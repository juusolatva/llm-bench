package solution

import "testing"

func TestReverse(t *testing.T) {
	cases := map[string]string{"": "", "abc": "cba", "héllo": "olléh", "日本語": "語本日", "a😀b": "b😀a"}
	for in, want := range cases {
		if got := Reverse(in); got != want {
			t.Errorf("Reverse(%q) = %q, want %q", in, got, want)
		}
	}
}
