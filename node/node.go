package node

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
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

	// Metrics
	mu                     sync.RWMutex
	lastLeaderID           raft.ServerAddress
	lastState              raft.RaftState
	leaderChanges          int64
	electionTriggered      int64
	lastElectionTime       time.Time
	lastElectionDurationMs int64
	heartbeatTimeouts      int64
	lastHeartbeatTimeoutAt time.Time
	lastEntriesReplication time.Time
	lastReplicatedIndex    uint64
	entriesPerSecond       float64
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

	node := &Node{
		Raft:                   r,
		FSM:                    kv,
		Transport:              qt,
		logger:                 logger,
		lastEntriesReplication: time.Now(),
		lastReplicatedIndex:    r.LastIndex(),
		lastState:              r.State(),
		lastLeaderID:           r.Leader(),
	}

	// Start metrics monitoring goroutine
	go node.monitorMetrics()

	return node, nil
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

// monitorMetrics periodically checks for Raft state changes and updates metrics
func (n *Node) monitorMetrics() {
	ticker := time.NewTicker(500 * time.Millisecond)
	defer ticker.Stop()

	for range ticker.C {
		now := time.Now()
		currentLeaderID := n.Raft.Leader()
		currentState := n.Raft.State()
		lastLogIdx := n.Raft.LastIndex()

		n.mu.Lock()

		// Track leader changes
		if currentLeaderID != "" && n.lastLeaderID != "" && currentLeaderID != n.lastLeaderID {
			atomic.AddInt64(&n.leaderChanges, 1)
			n.logger.Info("leader changed", "old", n.lastLeaderID, "new", currentLeaderID)
		}

		// Track election transitions.
		if currentState == raft.Candidate && n.lastState != raft.Candidate {
			atomic.AddInt64(&n.electionTriggered, 1)
			n.lastElectionTime = now
			if n.lastState == raft.Follower {
				atomic.AddInt64(&n.heartbeatTimeouts, 1)
				n.lastHeartbeatTimeoutAt = now
			}
		}
		if currentState == raft.Leader && n.lastState == raft.Candidate && !n.lastElectionTime.IsZero() {
			n.lastElectionDurationMs = now.Sub(n.lastElectionTime).Milliseconds()
		}

		// Calculate entries replicated per second from last log index delta.
		timeDelta := now.Sub(n.lastEntriesReplication).Seconds()
		if timeDelta > 0 && lastLogIdx >= n.lastReplicatedIndex {
			entriesDelta := lastLogIdx - n.lastReplicatedIndex
			n.entriesPerSecond = float64(entriesDelta) / timeDelta
			n.lastReplicatedIndex = lastLogIdx
			n.lastEntriesReplication = now
		}

		n.lastLeaderID = currentLeaderID
		n.lastState = currentState

		n.mu.Unlock()
	}
}

// Metrics holds extracted metrics from Raft state
type Metrics struct {
	IsLeader               bool    `json:"is_leader"`
	LeaderID               string  `json:"leader_id"`
	Term                   uint64  `json:"term"`
	CommittedIndex         uint64  `json:"committed_index"`
	LastApplied            uint64  `json:"last_applied"`
	LastLogIndex           uint64  `json:"last_log_index"`
	ReplicationLag         int64   `json:"replication_lag"`
	PeersCount             int     `json:"peers_count"`
	LeaderChanges          int64   `json:"leader_changes"`
	ElectionTriggered      int64   `json:"election_triggered"`
	LastElectionDurationMs int64   `json:"last_election_duration_ms"`
	HeartbeatTimeouts      int64   `json:"heartbeat_timeouts"`
	EntriesPerSecond       float64 `json:"entries_per_second"`
}

// GetMetrics returns current Raft metrics
func (n *Node) GetMetrics() Metrics {
	stats := n.Raft.Stats()

	n.mu.RLock()
	defer n.mu.RUnlock()

	isLeader := n.Raft.State() == raft.Leader
	leaderID := string(n.Raft.Leader())
	term, _ := strconv.ParseUint(stats["term"], 10, 64)
	lastLogIdx := n.Raft.LastIndex()
	commitIdx := n.Raft.CommitIndex()
	lastAppliedIdx := n.Raft.AppliedIndex()
	numPeers, _ := strconv.Atoi(stats["num_peers"])
	peersCount := numPeers + 1
	if peersCount < 1 {
		peersCount = 1
	}

	return Metrics{
		IsLeader:               isLeader,
		LeaderID:               leaderID,
		Term:                   term,
		CommittedIndex:         commitIdx,
		LastApplied:            lastAppliedIdx,
		LastLogIndex:           lastLogIdx,
		ReplicationLag:         int64(lastLogIdx) - int64(commitIdx),
		PeersCount:             peersCount,
		LeaderChanges:          atomic.LoadInt64(&n.leaderChanges),
		ElectionTriggered:      atomic.LoadInt64(&n.electionTriggered),
		LastElectionDurationMs: n.lastElectionDurationMs,
		HeartbeatTimeouts:      atomic.LoadInt64(&n.heartbeatTimeouts),
		EntriesPerSecond:       n.entriesPerSecond,
	}
}
