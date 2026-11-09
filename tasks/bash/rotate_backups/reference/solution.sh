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

# Compare N with the file count as decimal strings first: N may be too large for Bash's 64-bit arithmetic.
keep=${keep#"${keep%%[!0]*}"}   # drop leading zeros ("" for 0), so "08" isn't read as octal
count=${#files[@]}
(( ${#keep} > ${#count} )) && exit 0
for ((i = ${keep:-0}; i < count; i++)); do
    rm -f -- "$dir/${files[i]}"
    printf '%s\n' "$dir/${files[i]}"
done
