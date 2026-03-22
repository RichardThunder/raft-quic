package node

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"time"

	hclog "github.com/hashicorp/go-hclog"
	"github.com/hashicorp/raft"
	"github.com/richard/raft-quic/fsm"
	"github.com/richard/raft-quic/transport"
)

// Config holds the configuration for a Raft node.
type Config struct {
	// NodeID is the unique identifier for this node.
	NodeID string
	// BindAddr is the QUIC listen address (host:port).
	BindAddr string
	// AdvertiseAddr is the address advertised to peers. Defaults to BindAddr.
	// Set this when the bind address is not reachable by other nodes (e.g. 0.0.0.0 in Docker).
	AdvertiseAddr string
	// DataDir is the directory for snapshots. If empty, an in-memory snapshot store is used.
	DataDir string
	// Bootstrap indicates this node should bootstrap the cluster.
	Bootstrap bool
	// JoinAddr is the HTTP address of the leader to join (optional).
	JoinAddr string

	// HeartbeatTimeout overrides the default 100 ms. Increase for high-latency
	// networks (e.g. cross-region: 1 s).  Zero means use the default.
	HeartbeatTimeout time.Duration
	// ElectionTimeout overrides the default 200 ms. Should be ≥ 2×HeartbeatTimeout.
	ElectionTimeout time.Duration

	Logger hclog.Logger
}

// Node wraps a Raft instance and its dependencies.
type Node struct {
	Raft      *raft.Raft
	FSM       *fsm.KVStateMachine
	Transport *transport.QuicTransport
	logger    hclog.Logger
}

// New creates and starts a new Raft node.
func New(cfg Config) (*Node, error) {
	logger := cfg.Logger
	if logger == nil {
		logger = hclog.New(&hclog.LoggerOptions{
			Name:   fmt.Sprintf("raft[%s]", cfg.NodeID),
			Level:  hclog.Info,
			Output: os.Stderr,
		})
	}

	// Resolve effective advertise address.
	advertise := cfg.AdvertiseAddr
	if advertise == "" {
		advertise = cfg.BindAddr
	}

	// Generate TLS config.
	serverTLS, clientTLS, err := transport.GenerateTLSConfig()
	if err != nil {
		return nil, fmt.Errorf("generate tls: %w", err)
	}

	// Create transport.
	qt, err := transport.NewQuicTransport(cfg.BindAddr, advertise, serverTLS, clientTLS, logger)
	if err != nil {
		return nil, fmt.Errorf("create transport: %w", err)
	}

	// Create FSM.
	kv := fsm.New()

	// Create log store and stable store (in-memory for PoC).
	logStore := raft.NewInmemStore()
	stableStore := raft.NewInmemStore()

	// Create snapshot store.
	var snapshotStore raft.SnapshotStore
	if cfg.DataDir != "" {
		if err := os.MkdirAll(cfg.DataDir, 0755); err != nil {
			return nil, fmt.Errorf("mkdir %s: %w", cfg.DataDir, err)
		}
		snapshotStore, err = raft.NewFileSnapshotStore(
			filepath.Join(cfg.DataDir, "snapshots"), 2, os.Stderr)
		if err != nil {
			return nil, fmt.Errorf("snapshot store: %w", err)
		}
	} else {
		snapshotStore = raft.NewInmemSnapshotStore()
	}

	// Raft configuration.
	hbTimeout := 100 * time.Millisecond
	if cfg.HeartbeatTimeout > 0 {
		hbTimeout = cfg.HeartbeatTimeout
	}
	elTimeout := 2 * hbTimeout
	if cfg.ElectionTimeout > 0 {
		elTimeout = cfg.ElectionTimeout
	}

	raftCfg := raft.DefaultConfig()
	raftCfg.LocalID = raft.ServerID(cfg.NodeID)
	raftCfg.HeartbeatTimeout = hbTimeout
	raftCfg.ElectionTimeout = elTimeout
	raftCfg.CommitTimeout = hbTimeout / 2
	raftCfg.LeaderLeaseTimeout = hbTimeout
	raftCfg.Logger = logger

	// Create Raft.
	r, err := raft.NewRaft(raftCfg, kv, logStore, stableStore, snapshotStore, qt)
	if err != nil {
		qt.Close()
		return nil, fmt.Errorf("new raft: %w", err)
	}

	// Bootstrap or join.
	if cfg.Bootstrap {
		configuration := raft.Configuration{
			Servers: []raft.Server{
				{
					ID:      raft.ServerID(cfg.NodeID),
					Address: raft.ServerAddress(advertise),
				},
			},
		}
		future := r.BootstrapCluster(configuration)
		if err := future.Error(); err != nil {
			qt.Close()
			return nil, fmt.Errorf("bootstrap: %w", err)
		}
		logger.Info("cluster bootstrapped")
	}

	return &Node{
		Raft:      r,
		FSM:       kv,
		Transport: qt,
		logger:    logger,
	}, nil
}

// JoinCluster asks the leader at leaderHTTP to add this node.
func JoinCluster(leaderHTTP, nodeID, bindAddr string) error {
	url := fmt.Sprintf("http://%s/join?id=%s&addr=%s", leaderHTTP, nodeID, bindAddr)
	resp, err := http.Post(url, "", nil)
	if err != nil {
		return fmt.Errorf("join request: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("join failed with status %s", resp.Status)
	}
	return nil
}

// Shutdown gracefully stops the node.
func (n *Node) Shutdown() error {
	future := n.Raft.Shutdown()
	if err := future.Error(); err != nil {
		return err
	}
	return n.Transport.Close()
}
