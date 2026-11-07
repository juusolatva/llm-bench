#!/bin/bash
# Usage: rename_ext.sh DIR OLD NEW
# Renames every file in DIR whose name ends in .OLD so that it ends in .NEW instead.
shopt -s nullglob
dir=$1
for f in "$dir"/*."$2"; do
    mv -- "$f" "${f%."$2"}.$3"
done
