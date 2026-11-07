package solution

import (
	"bufio"
	"io"
	"strings"
	"unicode"
)

// WordFreq counts the lowercase words (runs of letters and digits) read from r.
func WordFreq(r io.Reader) (map[string]int, error) {
	counts := map[string]int{}
	br := bufio.NewReader(r)
	var word strings.Builder
	flush := func() {
		if word.Len() > 0 {
			counts[strings.ToLower(word.String())]++
			word.Reset()
		}
	}
	for {
		c, _, err := br.ReadRune()
		if err == io.EOF {
			flush()
			return counts, nil
		}
		if err != nil {
			return nil, err
		}
		if unicode.IsLetter(c) || unicode.IsDigit(c) {
			word.WriteRune(c)
		} else {
			flush()
		}
	}
}
