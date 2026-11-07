package solution

import (
	"errors"
	"reflect"
	"strings"
	"testing"
	"testing/iotest"
)

func TestBasic(t *testing.T) {
	got, err := WordFreq(strings.NewReader("Hello, hello WORLD!\nworld? 42 42 x\n\ndon't"))
	want := map[string]int{"hello": 2, "world": 2, "42": 2, "x": 1, "don": 1, "t": 1}
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, %v; want %v", got, err, want)
	}
}

func TestEmptyAndUnicode(t *testing.T) {
	got, err := WordFreq(strings.NewReader(""))
	if err != nil || len(got) != 0 {
		t.Fatalf("empty input: got %v, %v", got, err)
	}
	got, err = WordFreq(strings.NewReader("Ünïcode ünïcode ÜNÏCODE"))
	if err != nil || got["ünïcode"] != 3 {
		t.Fatalf("unicode: got %v, %v", got, err)
	}
}

func TestLongLine(t *testing.T) {
	line := strings.Repeat("word ", 40000) // 200,000 bytes, no newline
	got, err := WordFreq(strings.NewReader(line))
	if err != nil || got["word"] != 40000 {
		t.Fatalf("long line: got %d, %v", got["word"], err)
	}
}

func TestReadError(t *testing.T) {
	boom := errors.New("boom")
	_, err := WordFreq(iotest.ErrReader(boom))
	if !errors.Is(err, boom) {
		t.Fatalf("got err %v, want boom", err)
	}
}
