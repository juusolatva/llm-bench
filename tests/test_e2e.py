"""End-to-end tests against a mock server. They run model "output" in the real sandbox."""
import csv
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import MODEL_DIR, Reply

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
    attempt = trial_dir(tmp_path / f"runs/mock_x/{MODEL_DIR}/py_parse_duration")
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


def install_must_be_hidden(install, tmp_path):
    """Whether the sandbox must hide a Node installation root: not if it lies under a system path the sandbox
    mounts anyway (/usr for /usr/bin/node or /usr/local/bin/node). The system paths come from sandbox_command's
    binds with the toolchain mounts off, so a toolchain mount that leaks the installation can't excuse itself."""
    tools = {"bwrap": "/usr/bin/bwrap", "systemd-run": "/usr/bin/systemd-run"}
    with pytest.MonkeyPatch.context() as mp:
        for name in ("NODE_BIN", "TS_PACKAGE", "RUST_SYSROOT"):
            mp.setattr(llm_bench, name, None)
        cmd = llm_bench.sandbox_command(tools, "llm-bench-x.service", ["true"], tmp_path, 60, None)
    args = cmd[cmd.index("/usr/bin/bwrap"):cmd.index("--")]
    exposed = [args[i + 1] for i, a in enumerate(args) if a == "--ro-bind" and args[i + 2] == args[i + 1]]
    return not any(install.is_relative_to(path) for path in exposed)


@pytest.mark.parametrize(("install", "hidden"), [
    ("/usr", False),                                    # /usr/bin/node: the sandbox mounts /usr anyway
    ("/usr/local", False),                              # /usr/local/bin/node
    ("/home/someone/.local/share/fnm/node-versions/v24.22.1/installation", True),
    ("/opt/node-v24", True),
])
def test_install_must_be_hidden(tmp_path, install, hidden):
    assert install_must_be_hidden(Path(install), tmp_path) is hidden


def test_sandbox_exposes_only_node_and_typescript(tmp_path, monkeypatch):
    """With TypeScript tasks, the sandbox sees the Node binary and the typescript package read-only, and nothing
    else of the Node installation (npm and global packages next to them) or the home directory around it. (The
    directories bwrap creates for the mounts are on the sandbox's private root tmpfs, like /opt itself.)"""
    for name in ("NODE_BIN", "TS_PACKAGE"):
        monkeypatch.setattr(llm_bench, name, getattr(llm_bench, name))   # restored after the test
    try:
        llm_bench.check_toolchains([{"lang": "ts"}])
    except SystemExit as exc:
        pytest.skip(str(exc))
    install = llm_bench.NODE_BIN.parent.parent
    # A system Node's prefix (/usr) is visible by design; a version manager's installation must not be.
    install_check = f"test -e {shlex.quote(str(install))} && echo INSTALL-VISIBLE" if install_must_be_hidden(install, tmp_path) else ""
    script = f"""
ls -A /opt/node/bin | tr '\\n' ' '; echo
{install_check}
test -e /opt/typescript/package.json && echo PACKAGE-OK
touch /opt/typescript/x 2>/dev/null && echo PACKAGE-WRITABLE
[ -w /opt/typescript/package.json ] && echo PACKAGE-WRITABLE
[ -w /opt/node/bin/node ] && echo NODE-WRITABLE
ls {shlex.quote(str(Path.home()))} >/dev/null 2>&1 && echo HOME-VISIBLE
tsc --version
"""
    out = llm_bench.run_cmd(["/bin/bash", "-c", script], tmp_path).out
    lines = out.splitlines()
    assert lines[0].split() == ["node", "tsc"]
    assert "PACKAGE-OK" in lines
    for leak in ("INSTALL-VISIBLE", "PACKAGE-WRITABLE", "NODE-WRITABLE", "HOME-VISIBLE"):
        assert leak not in lines
    assert any(line.startswith("Version ") for line in lines)


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
    """A --tasks-dir harness must print the final line too: one that ends with a plain "ok" fails every solution."""
    for name, last in (("double", "print('harness: all checks passed')"), ("legacy", "print('ok')")):
        task = tmp_path / "tasks" / "python" / name
        task.mkdir(parents=True)
        (task / "prompt.md").write_text("Write `double(x)` in solution.py.\n")
        (task / "test_solution.py").write_text(f"from solution import double\nassert double(2) == 4\n{last}\n")
    reply = "```python\ndef double(x):\n    return 2 * x\n```"
    s = mock_server(replies=[reply, reply])
    run(monkeypatch, tmp_path / "out", f"m={s.url}", "--tasks-dir", str(tmp_path / "tasks"), "--attempts", "1")
    rows = read_rows(tmp_path / "out" / "results_m.csv")
    assert [(r["task"], r["passed"], r["fail_stage"]) for r in rows] == [
        ("py_double", "1", ""), ("py_legacy", "0", "test")]
    assert s.requests[0]["messages"][1]["content"] == "Write `double(x)` in solution.py."
    log = (trial_dir(tmp_path / f"out/runs/m/{MODEL_DIR}/py_legacy") / "attempt_1/log.txt").read_text()
    assert 'its final line "harness: all checks passed" was never printed' in log


