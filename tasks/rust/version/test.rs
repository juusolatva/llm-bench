#[cfg(test)]
mod harness_tests {
    use super::*;
    fn v(a: u64, b: u64, c: u64) -> Version { Version { major: a, minor: b, patch: c } }
    /// Compiles only if Version implements the traits the prompt lists (Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash).
    fn harness_has_traits<T: std::fmt::Debug + Clone + Copy + PartialEq + Eq + PartialOrd + Ord + std::hash::Hash>() {}

    #[test] fn parse_ok() {
        for (s, want) in [("1.2.3", v(1, 2, 3)), ("v10.0.1", v(10, 0, 1)), ("0.0.0", v(0, 0, 0))] {
            let got = s.parse::<Version>();
            assert!(got == Ok(want), "{:?}.parse::<Version>(): got {:?}, want Ok({:?})", s, got, want);
        }
    }
    #[test] fn parse_err() {
        for s in ["", "1.2", "1.2.3.4", "1..3", "a.b.c", "v", "vv1.2.3", "1.2.-3", " 1.2.3", "1.2.3 ", "1.2.x", "V1.2.3"] {
            let got = s.parse::<Version>();
            assert!(got.is_err(), "{:?}.parse::<Version>(): got {:?}, want an Err", s, got);
        }
    }
    #[test] fn display_and_order() {
        harness_has_traits::<Version>();
        let got = v(1, 2, 3).to_string();
        assert!(got == "1.2.3", "Version {{ major: 1, minor: 2, patch: 3 }}.to_string(): got {:?}, want \"1.2.3\"", got);
        let got = "v4.5.6".parse::<Version>().map(|x| x.to_string());
        assert!(got == Ok("4.5.6".to_string()), "\"v4.5.6\" parsed and printed with Display: got {:?}, want Ok(\"4.5.6\")", got);
        let input = ["1.10.0", "1.2.0", "0.9.9", "1.2.10", "1.2.9"];
        let mut list: Vec<Version> = input.iter()
            .map(|s| s.parse().unwrap_or_else(|e| panic!("{:?}.parse::<Version>(): got Err({:?}), want Ok", s, e)))
            .collect();
        list.sort();
        let out: Vec<String> = list.iter().map(|x| x.to_string()).collect();
        let want = ["0.9.9", "1.2.0", "1.2.9", "1.2.10", "1.10.0"];
        assert!(out == want, "sorting the versions {:?}: got {:?}, want {:?}", input, out, want);
    }
}
