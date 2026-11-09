find etc -type f -name '*.conf' -exec sed -i -E 's/^([[:blank:]]*port[[:blank:]]*=[[:blank:]]*).*$/\19090/' {} +
