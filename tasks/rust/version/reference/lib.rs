use std::fmt;
use std::str::FromStr;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Version {
    pub major: u64,
    pub minor: u64,
    pub patch: u64,
}

impl FromStr for Version {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let body = s.strip_prefix('v').unwrap_or(s);
        let parts: Vec<&str> = body.split('.').collect();
        if parts.len() != 3 {
            return Err(format!("expected MAJOR.MINOR.PATCH, got {:?}", s));
        }
        let mut nums = [0u64; 3];
        for (num, part) in nums.iter_mut().zip(&parts) {
            if part.is_empty() || !part.bytes().all(|b| b.is_ascii_digit()) {
                return Err(format!("invalid number {:?} in {:?}", part, s));
            }
            *num = part.parse().map_err(|e| format!("{:?}: {}", part, e))?;
        }
        Ok(Version { major: nums[0], minor: nums[1], patch: nums[2] })
    }
}

impl fmt::Display for Version {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}.{}.{}", self.major, self.minor, self.patch)
    }
}
