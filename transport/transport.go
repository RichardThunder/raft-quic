package transport

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"sync"
	"time"

	hclog "github.com/hashicorp/go-hclog"
	"github.com/hashicorp/raft"
	"github.com/quic-go/quic-go"
)

const (
	rpcTimeout   = 10 * time.Second
	maxIdleConns = 100
	consumeQueue = 1024
)

// quicConfig returns the shared QUIC configuration used by both dial and listen.
func quicConfig() *quic.Config {
	return &quic.Config{
		MaxIdleTimeout:        30 * time.Second,
		KeepAlivePeriod:       10 * time.Second,
		MaxIncomingStreams:    1024,
		MaxIncomingUniStreams: -1, // disable unidirectional streams
	}
}

// QuicTransport implements raft.Transport using QUIC as the underlying transport.
type QuicTransport struct {
	logger    hclog.Logger
	localAddr raft.ServerAddress

	serverTLS *tls.Config
	clientTLS *tls.Config

	listener *quic.Listener

	// peers maps ServerAddress → peerConn
	peersMu sync.Mutex
	peers   map[raft.ServerAddress]*peerConn

	// heartbeatFn is called directly for heartbeat RPCs (AppendEntries with no entries).
	heartbeatFnMu sync.RWMutex
	heartbeatFn   func(raft.RPC)

	consumeCh chan raft.RPC

	shutdownCh chan struct{}
	shutdownMu sync.Mutex
	shutdown   bool
}

// NewQuicTransport creates a new QuicTransport bound to bindAddr and advertising
// advertiseAddr to peers (useful when the bind and routable addresses differ, e.g.
// inside Docker where bindAddr is "0.0.0.0:PORT" but peers reach the node via
// "hostname:PORT").  If advertiseAddr is empty it defaults to bindAddr.
func NewQuicTransport(bindAddr string, advertiseAddr string, serverTLS *tls.Config, clientTLS *tls.Config, logger hclog.Logger) (*QuicTransport, error) {
	if logger == nil {
		logger = hclog.Default()
	}
	if advertiseAddr == "" {
		advertiseAddr = bindAddr
	}

	listener, err := quic.ListenAddr(bindAddr, serverTLS, quicConfig())
	if err != nil {
		return nil, fmt.Errorf("quic listen %s: %w", bindAddr, err)
	}

	t := &QuicTransport{
		logger:     logger.Named("quic-transport"),
		localAddr:  raft.ServerAddress(advertiseAddr),
		serverTLS:  serverTLS,
		clientTLS:  clientTLS,
		listener:   listener,
		peers:      make(map[raft.ServerAddress]*peerConn),
		consumeCh:  make(chan raft.RPC, consumeQueue),
		shutdownCh: make(chan struct{}),
	}

	go t.acceptLoop()
	return t, nil
}

// LocalAddr implements raft.Transport.
func (t *QuicTransport) LocalAddr() raft.ServerAddress {
	return t.localAddr
}

// Consumer implements raft.Transport.
func (t *QuicTransport) Consumer() <-chan raft.RPC {
	return t.consumeCh
}

// SetHeartbeatHandler implements raft.Transport.
func (t *QuicTransport) SetHeartbeatHandler(cb func(rpc raft.RPC)) {
	t.heartbeatFnMu.Lock()
	defer t.heartbeatFnMu.Unlock()
	t.heartbeatFn = cb
}

// Close implements raft.Transport.
func (t *QuicTransport) Close() error {
	t.shutdownMu.Lock()
	defer t.shutdownMu.Unlock()
	if t.shutdown {
		return nil
	}
	t.shutdown = true
	close(t.shutdownCh)

	t.peersMu.Lock()
	for _, p := range t.peers {
		p.close()
	}
	t.peersMu.Unlock()

	return t.listener.Close()
}

// IsShutdown returns true after Close has been called.
func (t *QuicTransport) IsShutdown() bool {
	select {
	case <-t.shutdownCh:
		return true
	default:
		return false
	}
}

// ------------------------------------------------------------------ server side

func (t *QuicTransport) acceptLoop() {
	for {
		conn, err := t.listener.Accept(context.Background())
		if err != nil {
			if t.IsShutdown() {
				return
			}
			t.logger.Error("accept error", "err", err)
			continue
		}
		go t.handleConn(conn)
	}
}

