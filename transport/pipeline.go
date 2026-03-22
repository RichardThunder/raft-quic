package transport

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/hashicorp/raft"
)

// inflightFuture tracks an in-flight AppendEntries call sent through the pipeline.
type inflightFuture struct {
	req       *raft.AppendEntriesRequest
	resp      *raft.AppendEntriesResponse
	startTime time.Time
	err       error
	done      chan struct{}
}

func (f *inflightFuture) Error() error                          { <-f.done; return f.err }
func (f *inflightFuture) Start() time.Time                      { return f.startTime }
func (f *inflightFuture) Request() *raft.AppendEntriesRequest   { return f.req }
func (f *inflightFuture) Response() *raft.AppendEntriesResponse { <-f.done; return f.resp }

// QuicPipeline implements raft.AppendPipeline.
// Each AppendEntries call opens a fresh QUIC stream (streams are cheap).
// A background goroutine reads responses and resolves futures.
type QuicPipeline struct {
	trans  *QuicTransport
	id     raft.ServerID
	target raft.ServerAddress

	doneCh   chan raft.AppendFuture
	inflight chan *inflightFuture

	shutdownOnce sync.Once
	shutdownCh   chan struct{}
}

func newQuicPipeline(t *QuicTransport, id raft.ServerID, target raft.ServerAddress) (*QuicPipeline, error) {
	p := &QuicPipeline{
		trans:      t,
		id:         id,
		target:     target,
		doneCh:     make(chan raft.AppendFuture, 16),
		inflight:   make(chan *inflightFuture, 16),
		shutdownCh: make(chan struct{}),
	}
	go p.decodingLoop()
	return p, nil
}

// AppendEntries implements raft.AppendPipeline.
func (p *QuicPipeline) AppendEntries(args *raft.AppendEntriesRequest, resp *raft.AppendEntriesResponse) (raft.AppendFuture, error) {
	select {
	case <-p.shutdownCh:
		return nil, fmt.Errorf("pipeline closed")
	default:
	}

	future := &inflightFuture{
		req:       args,
		resp:      resp,
		startTime: time.Now(),
		done:      make(chan struct{}),
	}

	// Send on a new stream.
	go func() {
		if err := p.sendOne(args, resp, future); err != nil {
			future.err = err
			close(future.done)
			select {
			case p.doneCh <- future:
			case <-p.shutdownCh:
			}
			return
		}
		// Successfully sent; decodingLoop will complete the future.
		select {
		case p.inflight <- future:
		case <-p.shutdownCh:
		}
	}()

	return future, nil
}

func (p *QuicPipeline) sendOne(args *raft.AppendEntriesRequest, resp *raft.AppendEntriesResponse, future *inflightFuture) error {
	ctx, cancel := context.WithTimeout(context.Background(), rpcTimeout)
	defer cancel()

	stream, err := p.trans.openStream(ctx, p.target)
	if err != nil {
		return err
	}
	defer stream.Close()

	body, err := json.Marshal(args)
	if err != nil {
		return err
	}
	if err := writeFrame(stream, rpcAppendEntries, body); err != nil {
		return err
	}

	_, respBody, err := readFrame(stream)
	if err != nil {
		return err
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

// decodingLoop waits for completed inflight futures and pushes them to doneCh.
func (p *QuicPipeline) decodingLoop() {
	for {
		select {
		case future := <-p.inflight:
			close(future.done)
			select {
			case p.doneCh <- future:
			case <-p.shutdownCh:
				return
			}
		case <-p.shutdownCh:
			return
		}
	}
}

// Consumer implements raft.AppendPipeline.
func (p *QuicPipeline) Consumer() <-chan raft.AppendFuture {
	return p.doneCh
}

// Close implements raft.AppendPipeline.
func (p *QuicPipeline) Close() error {
	p.shutdownOnce.Do(func() { close(p.shutdownCh) })
	return nil
}
