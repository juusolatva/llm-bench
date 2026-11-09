This log maintenance script was written on macOS, and its commands fail or do the wrong thing on Linux. Fix it so that it works with the GNU tools, keeping what each step does as the comments describe. It is run from the project directory, it prints only the line from step 3 (and nothing on stderr), and it exits with status 0.

```bash
#!/bin/bash
# Nightly log maintenance, run from the project directory.
# 1. Mask passwords in the current logs, logs/*.log: every "password=" followed by non-space characters
#    becomes "password=***".
sed -i '' -E 's/password=[^ ]+/password=***/g' logs/*.log
# 2. Delete the rotated logs (regular files at any depth under logs whose names end in .log followed by
#    a dot and a number, like app.log.3) that were last modified more than 7 days ago.
find -E logs -type f -regex '.*\.log\.[0-9]+' -mtime +7 -delete
# 3. Print the size in bytes and the path (as logs/NAME) of the largest current log, after step 1.
stat -f '%z %N' logs/*.log | sort -rn | head -n 1
```

Reply with the complete fixed script as `solution.sh`. It is run as `bash solution.sh`, with no arguments, on Linux with GNU coreutils, findutils, diffutils, grep, sed and gawk, and with `LC_ALL=C`. Use only Bash and these command-line tools (no Python, Perl, Ruby, Node.js or other interpreters). File names may contain spaces, quotes and leading dashes, but no newlines.
