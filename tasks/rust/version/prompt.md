Write Rust code for a library file (no main, no tests) defining a semantic version type:

- `pub struct Version { pub major: u64, pub minor: u64, pub patch: u64 }` deriving Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord and Hash (versions compare by major, then minor, then patch).
- Implement `std::str::FromStr` with `type Err = String`. Accept exactly three dot-separated non-negative integers, optionally prefixed by a single 'v' (for example "1.2.3" or "v10.0.1"). Anything else is an error.
- Implement `std::fmt::Display`, printing "MAJOR.MINOR.PATCH" without a 'v'.
