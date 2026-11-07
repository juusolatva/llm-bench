set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

mkdir 'my dir' empty
touch 'my dir/a file.txt' 'my dir/b.txt' 'my dir/c.md' 'my dir/x.txt.bak'
bash "$SOL" 'my dir' txt log > out 2> err < /dev/null || fail "exit status $? ($(cat err))"
[ ! -s err ] || fail "unexpected stderr: $(cat err)"
(cd 'my dir' && ls -1 | sort) > got
printf '%s\n' 'a file.log' 'b.log' 'c.md' 'x.txt.bak' > want
cmp -s got want || { diff want got >&2; fail "wrong files after rename (want vs got above)"; }

bash "$SOL" empty txt log > out 2> err < /dev/null
rc=$?
[ "$rc" -eq 0 ] || fail "no matches: exit $rc, want 0"
[ ! -s err ] || fail "no matches: stderr not empty: $(cat err)"
echo ok
