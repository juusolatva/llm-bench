#!/bin/bash
tr -cs 'A-Za-z' '\n' < "$1" | tr 'A-Z' 'a-z' | grep -v '^$' | sort | uniq -c \
    | sort -k1,1nr -k2,2 | head -n 3 | awk '{ print $1, $2 }'
