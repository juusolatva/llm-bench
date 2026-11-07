#[cfg(test)]
mod harness_tests {
    use super::*;
    #[test] fn add_and_get() {
        let mut inv = Inventory::new();
        assert_eq!(inv.get("apple"), 0);
        inv.add("apple", 3);
        inv.add("pear", 1);
        inv.add("apple", 2);
        assert_eq!(inv.get("apple"), 5);
        assert_eq!(inv.get("pear"), 1);
        assert_eq!(inv.len(), 2);
    }
    #[test] fn remove() {
        let mut inv = Inventory::new();
        inv.add("apple", 5);
        assert!(inv.remove("apple", 2).is_ok());
        assert_eq!(inv.get("apple"), 3);
        assert!(inv.remove("apple", 4).is_err());
        assert_eq!(inv.get("apple"), 3);
        assert!(inv.remove("kiwi", 1).is_err());
        assert!(inv.remove("apple", 3).is_ok());
        assert_eq!(inv.get("apple"), 0);
        assert_eq!(inv.len(), 0);
    }
}
