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
# The files under the current directory, one per line as "PATH: CONTENTS" (contents shell-quoted).
describe() {
    find . -type f | sort | while IFS= read -r f; do
        c=$(cat -- "$f"; printf x)
        printf '\n  %s: %q' "$f" "${c%x}"
    done
}

put etc/app.conf '# port = 1\nport = 8080\nport=80\n\tport\t=\t 443\nexport_port = 1\nport_max = 2\nportal = 3\nsupport = 4\nports = 5\n PORT = 6\nhost = port = 7\n'
put 'etc/my app/site.conf' 'name = site\n  port = ${PORT:-8080} # default'
put etc/.hidden/x.conf 'port = 2\n'
put etc/-d.conf 'port = 3\n'
put "etc/it's.conf" 'port = 4\n'
put etc/a/b/c/deep.conf 'x = 1\nport = 5\n'
put etc/app.conf.bak 'port = 8080\n'
put etc/notes.txt 'port = 8080\n'
put etc/old.conf/readme.txt 'port = 8080\n'
put etc/old.conf/real.conf 'port = 8080\n'
put other.conf 'port = 8080\n'
before=$(describe)
cp -a "$W" "$T/want" || exit 1
(
    cd "$T/want" || exit 1
    put etc/app.conf '# port = 1\nport = 9090\nport=9090\n\tport\t=\t 9090\nexport_port = 1\nport_max = 2\nportal = 3\nsupport = 4\nports = 5\n PORT = 6\nhost = port = 7\n'
    put 'etc/my app/site.conf' 'name = site\n  port = 9090'
    put etc/.hidden/x.conf 'port = 9090\n'
    put etc/-d.conf 'port = 9090\n'
    put "etc/it's.conf" 'port = 9090\n'
    put etc/a/b/c/deep.conf 'x = 1\nport = 9090\n'
    put etc/old.conf/real.conf 'port = 9090\n'
) || exit 1
case1="bash solution.sh in a directory with these files (PATH: CONTENTS):$before
"
bash "$SOL" > "$T/out" 2> "$T/err" < /dev/null
rc=$?
[ "$rc" -eq 0 ] || fail "$case1 -- exit status $rc, want 0 (stderr: $(head -c 2000 "$T/err"))"
[ ! -s "$T/out" ] || fail "$case1 -- printed $(printf '%q' "$(head -c 2000 "$T/out")"), want no output"
cd "$T" || exit 1
diff -r want work >&2 || fail "$case1 -- wrong files afterwards (diff above: < want, > got; 'Only in' lines name files that should or shouldn't exist)"
echo 'harness: all checks passed'
