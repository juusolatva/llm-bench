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

func harnessExpect(t *testing.T, h http.Handler, method, path, body string, code int, want string) {
	t.Helper()
	got, b := harnessDo(h, method, path, body)
	if got != code || (want != "" && b != want) {
		wantBody := ""
		if want != "" {
			wantBody = fmt.Sprintf(" %q", want)
		}
		t.Fatalf("%s %s with body %q: got %d %q, want %d%s", method, path, body, got, b, code, wantBody)
	}
}

func TestCRUD(t *testing.T) {
	h := NewHandler()
	harnessExpect(t, h, "GET", "/kv/a", "", 404, "")
	harnessExpect(t, h, "PUT", "/kv/a", "hello", 204, "")
	harnessExpect(t, h, "GET", "/kv/a", "", 200, "hello")
	harnessExpect(t, h, "PUT", "/kv/a", "world", 204, "")
	harnessExpect(t, h, "GET", "/kv/a", "", 200, "world")
	harnessExpect(t, h, "DELETE", "/kv/a", "", 204, "")
	harnessExpect(t, h, "GET", "/kv/a", "", 404, "")
	harnessExpect(t, h, "DELETE", "/kv/a", "", 404, "")
	harnessExpect(t, h, "POST", "/kv/a", "x", 405, "")
	harnessExpect(t, h, "PATCH", "/kv/a", "x", 405, "")
	harnessExpect(t, h, "POST", "/kv/", "x", 404, "")
	harnessExpect(t, h, "POST", "/other", "x", 404, "")
	harnessExpect(t, h, "DELETE", "/kv/a/b", "", 404, "")
	harnessExpect(t, h, "GET", "/kv/", "", 404, "")
	harnessExpect(t, h, "GET", "/other", "", 404, "")
	harnessExpect(t, h, "GET", "/kv/a/b", "", 404, "")
	harnessExpect(t, h, "GET", "/kv", "", 404, "")
	harnessExpect(t, h, "PUT", "/kv/empty", "", 204, "")
	if c, b := harnessDo(h, "GET", "/kv/empty", ""); c != 200 || b != "" {
		t.Fatalf("GET /kv/empty after PUT /kv/empty with body \"\": got %d %q, want 200 \"\"", c, b)
	}
	h2 := NewHandler()
	harnessExpect(t, h, "PUT", "/kv/x", "1", 204, "")
	harnessExpect(t, h2, "GET", "/kv/x", "", 404, "")
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
