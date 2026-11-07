package solution

import (
	"io"
	"net/http"
	"strings"
	"sync"
)

type store struct {
	mu   sync.RWMutex
	data map[string][]byte
}

// NewHandler returns an HTTP handler for an in-memory key-value store under /kv/{key}.
func NewHandler() http.Handler {
	return &store{data: map[string][]byte{}}
}

func (s *store) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	key, ok := strings.CutPrefix(r.URL.Path, "/kv/")
	if !ok || key == "" || strings.Contains(key, "/") {
		http.NotFound(w, r)
		return
	}
	switch r.Method {
	case http.MethodPut:
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		s.mu.Lock()
		s.data[key] = body
		s.mu.Unlock()
		w.WriteHeader(http.StatusNoContent)
	case http.MethodGet:
		s.mu.RLock()
		value, found := s.data[key]
		s.mu.RUnlock()
		if !found {
			http.NotFound(w, r)
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(value)
	case http.MethodDelete:
		s.mu.Lock()
		_, found := s.data[key]
		delete(s.data, key)
		s.mu.Unlock()
		if !found {
			http.NotFound(w, r)
			return
		}
		w.WriteHeader(http.StatusNoContent)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}
