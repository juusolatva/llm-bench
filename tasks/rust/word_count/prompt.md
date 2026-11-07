Write Rust code for a library file (no main, no tests) with:

```rust
pub fn word_count(text: &str) -> std::collections::HashMap<String, usize>
```

Words are maximal runs of alphanumeric characters (char::is_alphanumeric). Count them case-insensitively; the map keys are the lowercase words.
