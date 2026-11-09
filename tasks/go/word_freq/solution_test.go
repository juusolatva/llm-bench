package solution

import (
	"errors"
	"fmt"
	"os"
	"reflect"
	"strings"
	"testing"
	"testing/iotest"
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

func TestBasic(t *testing.T) {
	in := "Hello, hello WORLD!\nworld? 42 42 x\n\ndon't"
	got, err := WordFreq(strings.NewReader(in))
	want := map[string]int{"hello": 2, "world": 2, "42": 2, "x": 1, "don": 1, "t": 1}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("WordFreq(%q): got %v, %v; want %v, nil", in, got, err, want)
	}
}

func TestEmptyAndUnicode(t *testing.T) {
	got, err := WordFreq(strings.NewReader(""))
	if err != nil || len(got) != 0 {
		t.Fatalf("WordFreq(\"\"): got %v, %v; want an empty map, nil", got, err)
	}
	in := "Ünïcode ünïcode ÜNÏCODE"
	want := map[string]int{"ünïcode": 3}
	got, err = WordFreq(strings.NewReader(in))
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("WordFreq(%q): got %v, %v; want %v, nil", in, got, err, want)
	}
	// A reader that returns one byte per Read call: words and multi-byte letters span reads.
	in = "Wörd ünï wörd,ünï"
	want = map[string]int{"wörd": 2, "ünï": 2}
	got, err = WordFreq(iotest.OneByteReader(strings.NewReader(in)))
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("WordFreq(reader returning %q one byte per Read): got %v, %v; want %v, nil", in, got, err, want)
	}
}

func TestLongLine(t *testing.T) {
	line := strings.Repeat("word ", 40000) // 200,000 bytes, no newline
	got, err := WordFreq(strings.NewReader(line))
	if err != nil || got["word"] != 40000 || len(got) != 1 {
		t.Fatalf("WordFreq(strings.Repeat(\"word \", 40000)) (one 200000-byte line): got %d for \"word\" and %d distinct words, %v; want 40000, 1, nil",
			got["word"], len(got), err)
	}
}

func TestHugeLines(t *testing.T) {
	// Lines far above 64 KiB: a 2100000-byte line of short words, then a 100000-byte word on a line of its own.
	// The prompt sets no upper limit on line length.
	long := strings.Repeat("ab ", 700000)
	huge := strings.Repeat("x", 100000)
	got, err := WordFreq(strings.NewReader(long + "\n" + huge + "\n"))
	if err != nil || got["ab"] != 700000 || got[huge] != 1 || len(got) != 2 {
		t.Fatalf("WordFreq(strings.Repeat(\"ab \", 700000) + \"\\n\" + strings.Repeat(\"x\", 100000) + \"\\n\"): "+
			"(lines of 2100000 and 100000 bytes) got %d for \"ab\", %d for the 100000-letter word and %d distinct words, "+
			"error %v; want 700000, 1, 2, nil",
			got["ab"], got[huge], len(got), err)
	}
}

func TestReadError(t *testing.T) {
	boom := errors.New("boom")
	_, err := WordFreq(iotest.ErrReader(boom))
	if !errors.Is(err, boom) {
		t.Fatalf("WordFreq(reader whose Read fails with error \"boom\"): got error %v, want \"boom\"", err)
	}
}
