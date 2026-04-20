package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	hclog "github.com/hashicorp/go-hclog"
	"github.com/hashicorp/raft"
	"github.com/richard/raft-quic/fsm"
	nodemod "github.com/richard/raft-quic/node"
)

func main() {
	var (
		nodeID           = flag.String("id", "", "Node ID (required)")
		bindAddr         = flag.String("bind", "127.0.0.1:7001", "QUIC bind address")
		advertise        = flag.String("advertise", "", "QUIC advertise address (default = bind); set this in Docker/AWS to the routable address")
		httpAddr         = flag.String("http", "127.0.0.1:8001", "HTTP API listen address")
		dataDir          = flag.String("data", "", "Data directory (empty = in-memory)")
		joinAddr         = flag.String("join", "", "HTTP address of an existing cluster member to join")
		joinRetries      = flag.Int("join-retries", 10, "Number of join attempts before giving up")
		heartbeatTimeout = flag.Duration("heartbeat-timeout", 0, "Raft heartbeat timeout (0 = 100 ms default; use ≥500ms for cross-region)")
		electionTimeout  = flag.Duration("election-timeout", 0, "Raft election timeout (0 = 2×heartbeat)")
	)
	flag.Parse()

	effectiveAdvertise := *advertise
	if effectiveAdvertise == "" {
		effectiveAdvertise = *bindAddr
	}

	if *nodeID == "" {
		fmt.Fprintln(os.Stderr, "error: -id is required")
		flag.Usage()
		os.Exit(1)
	}

	logger := hclog.New(&hclog.LoggerOptions{
		Name:   *nodeID,
		Level:  hclog.Info,
		Output: os.Stderr,
	})

	bootstrap := *joinAddr == ""

	n, err := nodemod.New(nodemod.Config{
		NodeID:           *nodeID,
		BindAddr:         *bindAddr,
		AdvertiseAddr:    effectiveAdvertise,
		DataDir:          *dataDir,
		Bootstrap:        bootstrap,
		HeartbeatTimeout: *heartbeatTimeout,
		ElectionTimeout:  *electionTimeout,
		Logger:           logger,
	})
	if err != nil {
		log.Fatalf("create node: %v", err)
	}

	// If joining, retry with backoff until the leader is ready.
	if *joinAddr != "" {
		time.Sleep(500 * time.Millisecond)
		var joinErr error
		for i := 0; i < *joinRetries; i++ {
			joinErr = nodemod.JoinCluster(*joinAddr, *nodeID, effectiveAdvertise)
			if joinErr == nil {
				break
			}
			logger.Warn("join attempt failed, retrying", "attempt", i+1, "of", *joinRetries, "err", joinErr)
			time.Sleep(2 * time.Second)
		}
		if joinErr != nil {
			log.Fatalf("join cluster: %v", joinErr)
		}
		logger.Info("joined cluster", "leader_http", *joinAddr)
	}

	srv := &server{node: n, logger: logger}
	mux := http.NewServeMux()
	mux.HandleFunc("/set", srv.handleSet)
	mux.HandleFunc("/get", srv.handleGet)
	mux.HandleFunc("/leader", srv.handleLeader)
	mux.HandleFunc("/join", srv.handleJoin)
	mux.HandleFunc("/status", srv.handleStatus)

	httpServer := &http.Server{
		Addr:    *httpAddr,
		Handler: mux,
	}

	go func() {
		logger.Info("HTTP API listening", "addr", *httpAddr)
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("http: %v", err)
		}
	}()

	// Wait for termination signal.
	ch := make(chan os.Signal, 1)
	signal.Notify(ch, syscall.SIGINT, syscall.SIGTERM)
	<-ch
	logger.Info("shutting down")
	_ = httpServer.Close()
	_ = n.Shutdown()
}

type server struct {
	node   *nodemod.Node
	logger hclog.Logger
}

// handleSet writes a key/value pair via Raft.
// POST /set?key=K&value=V
func (s *server) handleSet(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}
	key := r.URL.Query().Get("key")
	value := r.URL.Query().Get("value")
	if key == "" {
		http.Error(w, "key required", http.StatusBadRequest)
		return
	}

	if s.node.Raft.State() != raft.Leader {
		leader := string(s.node.Raft.Leader())
		http.Error(w, fmt.Sprintf("not leader; leader is %s", leader), http.StatusServiceUnavailable)
		return
	}

	cmd := fsm.Command{Op: "set", Key: key, Value: value}
	data, _ := json.Marshal(cmd)

	future := s.node.Raft.Apply(data, 5*time.Second)
	if err := future.Error(); err != nil {
		http.Error(w, fmt.Sprintf("apply failed: %v", err), http.StatusInternalServerError)
		return
	}
	fmt.Fprintln(w, "ok")
}

// handleGet reads a key from the local FSM (stale read acceptable for PoC).
// GET /get?key=K
func (s *server) handleGet(w http.ResponseWriter, r *http.Request) {
	key := r.URL.Query().Get("key")
	if key == "" {
		http.Error(w, "key required", http.StatusBadRequest)
		return
	}
	val, ok := s.node.FSM.Get(key)
	if !ok {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	fmt.Fprintln(w, val)
}

// handleLeader returns the current leader address.
// GET /leader
func (s *server) handleLeader(w http.ResponseWriter, r *http.Request) {
	leader := string(s.node.Raft.Leader())
	if leader == "" {
		fmt.Fprintln(w, "(no leader)")
		return
	}
	fmt.Fprintln(w, leader)
}

// handleJoin adds a new server to the cluster. Only works on the leader.
// POST /join?id=ID&addr=ADDR
func (s *server) handleJoin(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST required", http.StatusMethodNotAllowed)
		return
	}
	id := r.URL.Query().Get("id")
	addr := r.URL.Query().Get("addr")
	if id == "" || addr == "" {
		http.Error(w, "id and addr required", http.StatusBadRequest)
		return
	}

	if s.node.Raft.State() != raft.Leader {
		http.Error(w, "not leader", http.StatusServiceUnavailable)
		return
	}

	future := s.node.Raft.AddVoter(
		raft.ServerID(id),
		raft.ServerAddress(addr),
		0, 5*time.Second,
	)
	if err := future.Error(); err != nil {
		http.Error(w, fmt.Sprintf("add voter: %v", err), http.StatusInternalServerError)
		return
	}
	s.logger.Info("node joined", "id", id, "addr", addr)
	fmt.Fprintln(w, "ok")
}

// handleStatus returns Raft state information as JSON.
// GET /status
func (s *server) handleStatus(w http.ResponseWriter, r *http.Request) {
	metrics := s.node.GetMetrics()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(metrics)
}
