"""End-to-end tests against a mock server. They run model "output" in the real sandbox."""
import csv
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import Reply

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


def trial_dir(task_dir, repeat=1):
    """The transcript directory runs/<endpoint>/<model>/<task>/<config>/repeat_<r>/ of the only config."""
    (d,) = task_dir.glob(f"*/repeat_{repeat}")
    return d


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
    attempt = trial_dir(tmp_path / "runs/mock_x/test_model/py_parse_duration")
    assert (attempt / "attempt_1/response.md").read_text() == BAD
    assert "[exit 0]" in (attempt / "attempt_2/log.txt").read_text()


def test_attempts_one_disables_feedback(monkeypatch, tmp_path, mock_server):
    s = mock_server(replies=[BAD, GOOD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration", "--attempts", "1",
        "--temperature", "0")
    (row,) = read_rows(tmp_path / "results_m.csv")
    assert (row["passed"], row["attempts"]) == ("0", "1")
    assert len(s.requests) == 1
    assert s.requests[0]["temperature"] == 0


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
    out = llm_bench.run_cmd(["/bin/bash", "-c", f"ls {Path.home()} || echo HIDDEN"], tmp_path).out
    assert "HIDDEN" in out


def test_sandbox_has_no_network(tmp_path):
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        out = llm_bench.run_cmd(
            ["/bin/bash", "-c", f"(exec 3<>/dev/tcp/127.0.0.1/{port}) 2>/dev/null && echo OPEN || echo CLOSED"],
            tmp_path).out
    assert "CLOSED" in out


def test_sandbox_clears_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_BENCH_API_KEY", "secret")
    out = llm_bench.run_cmd(["/bin/bash", "-c", "env"], tmp_path).out
    env = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    assert env["HOME"] == "/tmp"
    assert "USER" not in env
    assert "LLM_BENCH_API_KEY" not in env


def test_sandbox_enforces_time_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_bench, "CMD_TIMEOUT_S", 2)
    result = llm_bench.run_cmd(["/bin/sleep", "30"], tmp_path)
    assert result.rc != 0
    assert result.timed_out
    assert "[killed: exceeded the 2 s time limit" in result.out
    fast = llm_bench.run_cmd(["/bin/false"], tmp_path)
    assert fast.rc != 0
    assert not fast.timed_out
    assert "killed" not in fast.out


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


RUST_TOPO_ORDER = "```rust\n" + (llm_bench.DEFAULT_TASKS_DIR / "rust/topo_order/reference/lib.rs").read_text() + "```"


def test_appended_harness_language(monkeypatch, tmp_path, mock_server):
    """Rust harnesses are appended to the solution file instead of written separately."""
    s = mock_server(replies=[RUST_TOPO_ORDER])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "rust_topo_order", "--attempts", "1")
    (row,) = read_rows(tmp_path / "results_m.csv")
    log = (trial_dir(tmp_path / "runs/m/test_model/rust_topo_order") / "attempt_1/log.txt").read_text()
    assert row["passed"] == "1", log
    assert "3 passed" in log


def test_feedback_names_failing_command(monkeypatch, tmp_path, mock_server):
    s = mock_server(replies=[BAD, GOOD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration")
    assert "Output of `python3 test_solution.py`:" in s.requests[1]["messages"][-1]["content"]
    (row,) = read_rows(tmp_path / "results_m.csv")
    assert row["fail_stage"] == ""   # passed in the end


C_JOIN_WRONG = "```c\nchar *join_path(const char *a, const char *b) { (void)a; (void)b; return 0; }\n```"
C_JOIN_BROKEN = "```c\nchar *join_path(const char *a, const char *b) { return a }\n```"


@pytest.mark.parametrize(("reply", "stage", "cmd"), [
    (C_JOIN_BROKEN, "build", "gcc -std=gnu17"),
    (C_JOIN_WRONG, "test", "./t"),
])
def test_fail_stage_build_vs_test(monkeypatch, tmp_path, mock_server, reply, stage, cmd):
    s = mock_server(replies=[reply, reply])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "c_join_path", "--attempts", "2")
    (row,) = read_rows(tmp_path / "results_m.csv")
    assert row["fail_stage"] == stage
    assert f"Output of `{cmd}" in s.requests[1]["messages"][-1]["content"]


def test_time_limit_is_reported(monkeypatch, tmp_path, mock_server):
    monkeypatch.setattr(llm_bench, "CMD_TIMEOUT_S", 3)
    s = mock_server(replies=["```python\nwhile True:\n    pass\n```", BAD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration", "--attempts", "2")
    (row,) = read_rows(tmp_path / "results_m.csv")
    assert row["fail_stage"] == "test"   # the last attempt failed normally
    first = s.requests[1]["messages"][-1]["content"]
    assert "exceeded the 3 s time limit" in first
    assert "[killed:" in first
    log = (trial_dir(tmp_path / "runs/m/test_model/py_parse_duration") / "attempt_1/log.txt").read_text()
    assert "[killed: exceeded the 3 s time limit" in log


def test_rerun_appends_and_tag_separates_transcripts(monkeypatch, tmp_path, mock_server):
    s = mock_server(replies=[GOOD, GOOD, GOOD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration")
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration")
    assert len(read_rows(tmp_path / "results_m.csv")) == 2
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration", "-t", "x")
    assert trial_dir(tmp_path / "runs/m/test_model/py_parse_duration").is_dir()
    assert trial_dir(tmp_path / "runs/m/test_model/py_parse_duration", 2).is_dir()   # re-run: next repeat number
    assert trial_dir(tmp_path / "runs/m_x/test_model/py_parse_duration").is_dir()


def test_ctrl_c_stops_promptly(tmp_path, mock_server):
    s = mock_server(replies=[Reply(text=GOOD, sleep=30)])
    script = Path(llm_bench.__file__)
    proc = subprocess.Popen([sys.executable, str(script), f"m={s.url}", "--task", "py_parse_duration",
                             "-o", str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 30
    while not s.requests and time.monotonic() < deadline:   # wait until the request is in flight
        time.sleep(0.1)
    assert s.requests, "request never arrived"
    proc.send_signal(signal.SIGINT)
    out, err = proc.communicate(timeout=10)
    assert proc.returncode == 130
    assert "interrupted" in err
    assert "no results" in out


def test_go_cache_overlay_is_private(tmp_path, monkeypatch):
    """Sandboxes see GO_CACHE's contents but their writes go to a throwaway layer."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "entry").write_text("cached\n")
    monkeypatch.setattr(llm_bench, "GO_CACHE", cache)
    work = tmp_path / "work"
    work.mkdir()
    script = 'cat /opt/go-cache/entry; echo "$GOCACHE"; echo tampered > /opt/go-cache/entry; touch /opt/go-cache/new'
    result = llm_bench.run_cmd(["/bin/bash", "-ec", script], work)
    assert result.rc == 0, result.out
    assert result.out.split()[:2] == ["cached", "/opt/go-cache"]
    assert (cache / "entry").read_text() == "cached\n"
    assert not (cache / "new").exists()
