This script breaks on file and directory names that contain spaces, and prints an error when no file matches. Fix it: when nothing matches it should do nothing and exit 0; otherwise it should keep working as before. Reply with the complete fixed script.

```bash
#!/bin/bash
# Usage: rename_ext.sh DIR OLD NEW
# Renames every file in DIR whose name ends in .OLD so that it ends in .NEW instead.
dir=$1
for f in $(ls $dir/*.$2); do
    mv $f ${f%.$2}.$3
done
```
