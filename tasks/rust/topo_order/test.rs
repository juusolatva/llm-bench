#[cfg(test)]
mod harness_tests {
    use solution::topo_order;

    fn harness_check(n: usize, edges: &[(usize, usize)], want: &[usize]) {
        let got = topo_order(n, edges);
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
            let got = topo_order(n, &edges);
            assert!(got.is_err(), "topo_order({}, {:?}) = {:?}, want an Err", n, edges, got);
        }
    }

    #[test] fn large() {
        let start = std::time::Instant::now();
        let n = 200_000;
        // A reverse chain (i before i - 1) with extra edges: the order is n-1, ..., 0.
        let mut edges: Vec<(usize, usize)> = (1..n).map(|i| (i, i - 1)).collect();
        edges.extend((2..n).step_by(3).map(|i| (i, i - 2)));
        let got = topo_order(n, &edges).expect("large acyclic graph must succeed");
        let want: Vec<usize> = (0..n).rev().collect();
        assert!(got == want, "topo_order(200000, edges (i, i-1) for 1 <= i < n and (i, i-2) for i = 2, 5, 8, ...): {}",
                harness_mismatch(&got, &want));

        // Independent pairs: (2k+1) before (2k). The smallest available node always goes first.
        let edges: Vec<(usize, usize)> = (0..n / 2).map(|k| (2 * k + 1, 2 * k)).collect();
        let got = topo_order(n, &edges).expect("large acyclic graph must succeed");
        let mut want = vec![1, 0];
        for k in 1..n / 2 {
            want.push(2 * k + 1);
            want.push(2 * k);
        }
        assert!(got == want, "topo_order(200000, edges (2k+1, 2k) for 0 <= k < 100000): {}", harness_mismatch(&got, &want));
        let secs = start.elapsed().as_secs_f64();
        assert!(secs < 5.0, "too slow: two graphs with 200000 nodes took {:.1} s", secs);
    }
}
