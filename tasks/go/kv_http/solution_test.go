package solution

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
)

// TestMain prints the harness's final line only after every test passed. The benchmark requires it, so a
// solution that ends the process early (e.g. os.Exit(0) in an init function) fails.
func TestMain(m *testing.M) {
	code := m.Run()
	if code == 0 {
		fmt.Println("harness: all checks passed")
	}
	os.Exit(code)
}

func harnessDo(h http.Handler, method, path, body string) (int, string) {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec.Code, rec.Body.String()
}

// harnessSession makes handlers with NewHandler and sends them requests, recording every step, so a failure can
// show everything that happened before it.
type harnessSession struct {
	t   *testing.T
	log []string
}

type harnessHandler struct {
	name string
	h    http.Handler
}

func (s *harnessSession) newHandler(name string) *harnessHandler {
	s.log = append(s.log, name+" := NewHandler()")
	return &harnessHandler{name, NewHandler()}
}

// expect sends a request to hh and checks the status code and, if want is given, the body.
func (s *harnessSession) expect(hh *harnessHandler, method, path, body string, code int, want ...string) {
	s.t.Helper()
	step := fmt.Sprintf("%s: %s %s with body %q", hh.name, method, path, body)
	got, b := harnessDo(hh.h, method, path, body)
	if got != code || (len(want) > 0 && b != want[0]) {
		wantBody := ""
		if len(want) > 0 {
			wantBody = fmt.Sprintf(" %q", want[0])
		}
		s.t.Fatalf("after %s: %s: got %d %q, want %d%s", strings.Join(s.log, "; "), step, got, b, code, wantBody)
	}
	s.log = append(s.log, step)
}

func TestCRUD(t *testing.T) {
	s := &harnessSession{t: t}
	h := s.newHandler("h")
	s.expect(h, "GET", "/kv/a", "", 404)
	s.expect(h, "PUT", "/kv/a", "hello", 204)
	s.expect(h, "GET", "/kv/a", "", 200, "hello")
	s.expect(h, "PUT", "/kv/a", "world", 204)
	s.expect(h, "GET", "/kv/a", "", 200, "world")
	s.expect(h, "DELETE", "/kv/a", "", 204)
	s.expect(h, "GET", "/kv/a", "", 404)
	s.expect(h, "DELETE", "/kv/a", "", 404)
	s.expect(h, "POST", "/kv/a", "x", 405)
	s.expect(h, "PATCH", "/kv/a", "x", 405)
	s.expect(h, "POST", "/kv/", "x", 404)
	s.expect(h, "POST", "/other", "x", 404)
	s.expect(h, "DELETE", "/kv/a/b", "", 404)
	s.expect(h, "GET", "/kv/", "", 404)
	s.expect(h, "GET", "/other", "", 404)
	s.expect(h, "GET", "/kv/a/b", "", 404)
	s.expect(h, "GET", "/kv", "", 404)
	s.expect(h, "PUT", "/kv/empty", "", 204)
	s.expect(h, "GET", "/kv/empty", "", 200, "")
	h2 := s.newHandler("h2")
	s.expect(h, "PUT", "/kv/x", "1", 204)
	s.expect(h2, "GET", "/kv/x", "", 404)
}

func TestConcurrent(t *testing.T) {
	h := NewHandler()
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			key := fmt.Sprintf("/kv/k%d", i)
			for j := 0; j < 20; j++ {
				val := fmt.Sprintf("%d-%d", i, j)
				if c, _ := harnessDo(h, "PUT", key, val); c != 204 {
					t.Errorf("concurrent PUT %s with body %q: got %d, want 204", key, val, c)
					return
				}
				if c, b := harnessDo(h, "GET", key, ""); c != 200 || b != val {
					t.Errorf("concurrent GET %s right after PUT %q: got %d %q, want 200 %q", key, val, c, b, val)
					return
				}
			}
		}(i)
	}
	wg.Wait()
}
