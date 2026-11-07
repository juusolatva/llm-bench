#[cfg(test)]
mod harness_tests {
    use super::*;
    use std::collections::HashMap;
    fn m(v: &[(&str, usize)]) -> HashMap<String, usize> { v.iter().map(|(k, n)| (k.to_string(), *n)).collect() }

    #[test] fn basic() {
        assert_eq!(word_count("Hello, hello WORLD! world? 42 42 x"), m(&[("hello", 2), ("world", 2), ("42", 2), ("x", 1)]));
    }
    #[test] fn empty() {
        assert_eq!(word_count(""), m(&[]));
        assert_eq!(word_count(" ,.! "), m(&[]));
    }
    #[test] fn split_on_punctuation() {
        assert_eq!(word_count("don't stop-now"), m(&[("don", 1), ("t", 1), ("stop", 1), ("now", 1)]));
    }
    #[test] fn unicode() {
        assert_eq!(word_count("Straße STRASSE straße Ünïcode"), m(&[("straße", 2), ("strasse", 1), ("ünïcode", 1)]));
    }
}
