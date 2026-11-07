"""End-to-end tests against a mock server. They run model "output" in the real sandbox."""
import csv
import socket
import sys
from pathlib import Path

import pytest

import llm_bench

pytestmark = pytest.mark.sandbox

GOOD = """```python
import re

def parse_duration(s):
    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", s)
    if not s or not m:
        raise ValueError(s)
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se
```"""
BAD = "```python\ndef parse_duration(s):\n    return 0\n```"


def run(monkeypatch, tmp_path, *argv):
    monkeypatch.setattr(sys, "argv", ["llm_bench.py", *argv, "-o", str(tmp_path)])
    llm_bench.main()


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_feedback_loop_passes_on_second_attempt(monkeypatch, tmp_path, mock_server):
    s = mock_server(models=["test/model", "nomic-embed-text"], replies=[BAD, GOOD], api_key="k")
    monkeypatch.setenv("LLM_BENCH_API_KEY", "k")
    run(monkeypatch, tmp_path, f"mock={s.url}", "--task", "py_parse_duration", "-t", "x")

    rows = read_rows(tmp_path / "results_mock_x.csv")
    assert [(r["model"], r["passed"], r["passed_on"], r["attempts"]) for r in rows] == [
        ("test/model", "1", "2", "2")]
    # The second request carries the failing test output back to the model.
    assert len(s.requests) == 2
    feedback = s.requests[1]["messages"][-1]["content"]
    assert "got 0, want 5400" in feedback
    attempt = tmp_path / "runs/mock/test_model/py_parse_duration"
    assert (attempt / "attempt_1/response.md").read_text() == BAD
    assert "[exit 0]" in (attempt / "attempt_2/log.txt").read_text()


def test_attempts_one_disables_feedback(monkeypatch, tmp_path, mock_server):
    s = mock_server(replies=[BAD, GOOD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration", "--attempts", "1",
        "--temperature", "0")
    (row,) = read_rows(tmp_path / "results_m.csv")
    assert (row["passed"], row["attempts"]) == ("0", "1")
    assert len(s.requests) == 1 and s.requests[0]["temperature"] == 0


def test_model_filter(monkeypatch, tmp_path, mock_server):
    s = mock_server(models=["a/one", "b/two", "qwen-vl"], replies=[GOOD, GOOD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration", "-m", "b/*", "-m", "qwen-vl")
    assert [r["model"] for r in read_rows(tmp_path / "results_m.csv")] == ["b/two", "qwen-vl"]


def test_unreachable_endpoint_is_skipped(monkeypatch, tmp_path, mock_server):
    s = mock_server(replies=[GOOD])
    run(monkeypatch, tmp_path, "dead=127.0.0.1:9", f"live={s.url}", "--task", "py_parse_duration")
    assert not (tmp_path / "results_dead.csv").exists()
    assert read_rows(tmp_path / "results_live.csv")[0]["passed"] == "1"


def test_sandbox_hides_home(tmp_path):
    _, out = llm_bench.run_cmd(["/bin/bash", "-c", f"ls {Path.home()} || echo HIDDEN"], tmp_path)
    assert "HIDDEN" in out


def test_sandbox_has_no_network(tmp_path):
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        _, out = llm_bench.run_cmd(
            ["/bin/bash", "-c", f"(exec 3<>/dev/tcp/127.0.0.1/{port}) 2>/dev/null && echo OPEN || echo CLOSED"],
            tmp_path)
    assert "CLOSED" in out


def test_sandbox_clears_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BENCH_API_KEY", "secret")
    _, out = llm_bench.run_cmd(["/bin/bash", "-c", "env"], tmp_path)
    env = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    assert env["HOME"] == "/tmp" and "USER" not in env and "LLM_BENCH_API_KEY" not in env


def test_sandbox_enforces_time_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_bench, "CMD_TIMEOUT_S", 2)
    rc, _ = llm_bench.run_cmd(["/bin/sleep", "30"], tmp_path)
    assert rc != 0


def test_private_tasks_dir(monkeypatch, tmp_path, mock_server):
    task = tmp_path / "tasks" / "python" / "double"
    task.mkdir(parents=True)
    (task / "prompt.md").write_text("Write `double(x)` in solution.py.\n")
    (task / "test_solution.py").write_text("from solution import double\nassert double(2) == 4\nprint('ok')\n")
    s = mock_server(replies=["```python\ndef double(x):\n    return 2 * x\n```"])
    run(monkeypatch, tmp_path / "out", f"m={s.url}", "--tasks-dir", str(tmp_path / "tasks"))
    (row,) = read_rows(tmp_path / "out" / "results_m.csv")
    assert (row["task"], row["passed"]) == ("py_double", "1")
    assert s.requests[0]["messages"][1]["content"] == "Write `double(x)` in solution.py."


RUST_WORD_COUNT = """```rust
use std::collections::HashMap;

pub fn word_count(text: &str) -> HashMap<String, usize> {
    let mut m = HashMap::new();
    for w in text.split(|c: char| !c.is_alphanumeric()).filter(|w| !w.is_empty()) {
        *m.entry(w.to_lowercase()).or_insert(0) += 1;
    }
    m
}
```"""


def test_appended_harness_language(monkeypatch, tmp_path, mock_server):
    """Rust harnesses are appended to the solution file instead of written separately."""
    s = mock_server(replies=[RUST_WORD_COUNT])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "rust_word_count", "--attempts", "1")
    (row,) = read_rows(tmp_path / "results_m.csv")
    log = (tmp_path / "runs/m/test_model/rust_word_count/attempt_1/log.txt").read_text()
    assert row["passed"] == "1", log
    assert "4 passed" in log
