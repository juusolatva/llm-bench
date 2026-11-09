#!/bin/bash
# Nightly log maintenance, run from the project directory.
# 1. Mask passwords in the current logs, logs/*.log: every "password=" followed by non-space characters
#    becomes "password=***".
sed -i -E 's/password=[^ ]+/password=***/g' logs/*.log
# 2. Delete the rotated logs (regular files at any depth under logs whose names end in .log followed by
#    a dot and a number, like app.log.3) that were last modified more than 7 days ago.
find logs -regextype posix-extended -type f -regex '.*\.log\.[0-9]+' -mtime +7 -delete
# 3. Print the size in bytes and the path (as logs/NAME) of the largest current log, after step 1.
stat -c '%s %n' logs/*.log | sort -rn | head -n 1