RUST_TOPO_ORDER = (llm_bench.DEFAULT_TASKS_DIR / "rust/topo_order/reference/lib.rs").read_text()


def test_rust_harness_is_a_separate_crate(monkeypatch, tmp_path, mock_server):
    """The Rust solution is built as a library and the harness as its own test crate, so the harness sees only
    public items: the reference passes, and the same code without `pub` fails to build with rustc's error."""
    private = RUST_TOPO_ORDER.replace("pub fn topo_order", "fn topo_order")
    assert private != RUST_TOPO_ORDER
    s = mock_server(replies=[f"```rust\n{RUST_TOPO_ORDER}```", f"```rust\n{private}```", f"```rust\n{private}```"])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "rust_topo_order", "--attempts", "1")
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "rust_topo_order", "--attempts", "2")
    good, bad = read_rows(tmp_path / "results_m.csv")
    trial = tmp_path / f"runs/m/{MODEL_DIR}/rust_topo_order" / good["config"] / "repeat_1"
    log = (trial / "attempt_1/log.txt").read_text()
    assert good["passed"] == "1", log
    assert "test result: ok. 3 passed" in log
    assert (bad["passed"], bad["fail_stage"]) == ("0", "build")
    feedback = s.requests[2]["messages"][-1]["content"]
    assert "Output of `rustc --edition 2021 --test" in feedback
    assert "function `topo_order` is private" in feedback


EARLY_EXITS = {   # task: a reply that ends the process with status 0 on the first call (Go: at package load)
    "py_parse_duration": "```python\nimport sys\n\ndef parse_duration(s):\n    sys.exit(0)\n```",
    "c_join_path": "```c\n#include <stdlib.h>\nchar *join_path(const char *a, const char *b) {\n"
                   "    (void)a; (void)b;\n    exit(0);\n}\n```",
    "cpp_top_words": "```cpp\n#include <cstdlib>\n#include <string>\n#include <utility>\n#include <vector>\n"
                     "inline std::vector<std::pair<std::string, int>> top_words(const std::string&, std::size_t) {\n"
                     "    std::exit(0);\n}\n```",
    "rust_csv_line": "```rust\npub fn parse_csv_line(_line: &str) -> Result<Vec<String>, String> {\n"
                     "    std::process::exit(0)\n}\n```",
    "go_word_freq": "```go\npackage solution\n\nimport (\n\t\"io\"\n\t\"os\"\n)\n\nfunc init() { os.Exit(0) }\n\n"
                    "func WordFreq(r io.Reader) (map[string]int, error) { return nil, nil }\n```",
}


