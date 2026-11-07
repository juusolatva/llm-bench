package solution

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

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
		t.Fatalf("%s %s: got %d %q, want %d %q", method, path, got, b, code, want)
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
	harnessExpect(t, h, "GET", "/kv/", "", 404, "")
	harnessExpect(t, h, "GET", "/other", "", 404, "")
	harnessExpect(t, h, "GET", "/kv/a/b", "", 404, "")
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
					t.Errorf("PUT %s: %d", key, c)
					return
				}
				if c, b := harnessDo(h, "GET", key, ""); c != 200 || b != val {
					t.Errorf("GET %s: %d %q, want %q", key, c, b, val)
					return
				}
			}
		}(i)
	}
	wg.Wait()
}
