Write a Bash script (awk is fine) that reads the HTTP access log given as its only argument and prints:
- one line `STATUS COUNT` per HTTP status code, sorted by status code ascending,
- then a final line `total_bytes N`, where N is the sum of all response sizes (a size of `-` counts as 0).

Example log line:
`127.0.0.1 - - [10/Oct/2024:13:55:36 +0000] "GET /index.html HTTP/1.1" 200 2326`

On every line the status is the second-to-last field and the size is the last field. Ignore empty lines.