def builtin_task(name):
    """The built-in task `name`; skips the test if its toolchain is missing."""
    (task,) = [t for t in llm_bench.load_tasks([llm_bench.DEFAULT_TASKS_DIR]) if t["name"] == name]
    try:
        llm_bench.check_toolchains([task])
    except SystemExit as exc:
        pytest.skip(str(exc))
    return task


@pytest.mark.parametrize("name", [n for n in EARLY_EXITS if not n.startswith("go_")])
def test_early_exit_fails(name, tmp_path):
    """A solution that ends the process with status 0 before the harness finishes fails at the test stage, and the
    output names the missing final line. (Before the final line was required, all of these passed.)"""
    check_early_exit(builtin_task(name), tmp_path)


def test_go_early_exit_fails(tmp_path, go_cache):
    """Like test_early_exit_fails, for Go (os.Exit(0) in init()), which needs the warmed build cache."""
    check_early_exit(builtin_task("go_word_freq"), tmp_path)


def check_early_exit(task, tmp_path):
    code = llm_bench.extract_code(EARLY_EXITS[task["name"]], task["lang"])
    passed, log, stage, cmd, out = llm_bench.run_task(task, code, tmp_path / "w")
    last_cmd = llm_bench.shlex.join(llm_bench.LANGS[task["lang"]]["cmds"][-1])
    assert (passed, stage, cmd) == (False, "test", last_cmd), log
    assert log.endswith("[exit 0]"), log
    assert "exited with status 0 before it finished" in out


UNTERMINATED = {   # task: a correct solution whose own output, without a final newline, precedes the final line
    "py_parse_duration": GOOD.replace("import re\n", "import re\nimport sys\nsys.stderr.write('loading')\n"
                                      "print('loaded', end='')\n"),
    "c_join_path": "```c\n" + (llm_bench.DEFAULT_TASKS_DIR / "c/join_path/reference/solution.c").read_text()
                   + '#include <stdio.h>\n__attribute__((constructor)) static void greet(void) { printf("hi"); }\n```',
}


@pytest.mark.parametrize("name", UNTERMINATED)
def test_unterminated_solution_output_still_passes(name, tmp_path):
    """The final line counts anywhere in a line, so a correct solution whose own output lacks a final newline passes."""
    task = builtin_task(name)
    passed, log, *_ = llm_bench.run_task(task, llm_bench.extract_code(UNTERMINATED[name], task["lang"]), tmp_path / "w")
    assert passed, log
    assert "harness: all checks passed" in log


def test_early_exit_feedback(monkeypatch, tmp_path, mock_server):
    s = mock_server(replies=[EARLY_EXITS["py_parse_duration"], GOOD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration")
    (row,) = read_rows(tmp_path / "results_m.csv")
    assert (row["passed"], row["passed_on"]) == ("1", "2")
    feedback = s.requests[1]["messages"][-1]["content"]
    assert "Output of `python3 test_solution.py`:" in feedback
    assert 'its final line "harness: all checks passed" was never printed' in feedback
    assert "sys.exit()" in feedback


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
    log = (trial_dir(tmp_path / f"runs/m/{MODEL_DIR}/py_parse_duration") / "attempt_1/log.txt").read_text()
    assert "[killed: exceeded the 3 s time limit" in log


def test_rerun_appends_and_tag_separates_transcripts(monkeypatch, tmp_path, mock_server):
    s = mock_server(replies=[GOOD, GOOD, GOOD])
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration")
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration")
    assert len(read_rows(tmp_path / "results_m.csv")) == 2
    run(monkeypatch, tmp_path, f"m={s.url}", "--task", "py_parse_duration", "-t", "x")
    assert trial_dir(tmp_path / f"runs/m/{MODEL_DIR}/py_parse_duration").is_dir()
    assert trial_dir(tmp_path / f"runs/m/{MODEL_DIR}/py_parse_duration", 2).is_dir()   # re-run: next repeat number
    assert trial_dir(tmp_path / f"runs/m_x/{MODEL_DIR}/py_parse_duration").is_dir()


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
