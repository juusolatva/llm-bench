#!/bin/bash
awk 'NF {
    count[$(NF - 1)]++
    if ($NF != "-") bytes += $NF
} END {
    for (status in count) print status, count[status] | "sort -n"
    close("sort -n")
    print "total_bytes", bytes + 0
}' "$1"
