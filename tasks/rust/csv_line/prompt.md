Write Rust code for a library file (no main, no tests) with:

```rust
pub fn parse_csv_line(line: &str) -> Result<Vec<String>, String>
```

It splits one CSV line into fields:
- Fields are separated by commas. An empty line is a single empty field.
- A field that starts with a double quote is quoted: commas inside it are literal and `""` inside it stands for one `"`. The quoted field ends at a single `"`, which must be followed by a comma or the end of the line; anything else is an error. A quoted field without a closing quote is an error.
- Unquoted fields are taken literally (no trimming) and must not contain a double quote (error).
