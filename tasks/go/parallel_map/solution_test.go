package solution

import (
	"context"
	"errors"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// harnessTracker counts calls of f: started, currently active and the peak number active at once.
type harnessTracker struct {
	active, peak, started atomic.Int64
}

// enter records the start of a call.
func (h *harnessTracker) enter() {
	h.started.Add(1)
	n := h.active.Add(1)
	for {
		p := h.peak.Load()
		if n <= p || h.peak.CompareAndSwap(p, n) {
			return
		}
	}
}

// leave records the end of a call.
func (h *harnessTracker) leave() { h.active.Add(-1) }

func TestOrderAndConcurrency(t *testing.T) {
	for _, workers := range []int{1, 7} {
		var h harnessTracker
		inputs := make([]int, 60)
		for i := range inputs {
			inputs[i] = i
		}
		got, err := ParallelMap(context.Background(), inputs, workers, func(ctx context.Context, x int) (int, error) {
			h.enter()
			defer h.leave()
			time.Sleep(time.Duration(5+x%3) * time.Millisecond)
			return x * x, nil
		})
		if err != nil {
			t.Fatalf("workers=%d: unexpected error %v", workers, err)
		}
		if len(got) != len(inputs) {
			t.Fatalf("workers=%d: got %d results, want %d", workers, len(got), len(inputs))
		}
		for i, v := range got {
			if v != i*i {
				t.Fatalf("workers=%d: result[%d] = %d, want %d (results must be in input order)", workers, i, v, i*i)
			}
		}
		if p := h.peak.Load(); p != int64(workers) {
			t.Fatalf("workers=%d: at most %d calls ran at the same time, want exactly %d", workers, p, workers)
		}
		if s := h.started.Load(); s != int64(len(inputs)) {
			t.Fatalf("workers=%d: f called %d times, want %d", workers, s, len(inputs))
		}
	}
}

func TestEmpty(t *testing.T) {
	got, err := ParallelMap(context.Background(), nil, 3, func(ctx context.Context, x int) (int, error) {
		t.Error("f called for empty inputs")
		return 0, nil
	})
	if err != nil || len(got) != 0 {
		t.Fatalf("empty inputs: got %v, %v; want [] and nil error", got, err)
	}
}

func TestErrorCancelsAndStops(t *testing.T) {
	const cs = "ParallelMap(inputs 0..999, workers 4) with f failing on input 10 after 20 ms and inputs > 10 running until canceled"
	boom := errors.New("boom")
	var h harnessTracker
	var mu sync.Mutex
	canceled := 0
	inputs := make([]int, 1000)
	for i := range inputs {
		inputs[i] = i
	}
	// Calls that are never canceled give up after 2 s, so a missing cancellation fails the test quickly.
	watchdog := make(chan struct{})
	time.AfterFunc(2*time.Second, func() { close(watchdog) })
	// ParallelMap cancels the context only after it has seen the error, so a call that starts with that
	// context already canceled was started after the error. One such call is tolerated: an implementation may
	// free the failing call's worker and hand it to the next input just before it records the error.
	var startedCanceled atomic.Int64
	start := time.Now()
	got, err := ParallelMap(context.Background(), inputs, 4, func(ctx context.Context, x int) (int, error) {
		if ctx.Err() != nil {
			startedCanceled.Add(1)
		}
		h.enter()
		defer h.leave()
		switch {
		case x < 10:
			return x, nil
		case x == 10:
			time.Sleep(20 * time.Millisecond)
			return 0, boom
		default:
			select {
			case <-ctx.Done():
				mu.Lock()
				canceled++
				mu.Unlock()
				return 0, ctx.Err()
			case <-watchdog:
				return x, nil
			}
		}
	})
	elapsed := time.Since(start)
	if elapsed > time.Second {
		t.Fatalf("%s: took %v; the context passed to running calls was not canceled after the error", cs, elapsed)
	}
	if !errors.Is(err, boom) || got != nil {
		t.Fatalf("%s: got %v, %v; want nil and the error returned by f (boom)", cs, got, err)
	}
	if a := h.active.Load(); a != 0 {
		t.Fatalf("%s: returned while %d calls of f were still running", cs, a)
	}
	if n := startedCanceled.Load(); n > 1 {
		t.Fatalf("%s: %d calls of f started after the error (their context was already canceled); no new calls may start after an error", cs, n)
	}
	// Inputs claim the 4 workers in order and 11-13 run until canceled, so inputs 0-13 can start before input 10
	// fails, plus at most one more (14) if a worker is freed before the error is recorded.
	s := h.started.Load()
	if s > 15 {
		t.Fatalf("%s: f was called %d times, want at most 15 (inputs 0-13 can start before input 10 fails; no new calls may start after the error)", cs, s)
	}
	if s > 11 && canceled == 0 {
		t.Fatalf("%s: no running call saw its context canceled", cs)
	}
}

func TestErrorWithOneWorker(t *testing.T) {
	const cs = "ParallelMap([0 1 2 3 4], workers 1) with f always failing"
	boom := errors.New("boom")
	var calls, startedCanceled atomic.Int64
	got, err := ParallelMap(context.Background(), []int{0, 1, 2, 3, 4}, 1, func(ctx context.Context, x int) (int, error) {
		calls.Add(1)
		if ctx.Err() != nil {
			startedCanceled.Add(1)
		}
		return 0, boom
	})
	if !errors.Is(err, boom) || got != nil {
		t.Fatalf("%s: got %v, %v; want nil and boom", cs, got, err)
	}
	// As above, one call that races with recording the first error is tolerated.
	if n := startedCanceled.Load(); n > 1 {
		t.Fatalf("%s: f was called %d times, %d of them after the error (their context was already canceled); no new calls may start after an error", cs, calls.Load(), n)
	}
}

func TestParentCancel(t *testing.T) {
	const cs = "ParallelMap(100 inputs, workers 3) with ctx canceled after 50 ms and f running until canceled"
	var h harnessTracker
	ctx, cancel := context.WithCancel(context.Background())
	inputs := make([]int, 100)
	time.AfterFunc(50*time.Millisecond, cancel)
	watchdog := make(chan struct{})
	time.AfterFunc(2*time.Second, func() { close(watchdog) })
	start := time.Now()
	stopped := errors.New("stopped")
	got, err := ParallelMap(ctx, inputs, 3, func(ctx context.Context, x int) (int, error) {
		h.enter()
		defer h.leave()
		select {
		case <-ctx.Done():
			return 0, stopped
		case <-watchdog:
			return x, nil
		}
	})
	if time.Since(start) > time.Second {
		t.Fatalf("%s: did not stop promptly after ctx was canceled (calls must get a context derived from ctx)", cs)
	}
	if !errors.Is(err, context.Canceled) || got != nil {
		t.Fatalf("%s: got %v, %v; want nil and context.Canceled (ctx.Err() wins over errors returned by f)", cs, got, err)
	}
	if a := h.active.Load(); a != 0 {
		t.Fatalf("%s: returned while %d calls of f were still running", cs, a)
	}
	if s := h.started.Load(); s > 6 {
		t.Fatalf("%s: f was called %d times, want at most 6; no new calls may start after ctx is canceled", cs, s)
	}
}

func TestAlreadyCanceled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	var calls atomic.Int64
	got, err := ParallelMap(ctx, []int{1, 2, 3}, 2, func(ctx context.Context, x int) (int, error) {
		calls.Add(1)
		return x, nil
	})
	if !errors.Is(err, context.Canceled) || got != nil {
		t.Fatalf("ParallelMap(already canceled ctx, [1 2 3], workers 2): got %v, %v; want nil and context.Canceled", got, err)
	}
	if n := calls.Load(); n != 0 {
		t.Fatalf("ParallelMap(already canceled ctx, [1 2 3], workers 2): f was called %d times, want 0 (no calls may start once ctx is canceled)", n)
	}
}
