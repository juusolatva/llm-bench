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
# The files under the current directory, one per line as "PATH: CONTENTS" (contents shell-quoted).
describe() {
    find . -type f | sort | while IFS= read -r f; do
        c=$(cat -- "$f"; printf x)
        printf '\n  %s: %q' "$f" "${c%x}"
    done
}
# run CASE WANT...: run the solution in $W and compare its output with the WANT lines.
run() {
    local case=$1; shift
    bash "$SOL" > "$T/out" 2> "$T/err" < /dev/null
    local rc=$?
    ran_interpreter "$case"
    [ "$rc" -eq 0 ] || fail "$case -- exit status $rc, want 0 (stderr: $(head -c 2000 "$T/err"))"
    if [ "$#" -gt 0 ]; then printf '%s\n' "$@"; fi > "$T/want"
    cmp -s "$T/want" "$T/out" || { diff "$T/want" "$T/out" >&2; fail "$case -- wrong output (diff above: < want, > got)"; }
}

put app.py 'import yaml\ncfg = yaml.safe_load(open("config.yaml"))\n'
put README.md 'Settings live in config_yaml (see docs).\n'
put 'docs/setup guide.md' 'Copy config.yaml.example to config.yaml.\n'
put .env 'CONFIG_FILE=config.yaml\n'
put .github/workflows/ci.yml 'run: lint config.yaml\n'
put .git/config '[core]\n# config.yaml\n'
put sub/.git/HEAD 'config.yaml\n'
put node_modules/x.js 'require("config.yaml")\n'
put web/node_modules/pkg/index.js 'load("config.yaml")\n'
put node_modules.txt 'node_modules may mention config.yaml\n'
put src/-v.txt 'flag file: config.yaml\n'
put "src/it's here.txt" 'quoted name, config.yaml inside\n'
put src/upper.txt 'CONFIG.YAML is not the same\n'
put src/tail.txt 'last line names config.yaml'
put config.yaml 'port: 8080\n'
run "bash solution.sh in a directory with these files (PATH: CONTENTS):$(describe)
" ./.env ./.github/workflows/ci.yml ./app.py './docs/setup guide.md' ./node_modules.txt ./src/-v.txt "./src/it's here.txt" ./src/tail.txt

rm -rf "$W" && mkdir "$W" && cd "$W" || exit 1
put notes.txt 'config_yaml\n'
put node_modules/a.js 'config.yaml\n'
run "bash solution.sh in a directory where no file matches (PATH: CONTENTS):$(describe)
"
echo 'harness: all checks passed'
