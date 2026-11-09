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
# The entries under a and b, one per line: "PATH: CONTENTS" for files (contents shell-quoted), "PATH/" for
# directories.
describe() {
    find a b -mindepth 1 | sort | while IFS= read -r f; do
        if [ -d "$f" ]; then
            printf '\n  %s/' "$f"
        else
            c=$(cat -- "$f"; printf x)
            printf '\n  %s: %q' "$f" "${c%x}"
        fi
    done
}

put a/same.txt 'unchanged\n'
put b/same.txt 'unchanged\n'
touch -d '2024-01-01' b/same.txt
put a/changed.txt 'version 1\n'
put b/changed.txt 'version 2, longer\n'
put a/eol.txt 'x'
put b/eol.txt 'x\n'
put a/zero.txt ''
put b/zero.txt ''
put 'a/only a.txt' 'a\n'
put "b/it's new.txt" 'b\n'
put a/-flag.txt 'f\n'
put 'a/old dir/x.txt' 'x\n'
put 'a/old dir/sub/y.txt' 'y\n'
put b/.hidden/cfg 'k=v\n'
put a/.env 'MODE=dev\n'
put b/.env 'MODE=prod\n'
put a/src/main.c 'int main(void) { return 0; }\n'
put b/src/main.c 'int main(void) { return 0; }\n'
put a/src/util.c 'int f(void) { return 1; }\n'
put b/src/util.c 'int f(void) { return 2; }\n'
put a/src/lib.c 'lib\n'
put b/src/lib.h 'lib\n'
mkdir 'b/empty dir'
case1="bash solution.sh in a directory with these entries (PATH: CONTENTS; b/same.txt has an older modification time than a/same.txt):$(describe)
"
bash "$SOL" > "$T/out" 2> "$T/err" < /dev/null
rc=$?
ran_interpreter "$case1"
[ "$rc" -eq 0 ] || fail "$case1 -- exit status $rc, want 0 (stderr: $(head -c 2000 "$T/err"))"
printf '%s\n' 'only in a: -flag.txt' 'differ: .env' 'only in b: .hidden/cfg' 'differ: changed.txt' 'differ: eol.txt' \
    "only in b: it's new.txt" 'only in a: old dir/sub/y.txt' 'only in a: old dir/x.txt' 'only in a: only a.txt' \
    'only in a: src/lib.c' 'only in b: src/lib.h' 'differ: src/util.c' > "$T/want"
cmp -s "$T/want" "$T/out" || { diff "$T/want" "$T/out" >&2; fail "$case1 -- wrong output (diff above: < want, > got)"; }
echo 'harness: all checks passed'
