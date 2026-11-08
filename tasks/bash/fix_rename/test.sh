set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

mkdir -p 'my dir/sub dir' empty
touch 'my dir/a file.txt' 'my dir/b.txt' 'my dir/c.md' 'my dir/x.txt.bak' 'my dir/y.txt.txt' 'my dir/sub dir/z.txt'
case1="bash solution.sh 'my dir' txt log, with files 'a file.txt' 'b.txt' 'c.md' 'x.txt.bak' 'y.txt.txt' 'sub dir/z.txt' in 'my dir'"
bash "$SOL" 'my dir' txt log > out 2> err < /dev/null || fail "$case1: exit status $?, want 0 (stderr: $(cat err))"
[ ! -s err ] || fail "$case1: unexpected stderr: $(cat err)"
(cd 'my dir' && find . -type f | sort) > got
printf '%s\n' './a file.log' './b.log' './c.md' './sub dir/z.txt' './x.txt.bak' './y.txt.log' > want
cmp -s got want || { diff want got >&2; fail "$case1: wrong files in 'my dir' afterwards (diff above: < want, > got)"; }

case2="bash solution.sh empty txt log, with no files in the directory 'empty'"
bash "$SOL" empty txt log > out 2> err < /dev/null
rc=$?
[ "$rc" -eq 0 ] || fail "$case2: exit status $rc, want 0"
[ ! -s err ] || fail "$case2: stderr not empty: $(cat err)"
echo ok