func (t *QuicTransport) handleConn(conn quic.Connection) {
	for {
		stream, err := conn.AcceptStream(context.Background())
		if err != nil {
			if t.IsShutdown() {
				return
			}
			// Connection closed or idle timeout – normal.
			return
		}
		go t.handleStream(stream)
	}
}

func (t *QuicTransport) handleStream(stream quic.Stream) {
	defer stream.Close()

	rpcType, body, err := readFrame(stream)
	if err != nil {
		t.logger.Error("read frame", "err", err)
		return
	}

	respCh := make(chan raft.RPCResponse, 1)
	rpc := raft.RPC{RespChan: respCh}

	isHeartbeat := false

	switch rpcType {
	case rpcAppendEntries:
		var req raft.AppendEntriesRequest
		if err := json.Unmarshal(body, &req); err != nil {
			t.logger.Error("decode AppendEntries", "err", err)
			return
		}
		rpc.Command = &req
		isHeartbeat = req.Term != 0 && len(req.Entries) == 0

	case rpcRequestVote:
		var req raft.RequestVoteRequest
		if err := json.Unmarshal(body, &req); err != nil {
			t.logger.Error("decode RequestVote", "err", err)
			return
		}
		rpc.Command = &req

	case rpcInstallSnapshot:
		var req raft.InstallSnapshotRequest
		if err := json.Unmarshal(body, &req); err != nil {
			t.logger.Error("decode InstallSnapshot", "err", err)
			return
		}
		// Remaining bytes on the stream are the snapshot data.
		rpc.Command = &req
		rpc.Reader = stream

	case rpcTimeoutNow:
		var req raft.TimeoutNowRequest
		if err := json.Unmarshal(body, &req); err != nil {
			t.logger.Error("decode TimeoutNow", "err", err)
			return
		}
		rpc.Command = &req

	default:
		t.logger.Error("unknown rpc type", "type", rpcType)
		return
	}

	if isHeartbeat {
		t.heartbeatFnMu.RLock()
		fn := t.heartbeatFn
		t.heartbeatFnMu.RUnlock()
		if fn != nil {
			fn(rpc)
			goto sendResp
		}
	}

	select {
	case t.consumeCh <- rpc:
	case <-t.shutdownCh:
		return
	}

sendResp:
	select {
	case resp := <-respCh:
		if err := sendResponse(stream, resp); err != nil {
			t.logger.Error("send response", "err", err)
		}
	case <-t.shutdownCh:
	}
}

func sendResponse(w io.Writer, resp raft.RPCResponse) error {
	var errStr string
	if resp.Error != nil {
		errStr = resp.Error.Error()
	}
	type envelope struct {
		Resp  interface{} `json:"resp"`
		Error string      `json:"error,omitempty"`
	}
	data, err := json.Marshal(envelope{Resp: resp.Response, Error: errStr})
	if err != nil {
		return err
	}
	return writeFrame(w, 0x00, data) // type 0x00 = generic response
}

// ------------------------------------------------------------------ client side

func (t *QuicTransport) getPeerConn(target raft.ServerAddress) *peerConn {
	t.peersMu.Lock()
	defer t.peersMu.Unlock()
	p, ok := t.peers[target]
	if !ok {
		p = newPeerConn(string(target), t.clientTLS)
		t.peers[target] = p
	}
	return p
}

// openStream opens a new bidirectional QUIC stream to target.
func (t *QuicTransport) openStream(ctx context.Context, target raft.ServerAddress) (quic.Stream, error) {
	p := t.getPeerConn(target)
	conn, err := p.getOrDial(ctx)
	if err != nil {
		return nil, err
	}
	stream, err := conn.OpenStreamSync(ctx)
	if err != nil {
		// Connection might have died; reset and retry once.
		p.mu.Lock()
		p.conn = nil
		p.mu.Unlock()
		conn, err = p.getOrDial(ctx)
		if err != nil {
			return nil, err
		}
		return conn.OpenStreamSync(ctx)
	}
	return stream, nil
}

