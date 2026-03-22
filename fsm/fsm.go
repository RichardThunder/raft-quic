package fsm

import (
	"encoding/json"
	"fmt"
	"io"
	"sync"

	"github.com/hashicorp/raft"
)

// Command is the operation applied to the KV store via Raft.
type Command struct {
	Op    string `json:"op"`    // "set" | "del"
	Key   string `json:"key"`
	Value string `json:"value,omitempty"`
}

// KVStateMachine is an in-memory key-value store that implements raft.FSM.
type KVStateMachine struct {
	mu   sync.RWMutex
	data map[string]string
}

// New returns an empty KVStateMachine.
func New() *KVStateMachine {
	return &KVStateMachine{data: make(map[string]string)}
}

// Apply implements raft.FSM.
func (k *KVStateMachine) Apply(log *raft.Log) interface{} {
	var cmd Command
	if err := json.Unmarshal(log.Data, &cmd); err != nil {
		return fmt.Errorf("decode command: %w", err)
	}

	k.mu.Lock()
	defer k.mu.Unlock()

	switch cmd.Op {
	case "set":
		k.data[cmd.Key] = cmd.Value
		return nil
	case "del":
		delete(k.data, cmd.Key)
		return nil
	default:
		return fmt.Errorf("unknown op: %s", cmd.Op)
	}
}

// Snapshot implements raft.FSM.
func (k *KVStateMachine) Snapshot() (raft.FSMSnapshot, error) {
	k.mu.RLock()
	defer k.mu.RUnlock()

	copy := make(map[string]string, len(k.data))
	for key, val := range k.data {
		copy[key] = val
	}
	return &kvSnapshot{data: copy}, nil
}

// Restore implements raft.FSM.
func (k *KVStateMachine) Restore(rc io.ReadCloser) error {
	defer rc.Close()

	var data map[string]string
	if err := json.NewDecoder(rc).Decode(&data); err != nil {
		return err
	}

	k.mu.Lock()
	defer k.mu.Unlock()
	k.data = data
	return nil
}

// Get returns the value for key (safe for concurrent reads).
func (k *KVStateMachine) Get(key string) (string, bool) {
	k.mu.RLock()
	defer k.mu.RUnlock()
	v, ok := k.data[key]
	return v, ok
}

// kvSnapshot implements raft.FSMSnapshot.
type kvSnapshot struct {
	data map[string]string
}

func (s *kvSnapshot) Persist(sink raft.SnapshotSink) error {
	if err := json.NewEncoder(sink).Encode(s.data); err != nil {
		sink.Cancel()
		return err
	}
	return sink.Close()
}

func (s *kvSnapshot) Release() {}
