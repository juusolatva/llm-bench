Write Rust code for a library file (no main, no tests) with:

```rust
pub fn topo_order(n: usize, edges: &[(usize, usize)]) -> Result<Vec<usize>, String>
```

The nodes are 0, 1, ..., n-1. An edge (a, b) means that a must come before b.
- Return the lexicographically smallest ordering of all n nodes that respects every edge: whenever several nodes could come next, the smallest one comes first.
- The same edge may appear several times.
- Return an Err if an edge refers to a node >= n, if an edge goes from a node to itself, or if the edges form a cycle.
- It must handle 200000 nodes and edges in well under a second.
