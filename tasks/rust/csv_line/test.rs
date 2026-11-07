#[cfg(test)]
mod harness_tests {
    use super::*;
    fn ok(v: &[&str]) -> Result<Vec<String>, String> { Ok(v.iter().map(|s| s.to_string()).collect()) }

    #[test] fn plain() {
        assert_eq!(parse_csv_line("a,b,c"), ok(&["a", "b", "c"]));
        assert_eq!(parse_csv_line(""), ok(&[""]));
        assert_eq!(parse_csv_line("a,,c"), ok(&["a", "", "c"]));
        assert_eq!(parse_csv_line(","), ok(&["", ""]));
        assert_eq!(parse_csv_line(" a , b "), ok(&[" a ", " b "]));
    }
    #[test] fn quoted() {
        assert_eq!(parse_csv_line("\"x,y\",z"), ok(&["x,y", "z"]));
        assert_eq!(parse_csv_line("\"he said \"\"hi\"\"\""), ok(&["he said \"hi\""]));
        assert_eq!(parse_csv_line("\"\""), ok(&[""]));
        assert_eq!(parse_csv_line("a,\"\""), ok(&["a", ""]));
        assert_eq!(parse_csv_line("é,\"ü,ß\""), ok(&["é", "ü,ß"]));
    }
    #[test] fn errors() {
        assert!(parse_csv_line("\"abc").is_err());
        assert!(parse_csv_line("\"a\"b").is_err());
        assert!(parse_csv_line("a\"b").is_err());
        assert!(parse_csv_line("x,\"a\"\"").is_err());
    }
}
