set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
# check FILE NAME [any-exit]: run the solution on FILE and compare its output with $T/want; NAME is the file
# name shown in messages. The exit status must be 0 unless the third argument is "any-exit".
check() {
    bash "$SOL" "$1" > "$T/out" 2> "$T/err" < /dev/null
    local rc=$?
    [ "${3-}" = any-exit ] && rc=0
    if [ "$rc" -ne 0 ] || ! cmp -s "$T/out" "$T/want"; then
        printf '===== input file "%s":\n' "$2" >&2; cat "$1" >&2; printf '===== end of input\n' >&2
        [ "$rc" -eq 0 ] || fail "bash solution.sh '$2': exit status $rc, want 0 (stderr: $(cat "$T/err"))"
        diff "$T/want" "$T/out" >&2
        fail "bash solution.sh '$2': wrong output (diff above: < want, > got)"
    fi
}
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT

printf 'The cat and the hat.\nTHE end, cat! Zebra zebra\n' > "$T/in put.txt"
printf '%s\n' '3 the' '2 cat' '2 zebra' > "$T/want"
check "$T/in put.txt" "in put.txt"

printf 'b a b\n' > "$T/two"
printf '%s\n' '2 b' '1 a' > "$T/want"
check "$T/two" "two" any-exit

: > "$T/empty"
: > "$T/want"
check "$T/empty" "empty" any-exit
echo ok
