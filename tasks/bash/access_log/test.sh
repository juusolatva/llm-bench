set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
# check NAME: run the solution on the log $T/NAME and compare its output with $T/want.
check() {
    bash "$SOL" "$T/$1" > "$T/out" 2> "$T/err" < /dev/null
    local rc=$?
    if [ "$rc" -ne 0 ] || ! cmp -s "$T/out" "$T/want"; then
        printf '===== input file "%s":\n' "$1" >&2; cat "$T/$1" >&2; printf '===== end of input\n' >&2
        [ "$rc" -eq 0 ] || fail "bash solution.sh '$1': exit status $rc, want 0 (stderr: $(cat "$T/err"))"
        diff "$T/want" "$T/out" >&2
        fail "bash solution.sh '$1': wrong output (diff above: < want, > got)"
    fi
}
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT

cat > "$T/access log" <<'EOF'
127.0.0.1 - - [10/Oct/2024:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326
10.0.0.5 - bob [10/Oct/2024:13:55:40 +0000] "GET /missing HTTP/1.1" 404 512

10.0.0.6 - - [10/Oct/2024:13:56:01 +0000] "POST /api/items HTTP/1.1" 500 -
127.0.0.1 - - [10/Oct/2024:13:57:12 +0000] "GET /search?q=a b HTTP/1.1" 200 1000
192.168.1.9 - - [10/Oct/2024:13:58:00 +0000] "GET /img.png HTTP/1.1" 304 -
127.0.0.1 - - [10/Oct/2024:13:59:59 +0000] "GET / HTTP/1.1" 200 74
EOF
printf '%s\n' '200 3' '304 1' '404 1' '500 1' 'total_bytes 3912' > "$T/want"
check "access log"

# Every size is "-": the total is 0, not empty.
cat > "$T/no sizes" <<'EOF'
10.0.0.6 - - [10/Oct/2024:13:56:01 +0000] "POST /api/items HTTP/1.1" 500 -
192.168.1.9 - - [10/Oct/2024:13:58:00 +0000] "GET /img.png HTTP/1.1" 304 -
EOF
printf '%s\n' '304 1' '500 1' 'total_bytes 0' > "$T/want"
check "no sizes"

: > "$T/empty log"
printf '%s\n' 'total_bytes 0' > "$T/want"
check "empty log"
echo 'harness: all checks passed'
