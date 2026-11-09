set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
show_input() { printf '===== input file "access log":\n' >&2; cat "$T/access log" >&2; printf '===== end of input\n' >&2; }
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
bash "$SOL" "$T/access log" > "$T/out" 2> "$T/err" < /dev/null || { rc=$?; show_input; fail "bash solution.sh 'access log': exit status $rc, want 0 (stderr: $(cat "$T/err"))"; }
cmp -s "$T/out" "$T/want" || { show_input; diff "$T/want" "$T/out" >&2; fail "bash solution.sh 'access log': wrong output (diff above: < want, > got)"; }
echo 'harness: all checks passed'
