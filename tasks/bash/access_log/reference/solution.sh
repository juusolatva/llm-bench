#!/bin/bash
# Count HTTP status codes and sum response sizes in an access log.
awk 'NF {
    count[$(NF - 1)]++
    if ($NF != "-") bytes += $NF
} END {
    for (status in count) print status, count[status] | "sort -n"
    close("sort -n")
    print "total_bytes", bytes + 0
}' "$1"
