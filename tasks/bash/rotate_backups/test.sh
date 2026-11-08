set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

# The modification times are deliberately not in name order.
setup() {
    rm -rf d; mkdir -p d/sub
    touch -d '2024-01-03' 'd/db 1.bak'
    touch -d '2024-01-01' 'd/db 2.bak'
    touch -d '2024-01-04' 'd/db 3.bak'
    touch -d '2024-01-02' 'd/db 4.bak'
    touch -d '2023-01-01' 'd/notes.txt'
    touch -d '2023-01-01' 'd/notes.bak.txt'
    touch -d '2023-01-01' 'd/xbak'
    touch -d '2020-01-01' 'd/sub/old.bak'
}
files="DIR d containing 'db 1.bak' (modified 2024-01-03), 'db 2.bak' (2024-01-01), 'db 3.bak' (2024-01-04), \
'db 4.bak' (2024-01-02), 'notes.txt', 'notes.bak.txt', 'xbak' (each 2023-01-01) and 'sub/old.bak' (2020-01-01)"
listing() { (cd d && find . -type f | sort); }

setup
bash "$SOL" d 2 > out 2> err < /dev/null || fail "bash solution.sh d 2 with $files: exit status $?, want 0 (stderr: $(cat err))"
printf '%s\n' './db 1.bak' './db 3.bak' './notes.bak.txt' './notes.txt' './sub/old.bak' './xbak' > want
listing > got
cmp -s got want || { diff want got >&2; fail "bash solution.sh d 2 with $files: wrong files left in d (diff above: < want, > got)"; }
sort out > got
printf '%s\n' 'd/db 2.bak' 'd/db 4.bak' > want
cmp -s got want || { diff want got >&2; fail "bash solution.sh d 2 with $files: wrong deleted paths printed, sorted here (diff above: < want, > got)"; }

setup
bash "$SOL" d 0 > out 2> err < /dev/null || fail "bash solution.sh d 0 with $files: exit status $?, want 0 (stderr: $(cat err))"
printf '%s\n' './notes.bak.txt' './notes.txt' './sub/old.bak' './xbak' > want
listing > got
cmp -s got want || { diff want got >&2; fail "bash solution.sh d 0 with $files: wrong files left in d, want every .bak directly in d deleted (diff above: < want, > got)"; }

setup
bash "$SOL" d 10 > out 2> err < /dev/null || fail "bash solution.sh d 10 with $files: exit status $?, want 0 (stderr: $(cat err))"
listing > got
setup
listing > want
cmp -s got want || { diff want got >&2; fail "bash solution.sh d 10 with $files: wrong files left in d, want nothing deleted (diff above: < want, > got)"; }
[ ! -s out ] || fail "bash solution.sh d 10 with $files: printed $(cat out), want no output (nothing deleted)"

setup
# usage_error ARG...: the solution must reject these arguments with exit status 1 and a message on stderr.
usage_error() {
    local shown rc
    shown=$(printf "'%s' " "$@")
    bash "$SOL" "$@" > out 2> err < /dev/null
    rc=$?
    [ "$rc" -eq 1 ] || fail "bash solution.sh ${shown}(wrong usage; d is a directory, d/notes.txt a file, nodir does not exist): exit status $rc, want 1"
    [ -s err ] || fail "bash solution.sh ${shown}(wrong usage): no error message on stderr"
}
usage_error d
usage_error d 1 x
usage_error d -1
usage_error d abc
usage_error d 1x
usage_error d ''
usage_error nodir 1
usage_error d/notes.txt 1
listing > got
setup
listing > want
cmp -s got want || { diff want got >&2; fail "wrong usage (arguments d; d 1 x; d -1; d abc; d 1x; d ''; nodir 1; d/notes.txt 1) deleted files in d (diff above: < want, > got)"; }
echo ok
