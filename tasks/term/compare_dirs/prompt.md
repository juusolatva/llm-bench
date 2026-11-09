The current directory contains two directory trees, `a` and `b` (for example an old and a new copy of a build output). Write the shell commands that compare the regular files in them and print one line per difference:

- `only in a: PATH` for a file under `a` with no file at the same relative path under `b`,
- `only in b: PATH` for a file under `b` with no file at the same relative path under `a`,
- `differ: PATH` for a file that exists in both trees with different contents.

PATH is the file's path relative to `a` and `b` (for example `src/main.c`). Files at any depth count, including hidden files and files in hidden directories; when a directory exists in only one tree, every file inside it is listed. Files with identical contents are not printed, even if their modification times differ. Directories themselves are never printed, so an empty directory produces no line. No path is a file in one tree and a directory in the other, and there are no symbolic links.

Sort the lines by PATH in byte order. Exit with status 0.

Write it as `solution.sh`. It is run as `bash solution.sh`, with no arguments, from the directory to work on, on Linux with GNU coreutils, findutils, diffutils, grep, sed and gawk, and with `LC_ALL=C`. Use only Bash and these command-line tools (no Python, Perl, Ruby, Node.js or other interpreters). File names may contain spaces, quotes and leading dashes, but no newlines.
