use std::cmp::Reverse;
use std::collections::BinaryHeap;

/// The lexicographically smallest topological order of nodes 0..n (Kahn's algorithm with a min-heap),
/// or an error for out-of-range nodes, self-loops and cycles.
pub fn topo_order(n: usize, edges: &[(usize, usize)]) -> Result<Vec<usize>, String> {
    let mut successors = vec![Vec::new(); n];
    let mut indegree = vec![0usize; n];
    for &(a, b) in edges {
        if a >= n || b >= n {
            return Err(format!("edge ({}, {}) refers to a node >= {}", a, b, n));
        }
        if a == b {
            return Err(format!("self-loop on node {}", a));
        }
        successors[a].push(b);
        indegree[b] += 1;
    }
    let mut ready: BinaryHeap<Reverse<usize>> =
        (0..n).filter(|&v| indegree[v] == 0).map(Reverse).collect();
    let mut order = Vec::with_capacity(n);
    while let Some(Reverse(v)) = ready.pop() {
        order.push(v);
        for &w in &successors[v] {
            indegree[w] -= 1;
            if indegree[w] == 0 {
                ready.push(Reverse(w));
            }
        }
    }
    if order.len() != n {
        return Err("the edges form a cycle".to_string());
    }
    Ok(order)
}
