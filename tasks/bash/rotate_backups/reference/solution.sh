#!/bin/bash
# Delete all but the N most recently modified *.bak files directly in DIR, printing each deleted path.
# Print the usage and exit 1.
usage() { echo "usage: rotate.sh DIR N" >&2; exit 1; }
[ "$#" -eq 2 ] || usage
dir=$1 keep=$2
[[ $keep =~ ^[0-9]+$ ]] || usage
[ -d "$dir" ] || usage

files=()
while IFS= read -r -d '' line; do
    files+=("${line#* }")
done < <(find "$dir" -mindepth 1 -maxdepth 1 -type f -name '*.bak' -printf '%T@ %f\0' | sort -z -rn)

for ((i = 10#$keep; i < ${#files[@]}; i++)); do
    rm -f -- "$dir/${files[i]}"
    printf '%s\n' "$dir/${files[i]}"
done
