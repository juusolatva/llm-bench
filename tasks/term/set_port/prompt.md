Write the shell commands that set the port to 9090 in the config files under the directory `etc` in the current directory. The config files are the regular files under `etc` (at any depth, including hidden directories) whose names end in `.conf`.

In each config file, a port line consists of optional leading spaces or tabs, the key `port`, optional spaces or tabs, `=`, optional spaces or tabs, and a value that runs to the end of the line. Replace the value on every port line with `9090` and keep the rest of the line as it is. Leave every other line and every other file unchanged: afterwards the files must be byte-for-byte identical to before apart from the replaced values (a last line without a trailing newline stays without one).

Print nothing and exit with status 0.

Write it as `solution.sh`. It is run as `bash solution.sh`, with no arguments, from the directory to work on, on Linux with GNU coreutils, findutils, diffutils, grep, sed and gawk, and with `LC_ALL=C`. Use only Bash and these command-line tools (no Python, Perl, Ruby, Node.js or other interpreters). File names may contain spaces, quotes and leading dashes, but no newlines.
