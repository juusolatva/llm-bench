# The regular files under directory $1, as paths relative to it, sorted.
list() { (cd "$1" && find . -type f -printf '%P\n') | sort; }
{
    comm -23 <(list a) <(list b) | sed 's/^/only in a: /'
    comm -13 <(list a) <(list b) | sed 's/^/only in b: /'
    comm -12 <(list a) <(list b) | while IFS= read -r path; do
        cmp -s -- "a/$path" "b/$path" || printf 'differ: %s\n' "$path"
    done
} | sort -t: -k2
