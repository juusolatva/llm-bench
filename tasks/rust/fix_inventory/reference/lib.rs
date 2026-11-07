/// Item quantities by name.
pub struct Inventory {
    items: Vec<(String, u32)>,
}

impl Inventory {
    /// An empty inventory.
    pub fn new() -> Self {
        Inventory { items: Vec::new() }
    }

    /// Adds qty units of name.
    pub fn add(&mut self, name: &str, qty: u32) {
        for item in self.items.iter_mut() {
            if item.0 == name {
                item.1 += qty;
                return;
            }
        }
        self.items.push((name.to_string(), qty));
    }

    /// Removes qty units of name. Errors if the item is unknown or there are not enough units
    /// (the inventory is then unchanged). Items whose quantity drops to 0 are removed.
    pub fn remove(&mut self, name: &str, qty: u32) -> Result<(), String> {
        let item = self.items.iter_mut().find(|i| i.0 == name).ok_or("unknown item")?;
        if item.1 < qty {
            return Err(format!("only {} left", item.1));
        }
        item.1 -= qty;
        if item.1 == 0 {
            self.items.retain(|i| i.0 != name);
        }
        Ok(())
    }

    /// Quantity of name (0 if unknown).
    pub fn get(&self, name: &str) -> u32 {
        self.items.iter().find(|i| i.0 == name).map_or(0, |i| i.1)
    }

    /// Number of distinct items.
    pub fn len(&self) -> usize {
        self.items.len()
    }
}
