set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
bad=$(grep -Ewo 'python[0-9.]*|perl|ruby|node|nodejs|php|lua|tclsh' "$SOL" | head -n 1)
[ -z "$bad" ] || fail "solution.sh uses $bad: only Bash and the standard command-line tools are allowed"
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
W="$T/work"
mkdir "$W" && cd "$W" || exit 1
# put PATH CONTENT: create a file (and its directories); CONTENT is a printf %b string.
put() { mkdir -p -- "$(dirname -- "$1")" && printf '%b' "$2" > "$1"; }
# The entries under the current directory, one per line: "PATH (modified DATE): CONTENTS" for files (contents
# shell-quoted), "PATH/" for directories.
describe() {
    find . -mindepth 1 | sort | while IFS= read -r f; do
        if [ -d "$f" ]; then
            printf '\n  %s/' "$f"
        else
            c=$(cat -- "$f"; printf x)
            printf '\n  %s (modified %s): %q' "$f" "$(date -r "$f" +%F)" "${c%x}"
        fi
    done
}

put logs/app.log 'user=bob password=hunter2 ok\npassword=a1 password=b2\nno secrets here\n'
put 'logs/web server.log' "$(for i in 1 2 3 4 5 6 7 8; do printf 'GET /index.html 200\\n'; done)password=letmein (retry)\\n"
put logs/sub/deep.log 'password=zzz\n'
put logs/app.log.1 'old\n'
put 'logs/old runs/app.log.12' 'old\n'
put logs/app.log.3 'recent\n'
put logs/app.log.bak 'old\n'
put logs/app.log.1.gz 'old\n'
put notes.txt 'password=keep\n'
old=$(date -d '30 days ago' +%F)
recent=$(date -d '1 day ago' +%F)
for f in logs/app.log.1 'logs/old runs/app.log.12' logs/app.log.bak logs/app.log.1.gz; do touch -d "$old" "$f"; done
touch -d "$recent" logs/app.log.3
case1="bash solution.sh in a directory with these entries:$(describe)
"
cp -a "$W" "$T/want" || exit 1
(
    cd "$T/want" || exit 1
    put logs/app.log 'user=bob password=*** ok\npassword=*** password=***\nno secrets here\n'
    put 'logs/web server.log' "$(for i in 1 2 3 4 5 6 7 8; do printf 'GET /index.html 200\\n'; done)password=*** (retry)\\n"
    rm -f logs/app.log.1 'logs/old runs/app.log.12'
) || exit 1
want_out="$(wc -c < "$T/want/logs/web server.log") logs/web server.log"
bash "$SOL" > "$T/out" 2> "$T/err" < /dev/null
rc=$?
[ "$rc" -eq 0 ] || fail "$case1 -- exit status $rc, want 0 (stderr: $(head -c 2000 "$T/err"))"
[ ! -s "$T/err" ] || fail "$case1 -- printed to stderr: $(head -c 2000 "$T/err")"
printf '%s\n' "$want_out" > "$T/want_out"
cmp -s "$T/want_out" "$T/out" || fail "$case1 -- printed $(printf '%q' "$(head -c 2000 "$T/out")"), want $(printf '%q' "$want_out")"
cd "$T" || exit 1
diff -r want work >&2 || fail "$case1 -- wrong files afterwards (diff above: < want, > got; 'Only in' lines name files that should or shouldn't exist)"
echo 'harness: all checks passed'
