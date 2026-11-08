package solution

import (
	"errors"
	"reflect"
	"strings"
	"testing"
	"testing/iotest"
)

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

func TestReadError(t *testing.T) {
	boom := errors.New("boom")
	_, err := WordFreq(iotest.ErrReader(boom))
	if !errors.Is(err, boom) {
		t.Fatalf("WordFreq(reader whose Read fails with error \"boom\"): got error %v, want \"boom\"", err)
	}
}
