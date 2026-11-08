#[cfg(test)]
mod harness_tests {
    use super::*;
    /// Inventory wrapper that records the calls made so far, so failures can show them.
    struct HarnessInv { inv: Inventory, log: Vec<String> }
    impl HarnessInv {
        fn new() -> Self { HarnessInv { inv: Inventory::new(), log: vec!["Inventory::new()".to_string()] } }
        fn add(&mut self, name: &str, qty: u32) {
            self.inv.add(name, qty);
            self.log.push(format!("add({:?}, {})", name, qty));
        }
        fn remove(&mut self, name: &str, qty: u32, want_ok: bool) {
            let got = self.inv.remove(name, qty);
            assert!(got.is_ok() == want_ok, "after {}: remove({:?}, {}) returned {:?}, want {}",
                    self.log.join(", "), name, qty, got, if want_ok { "Ok(())" } else { "an Err" });
            self.log.push(format!("remove({:?}, {})", name, qty));
        }
        fn get(&self, name: &str, want: u32) {
            let got = self.inv.get(name);
            assert!(got == want, "after {}: get({:?}) returned {}, want {}", self.log.join(", "), name, got, want);
        }
        fn len(&self, want: usize) {
            let got = self.inv.len();
            assert!(got == want, "after {}: len() returned {}, want {}", self.log.join(", "), got, want);
        }
    }

    #[test] fn add_and_get() {
        let mut inv = HarnessInv::new();
        inv.get("apple", 0);
        inv.add("apple", 3);
        inv.add("pear", 1);
        inv.add("apple", 2);
        inv.get("apple", 5);
        inv.get("pear", 1);
        inv.len(2);
    }
    #[test] fn remove() {
        let mut inv = HarnessInv::new();
        inv.add("apple", 5);
        inv.remove("apple", 2, true);
        inv.get("apple", 3);
        inv.remove("apple", 4, false);
        inv.get("apple", 3);
        inv.remove("kiwi", 1, false);
        inv.len(1);
        inv.remove("apple", 3, true);
        inv.get("apple", 0);
        inv.len(0);
    }
}
