#[cfg(test)]
mod harness_tests {
    use solution::topo_order;

    fn harness_check(n: usize, edges: &[(usize, usize)], want: &[usize]) {
        let got: Result<Vec<usize>, String> = topo_order(n, edges);
        assert!(got.as_deref() == Ok(want), "topo_order({}, {:?}) = {:?}, want Ok({:?})", n, edges, got, want);
    }

    /// The first difference between got and want, with a few entries of context, for large outputs.
    fn harness_mismatch(got: &[usize], want: &[usize]) -> String {
        let i = got.iter().zip(want).position(|(g, w)| g != w).unwrap_or(got.len().min(want.len()));
        let lo = i.saturating_sub(2);
        format!("got {} nodes, want {}; first difference at index {}: got {:?}, want {:?} (from index {})",
                got.len(), want.len(), i, &got[lo.min(got.len())..(i + 3).min(got.len())],
                &want[lo.min(want.len())..(i + 3).min(want.len())], lo)
    }

    #[test] fn small() {
        harness_check(0, &[], &[]);
        harness_check(3, &[], &[0, 1, 2]);
        harness_check(3, &[(2, 0)], &[1, 2, 0]);
        harness_check(4, &[(3, 1), (2, 1), (3, 0)], &[2, 3, 0, 1]);
        harness_check(5, &[(4, 0), (4, 0), (1, 0), (3, 2)], &[1, 3, 2, 4, 0]);
        harness_check(5, &[(4, 0), (1, 0), (1, 0), (3, 2)], &[1, 3, 2, 4, 0]);
        harness_check(6, &[(5, 2), (5, 0), (4, 0), (4, 1), (2, 3), (3, 1)], &[4, 5, 0, 2, 3, 1]);
    }

    #[test] fn errors() {
        for (n, edges) in [
            (3, vec![(0, 1), (1, 2), (2, 0)]),
            (2, vec![(0, 1), (1, 0)]),
            (3, vec![(1, 1)]),
            (3, vec![(0, 3)]),
            (3, vec![(5, 0)]),
            (0, vec![(0, 0)]),
            (5, vec![(0, 1), (2, 3), (3, 4), (4, 2)]),
        ] {
            let got: Result<Vec<usize>, String> = topo_order(n, &edges);
            assert!(got.is_err(), "topo_order({}, {:?}) = {:?}, want an Err", n, edges, got);
        }
    }

    /// Runs topo_order(n, edges) in a thread and waits at most 5 s for it, so a slow solution fails with a message
    /// that names the bound instead of running into the sandbox's time limit. what describes the edges.
    fn harness_timed(n: usize, edges: Vec<(usize, usize)>, what: &str) -> Vec<usize> {
        let (tx, rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let _ = tx.send(topo_order(n, &edges));
        });
        match rx.recv_timeout(std::time::Duration::from_secs(5)) {
            Ok(Ok(order)) => order,
            Ok(Err(e)) => panic!("topo_order({}, {}) = Err({:?}), want Ok (the graph is acyclic)", n, what, e),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => panic!(
                "too slow: topo_order({}, {}) didn't return within 5 s; it must run in O((n + m) log n)", n, what),
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => panic!("topo_order({}, {}) panicked", n, what),
        }
    }

    #[test] fn large() {
        let n = 1_000_000;
        // A reverse chain (i before i - 1) with extra edges: the order is n-1, ..., 0.
        let mut edges: Vec<(usize, usize)> = (1..n).map(|i| (i, i - 1)).collect();
        edges.extend((2..n).step_by(3).map(|i| (i, i - 2)));
        let what = "edges (i, i-1) for 1 <= i < n and (i, i-2) for i = 2, 5, 8, ...";
        let got = harness_timed(n, edges, what);
        let want: Vec<usize> = (0..n).rev().collect();
        assert!(got == want, "topo_order({}, {}): {}", n, what, harness_mismatch(&got, &want));

        // Independent pairs: (2k+1) before (2k). The smallest available node always goes first.
        let edges: Vec<(usize, usize)> = (0..n / 2).map(|k| (2 * k + 1, 2 * k)).collect();
        let what = "edges (2k+1, 2k) for 0 <= k < n/2";
        let got = harness_timed(n, edges, what);
        let mut want = vec![1, 0];
        for k in 1..n / 2 {
            want.push(2 * k + 1);
            want.push(2 * k);
        }
        assert!(got == want, "topo_order({}, {}): {}", n, what, harness_mismatch(&got, &want));

        // Even nodes 2k before the top quarter's nodes n-1-k: while most nodes are ready, each node taken unlocks one
        // that is larger than all of them.
        let edges: Vec<(usize, usize)> = (0..n / 4).map(|k| (2 * k, n - 1 - k)).collect();
        let what = "edges (2k, n-1-k) for 0 <= k < n/4";
        let got = harness_timed(n, edges, what);
        let want: Vec<usize> = (0..n).collect();
        assert!(got == want, "topo_order({}, {}): {}", n, what, harness_mismatch(&got, &want));
    }
}
