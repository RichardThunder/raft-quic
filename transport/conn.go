package transport

import (
	"context"
	"crypto/tls"
	"sync"

	"github.com/quic-go/quic-go"
)

// peerConn holds a single persistent QUIC connection to a remote peer.
// Streams are multiplexed over this single connection.
type peerConn struct {
	addr      string
	clientTLS *tls.Config

	mu   sync.Mutex
	conn quic.Connection
}

func newPeerConn(addr string, clientTLS *tls.Config) *peerConn {
	return &peerConn{addr: addr, clientTLS: clientTLS}
}

// getOrDial returns the existing QUIC connection or dials a new one.
func (p *peerConn) getOrDial(ctx context.Context) (quic.Connection, error) {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.conn != nil {
		// Check if the connection is still alive.
		select {
		case <-p.conn.Context().Done():
			p.conn = nil
		default:
			return p.conn, nil
		}
	}

	conn, err := quic.DialAddr(ctx, p.addr, p.clientTLS, quicConfig())
	if err != nil {
		return nil, err
	}
	p.conn = conn
	return conn, nil
}

// close shuts down the connection if open.
func (p *peerConn) close() {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.conn != nil {
		p.conn.CloseWithError(0, "shutdown")
		p.conn = nil
	}
}
