set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT

printf 'The cat and the hat.\nTHE end, cat! Zebra zebra\n' > "$T/in put.txt"
printf '%s\n' '3 the' '2 cat' '2 zebra' > "$T/want"
bash "$SOL" "$T/in put.txt" > "$T/out" 2> "$T/err" < /dev/null || fail "exit status $? ($(cat "$T/err"))"
cmp -s "$T/out" "$T/want" || { diff "$T/want" "$T/out" >&2; fail "case 1 output (want vs got above)"; }

printf 'b a b\n' > "$T/two"
printf '%s\n' '2 b' '1 a' > "$T/want"
bash "$SOL" "$T/two" > "$T/out" 2>/dev/null < /dev/null
cmp -s "$T/out" "$T/want" || { diff "$T/want" "$T/out" >&2; fail "fewer than 3 words (want vs got above)"; }

: > "$T/empty"
bash "$SOL" "$T/empty" > "$T/out" 2>/dev/null < /dev/null
[ ! -s "$T/out" ] || fail "empty file must print nothing"
echo ok
