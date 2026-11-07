set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

setup() {
    rm -rf d; mkdir -p d/sub
    touch -d '2024-01-01' 'd/db 1.bak'
    touch -d '2024-01-02' 'd/db 2.bak'
    touch -d '2024-01-03' 'd/db 3.bak'
    touch -d '2024-01-04' 'd/db 4.bak'
    touch -d '2023-01-01' 'd/notes.txt'
    touch -d '2020-01-01' 'd/sub/old.bak'
}
listing() { (cd d && find . -type f | sort); }

setup
bash "$SOL" d 2 > out 2> err < /dev/null || fail "exit status $? ($(cat err))"
printf '%s\n' './db 3.bak' './db 4.bak' './notes.txt' './sub/old.bak' > want
listing > got
cmp -s got want || { diff want got >&2; fail "N=2: remaining files wrong (want vs got above)"; }
sort out > got
printf '%s\n' 'd/db 1.bak' 'd/db 2.bak' > want
cmp -s got want || { diff want got >&2; fail "N=2: printed paths wrong (want vs got above)"; }

setup
bash "$SOL" d 0 > out 2>/dev/null < /dev/null
printf '%s\n' './notes.txt' './sub/old.bak' > want
listing > got
cmp -s got want || fail "N=0 must delete every .bak in DIR"

setup
bash "$SOL" d 10 > out 2>/dev/null < /dev/null
[ ! -s out ] && [ "$(listing | wc -l)" -eq 6 ] || fail "N larger than the count must delete nothing"

setup
for args in "d" "d 1 x" "d -1" "d abc" "nodir 1"; do
    # shellcheck disable=SC2086
    bash "$SOL" $args > out 2> err < /dev/null
    rc=$?
    [ "$rc" -eq 1 ] || fail "args [$args]: exit $rc, want 1"
    [ -s err ] || fail "args [$args]: no error message"
done
[ "$(listing | wc -l)" -eq 6 ] || fail "usage errors must not delete anything"
echo ok
