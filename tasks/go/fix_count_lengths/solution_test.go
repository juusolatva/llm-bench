package solution

import (
	"reflect"
	"strings"
	"testing"
)

func TestCountLengths(t *testing.T) {
	words := make([]string, 5000)
	want := map[int]int{}
	for i := range words {
		words[i] = strings.Repeat("x", i%17)
		want[i%17]++
	}
	for round := 0; round < 20; round++ {
		if got := CountLengths(words); !reflect.DeepEqual(got, want) {
			t.Fatalf("round %d: wrong counts", round)
		}
	}
	if got := CountLengths(nil); len(got) != 0 {
		t.Fatalf("nil input: got %v", got)
	}
}
