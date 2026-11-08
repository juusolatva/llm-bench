#[cfg(test)]
mod harness_tests {
    use super::*;
    fn harness_ok(line: &str, want: &[&str]) {
        let want: Vec<String> = want.iter().map(|s| s.to_string()).collect();
        let got = parse_csv_line(line);
        assert!(got.as_ref() == Ok(&want), "parse_csv_line({:?}): got {:?}, want Ok({:?})", line, got, want);
    }
    fn harness_err(line: &str) {
        let got = parse_csv_line(line);
        assert!(got.is_err(), "parse_csv_line({:?}): got {:?}, want an Err", line, got);
    }

    #[test] fn plain() {
        harness_ok("a,b,c", &["a", "b", "c"]);
        harness_ok("", &[""]);
        harness_ok("a,,c", &["a", "", "c"]);
        harness_ok(",", &["", ""]);
        harness_ok(" a , b ", &[" a ", " b "]);
    }
    #[test] fn quoted() {
        harness_ok("\"x,y\",z", &["x,y", "z"]);
        harness_ok("a,\"b\",c", &["a", "b", "c"]);
        harness_ok("\"a\",", &["a", ""]);
        harness_ok("\"he said \"\"hi\"\"\"", &["he said \"hi\""]);
        harness_ok("\"\"", &[""]);
        harness_ok("a,\"\"", &["a", ""]);
        harness_ok("é,\"ü,ß\"", &["é", "ü,ß"]);
    }
    #[test] fn errors() {
        harness_err("\"abc");
        harness_err("\"a\"b");
        harness_err("a\"b");
        harness_err("x,\"a\"\"");
    }
}