func (t *QuicTransport) sendRPC(target raft.ServerAddress, rpcType byte, req interface{}, resp interface{}) error {
	ctx, cancel := context.WithTimeout(context.Background(), rpcTimeout)
	defer cancel()

	stream, err := t.openStream(ctx, target)
	if err != nil {
		return fmt.Errorf("open stream to %s: %w", target, err)
	}
	defer stream.Close()

	body, err := json.Marshal(req)
	if err != nil {
		return err
	}
	if err := writeFrame(stream, rpcType, body); err != nil {
		return fmt.Errorf("write frame: %w", err)
	}

	_, respBody, err := readFrame(stream)
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}

	type envelope struct {
		Resp  json.RawMessage `json:"resp"`
		Error string          `json:"error,omitempty"`
	}
	var env envelope
	if err := json.Unmarshal(respBody, &env); err != nil {
		return fmt.Errorf("decode envelope: %w", err)
	}
	if env.Error != "" {
		return fmt.Errorf("remote error: %s", env.Error)
	}
	if resp != nil && len(env.Resp) > 0 {
		return json.Unmarshal(env.Resp, resp)
	}
	return nil
}

// AppendEntries implements raft.Transport.
func (t *QuicTransport) AppendEntries(id raft.ServerID, target raft.ServerAddress, args *raft.AppendEntriesRequest, resp *raft.AppendEntriesResponse) error {
	return t.sendRPC(target, rpcAppendEntries, args, resp)
}

// RequestVote implements raft.Transport.
func (t *QuicTransport) RequestVote(id raft.ServerID, target raft.ServerAddress, args *raft.RequestVoteRequest, resp *raft.RequestVoteResponse) error {
	return t.sendRPC(target, rpcRequestVote, args, resp)
}

// InstallSnapshot implements raft.Transport.
func (t *QuicTransport) InstallSnapshot(id raft.ServerID, target raft.ServerAddress, args *raft.InstallSnapshotRequest, resp *raft.InstallSnapshotResponse, data io.Reader) error {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	stream, err := t.openStream(ctx, target)
	if err != nil {
		return fmt.Errorf("open stream to %s: %w", target, err)
	}
	defer stream.Close()

	body, err := json.Marshal(args)
	if err != nil {
		return err
	}
	if err := writeFrame(stream, rpcInstallSnapshot, body); err != nil {
		return err
	}
	// Stream the snapshot data.
	if _, err := io.Copy(stream, data); err != nil {
		return fmt.Errorf("stream snapshot data: %w", err)
	}
	// Signal EOF on the write side so the receiver can start reading the response.
	// In quic-go, Close() on a stream sends FIN for writes while reads can continue.
	if err := stream.Close(); err != nil {
		return fmt.Errorf("finish snapshot stream: %w", err)
	}

	_, respBody, err := readFrame(stream)
	if err != nil {
		return fmt.Errorf("read snapshot response: %w", err)
	}
	type envelope struct {
		Resp  json.RawMessage `json:"resp"`
		Error string          `json:"error,omitempty"`
	}
	var env envelope
	if err := json.Unmarshal(respBody, &env); err != nil {
		return err
	}
	if env.Error != "" {
		return fmt.Errorf("remote error: %s", env.Error)
	}
	if len(env.Resp) > 0 {
		return json.Unmarshal(env.Resp, resp)
	}
	return nil
}

// TimeoutNow implements raft.Transport.
func (t *QuicTransport) TimeoutNow(id raft.ServerID, target raft.ServerAddress, args *raft.TimeoutNowRequest, resp *raft.TimeoutNowResponse) error {
	return t.sendRPC(target, rpcTimeoutNow, args, resp)
}

// AppendEntriesPipeline implements raft.Transport.
func (t *QuicTransport) AppendEntriesPipeline(id raft.ServerID, target raft.ServerAddress) (raft.AppendPipeline, error) {
	return newQuicPipeline(t, id, target)
}

// EncodePeer implements raft.Transport.
func (t *QuicTransport) EncodePeer(id raft.ServerID, addr raft.ServerAddress) []byte {
	return []byte(addr)
}

// DecodePeer implements raft.Transport.
func (t *QuicTransport) DecodePeer(buf []byte) raft.ServerAddress {
	return raft.ServerAddress(buf)
}

// Ensure QuicTransport implements raft.Transport at compile time.
var _ raft.Transport = (*QuicTransport)(nil)

// NetAddr returns the net.Addr of the listener.
func (t *QuicTransport) NetAddr() net.Addr {
	return t.listener.Addr()
}
