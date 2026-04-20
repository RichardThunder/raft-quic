// tcp-server runs a Raft cluster node using hashicorp/raft's built-in TCP transport.
// It exposes the same HTTP API as cmd/raftd so the benchmark can compare
// Raft-over-TCP against Raft-over-QUIC on equal footing.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net"
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
		bindAddr         = flag.String("bind", "127.0.0.1:9007", "TCP Raft listen address (host:port)")
		advertise        = flag.String("advertise", "", "TCP Raft address advertised to peers (defaults to -bind)")
		httpAddr         = flag.String("http", "127.0.0.1:9001", "HTTP API listen address")
		dataDir          = flag.String("data", "", "Snapshot directory (empty = in-memory)")
		joinAddr         = flag.String("join", "", "HTTP address of cluster member to join")
		joinRetries      = flag.Int("join-retries", 10, "Retry attempts when joining")
		heartbeatTimeout = flag.Duration("heartbeat-timeout", 0, "Raft heartbeat timeout (0 = 100 ms)")
		electionTimeout  = flag.Duration("election-timeout", 0, "Raft election timeout (0 = 2×heartbeat)")
	)
	flag.Parse()

	if *nodeID == "" {
		fmt.Fprintln(os.Stderr, "error: -id is required")
		flag.Usage()
		os.Exit(1)
	}

	effectiveAdvertise := *advertise
	if effectiveAdvertise == "" {
		effectiveAdvertise = *bindAddr
	}

	logger := hclog.New(&hclog.LoggerOptions{
		Name:   *nodeID,
		Level:  hclog.Info,
		Output: os.Stderr,
	})

	// Build TCP transport.
	advertiseAddr, err := net.ResolveTCPAddr("tcp", effectiveAdvertise)
	if err != nil {
		log.Fatalf("resolve advertise addr: %v", err)
	}
	tcpTransport, err := raft.NewTCPTransportWithLogger(
		*bindAddr, advertiseAddr, 3, 10*time.Second, logger)
	if err != nil {
		log.Fatalf("create tcp transport: %v", err)
	}

	bootstrap := *joinAddr == ""

	n, err := nodemod.New(nodemod.Config{
		NodeID:           *nodeID,
		AdvertiseAddr:    effectiveAdvertise,
		DataDir:          *dataDir,
		Bootstrap:        bootstrap,
		HeartbeatTimeout: *heartbeatTimeout,
		ElectionTimeout:  *electionTimeout,
		Transport:        tcpTransport,
		Logger:           logger,
	})
	if err != nil {
		log.Fatalf("create node: %v", err)
	}

	if !bootstrap {
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

	httpServer := &http.Server{Addr: *httpAddr, Handler: mux}
	go func() {
		logger.Info("HTTP API listening", "addr", *httpAddr)
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("http: %v", err)
		}
	}()

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

func (s *server) handleLeader(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintln(w, string(s.node.Raft.Leader()))
}

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
		raft.ServerID(id), raft.ServerAddress(addr), 0, 5*time.Second)
	if err := future.Error(); err != nil {
		http.Error(w, fmt.Sprintf("add voter: %v", err), http.StatusInternalServerError)
		return
	}
	fmt.Fprintln(w, "ok")
}

func (s *server) handleStatus(w http.ResponseWriter, r *http.Request) {
	metrics := s.node.GetMetrics()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(metrics)
}
