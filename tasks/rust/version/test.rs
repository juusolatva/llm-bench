#[cfg(test)]
mod harness_tests {
    use super::*;
    fn v(a: u64, b: u64, c: u64) -> Version { Version { major: a, minor: b, patch: c } }

    #[test] fn parse_ok() {
        assert_eq!("1.2.3".parse::<Version>(), Ok(v(1, 2, 3)));
        assert_eq!("v10.0.1".parse::<Version>(), Ok(v(10, 0, 1)));
        assert_eq!("0.0.0".parse::<Version>(), Ok(v(0, 0, 0)));
    }
    #[test] fn parse_err() {
        for s in ["", "1.2", "1.2.3.4", "1..3", "a.b.c", "v", "vv1.2.3", "1.2.-3", " 1.2.3", "1.2.3 ", "1.2.x", "V1.2.3"] {
            assert!(s.parse::<Version>().is_err(), "{:?} should be an error", s);
        }
    }
    #[test] fn display_and_order() {
        assert_eq!(v(1, 2, 3).to_string(), "1.2.3");
        assert_eq!("v4.5.6".parse::<Version>().unwrap().to_string(), "4.5.6");
        let mut list: Vec<Version> = ["1.10.0", "1.2.0", "0.9.9", "1.2.10", "1.2.9"].iter().map(|s| s.parse().unwrap()).collect();
        list.sort();
        let out: Vec<String> = list.iter().map(|x| x.to_string()).collect();
        assert_eq!(out, ["0.9.9", "1.2.0", "1.2.9", "1.2.10", "1.10.0"]);
    }
}
