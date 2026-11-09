set -u
export LC_ALL=C
SOL="$PWD/solution.sh"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
T=$(mktemp -d) || exit 1
trap 'rm -rf "$T"' EXIT
# Interpreters other than Bash and awk are replaced by stubs that come first on PATH: running one fails the
# solution (even if it hides the error), while a comment that merely mentions one doesn't.
mkdir "$T/stubs" || exit 1
cat > "$T/stub" <<STUB
#!/bin/bash
printf '%s\n' "\${0##*/}" >> '$T/ran'
printf '%s: not available; use only Bash and the standard command-line tools\n' "\${0##*/}" >&2
exit 127
STUB
chmod +x "$T/stub" || exit 1
IFS=: read -ra dirs <<< "$PATH"
for d in "${dirs[@]}"; do
    for p in "$d"/{python,perl,ruby,php,lua,tclsh,wish,guile}* "$d"/{node,nodejs,deno,bun,pwsh,Rscript,julia}; do
        [ -e "$p" ] && ln -sf "$T/stub" "$T/stubs/${p##*/}"
    done
done
export PATH="$T/stubs:$PATH"
# ran_interpreter CASE: fail if the solution ran one of the stubbed interpreters.
ran_interpreter() {
    [ ! -s "$T/ran" ] ||
        fail "$1 -- solution.sh ran $(sort -u "$T/ran" | paste -sd ' ' -): only Bash and the standard command-line tools are allowed"
}
W="$T/work"
mkdir "$W" && cd "$W" || exit 1
# put PATH CONTENT: create a file (and its directories); CONTENT is a printf %b string.
put() { mkdir -p -- "$(dirname -- "$1")" && printf '%b' "$2" > "$1"; }
# The entries under the current directory, one per line: "PATH (modified TIME): CONTENTS" for files (contents
# shell-quoted), "PATH/" for directories.
describe() {
    find . -mindepth 1 | sort | while IFS= read -r f; do
        if [ -d "$f" ]; then
            printf '\n  %s/' "$f"
        else
            c=$(cat -- "$f"; printf x)
            printf '\n  %s (modified %s): %q' "$f" "$(date -r "$f" '+%F %H:%M')" "${c%x}"
        fi
    done
}

put logs/app.log 'user=bob password=hunter2 ok\npassword=a1 password=b2\nno secrets here\n'
put 'logs/web server.log' "$(for i in 1 2 3 4 5 6 7 8; do printf 'GET /index.html 200\\n'; done)password=letmein (retry)\\n"
put logs/sub/deep.log 'password=zzz\n'
put logs/app.log.1 'old\n'
put 'logs/old runs/app.log.12' 'old\n'
put logs/.app.log.2 'old\n'
put logs/.archive/app.log.6 'old\n'
put logs/app.log.3 'recent\n'
put logs/app.log.4 '7.5 days old\n'
put logs/app.log.5 '6.5 days old\n'
put logs/app.log.bak 'old\n'
put logs/app.log.1.gz 'old\n'
put notes.txt 'password=keep\n'
old=$(date -d '30 days ago' +%F)
recent=$(date -d '1 day ago' +%F)
for f in logs/app.log.1 'logs/old runs/app.log.12' logs/.app.log.2 logs/.archive/app.log.6 logs/app.log.bak logs/app.log.1.gz; do touch -d "$old" "$f"; done
touch -d "$recent" logs/app.log.3
touch -d '180 hours ago' logs/app.log.4
touch -d '156 hours ago' logs/app.log.5
case1="bash solution.sh at $(date '+%F %H:%M') in a directory with these entries:$(describe)
"
cp -a "$W" "$T/want" || exit 1
(
    cd "$T/want" || exit 1
    put logs/app.log 'user=bob password=*** ok\npassword=*** password=***\nno secrets here\n'
    put 'logs/web server.log' "$(for i in 1 2 3 4 5 6 7 8; do printf 'GET /index.html 200\\n'; done)password=*** (retry)\\n"
    rm -f logs/app.log.1 logs/app.log.4 'logs/old runs/app.log.12' logs/.app.log.2 logs/.archive/app.log.6
) || exit 1
want_out="$(wc -c < "$T/want/logs/web server.log") logs/web server.log"
bash "$SOL" > "$T/out" 2> "$T/err" < /dev/null
rc=$?
ran_interpreter "$case1"
[ "$rc" -eq 0 ] || fail "$case1 -- exit status $rc, want 0 (stderr: $(head -c 2000 "$T/err"))"
[ ! -s "$T/err" ] || fail "$case1 -- printed to stderr: $(head -c 2000 "$T/err")"
printf '%s\n' "$want_out" > "$T/want_out"
cmp -s "$T/want_out" "$T/out" || fail "$case1 -- printed $(printf '%q' "$(head -c 2000 "$T/out")"), want $(printf '%q' "$want_out")"
cd "$T" || exit 1
diff -r want work >&2 || fail "$case1 -- wrong files afterwards (diff above: < want, > got; 'Only in' lines name files that should or shouldn't exist)"
echo 'harness: all checks passed'
