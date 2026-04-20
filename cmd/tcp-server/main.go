package main

import (
	"flag"
	"fmt"
	"log"
	"net/http"
	"sync"
)

var (
	bind = flag.String("bind", "localhost:9001", "TCP server bind address")
)

type Store struct {
	mu   sync.RWMutex
	data map[string]string
}

func (s *Store) Set(key, value string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data[key] = value
}

func (s *Store) Get(key string) (string, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	val, ok := s.data[key]
	return val, ok
}

func handleSet(store *Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		key := r.URL.Query().Get("key")
		value := r.URL.Query().Get("value")
		if key == "" || value == "" {
			http.Error(w, "missing key or value", http.StatusBadRequest)
			return
		}
		store.Set(key, value)
		w.WriteHeader(http.StatusOK)
		fmt.Fprintf(w, "OK")
	}
}

func handleGet(store *Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		key := r.URL.Query().Get("key")
		if key == "" {
			http.Error(w, "missing key", http.StatusBadRequest)
			return
		}
		val, ok := store.Get(key)
		if !ok {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusOK)
		fmt.Fprintf(w, "%s", val)
	}
}

func handleStatus(store *Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		store.mu.RLock()
		size := len(store.data)
		store.mu.RUnlock()
		w.WriteHeader(http.StatusOK)
		fmt.Fprintf(w, `{"status":"ok","keys":%d}`, size)
	}
}

func main() {
	flag.Parse()

	store := &Store{
		data: make(map[string]string),
	}

	http.HandleFunc("/set", handleSet(store))
	http.HandleFunc("/get", handleGet(store))
	http.HandleFunc("/status", handleStatus(store))

	log.Printf("TCP server listening on %s", *bind)
	log.Fatal(http.ListenAndServe(*bind, nil))
}
