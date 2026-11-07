Write a Bash script used as `rotate.sh DIR N`. It deletes all but the N most recently modified files whose names end in `.bak` directly inside DIR (not in subdirectories). Other files are never touched. File names may contain spaces.

- Print the path of each deleted file as DIR/NAME (DIR exactly as given) to stdout, one per line, in any order.
- On wrong usage (not exactly 2 arguments, N not a non-negative integer, or DIR not a directory) print an error to stderr and exit 1.
