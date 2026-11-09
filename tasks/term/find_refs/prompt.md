Write the shell commands that print the path of every regular file under the current directory (at any depth, including hidden files and hidden directories) whose contents contain the text `config.yaml`, matched literally and case-sensitively. Skip everything inside directories named `.git` or `node_modules`, at any depth.

Print each path once, as `./PATH` (for example `./src/app.py`), one per line, sorted in byte order. Print nothing if no file matches. Always exit with status 0.

Write it as `solution.sh`. It is run as `bash solution.sh`, with no arguments, from the directory to work on, on Linux with GNU coreutils, findutils, diffutils, grep, sed and gawk, and with `LC_ALL=C`. Use only Bash and these command-line tools (no Python, Perl, Ruby, Node.js or other interpreters). File names may contain spaces, quotes and leading dashes, but no newlines.
