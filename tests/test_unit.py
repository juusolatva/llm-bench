import hashlib
import sys
import time
import urllib.error
from collections import Counter

import pytest
from conftest import Reply

import llm_bench


@pytest.mark.parametrize(("spec", "want"), [
    ("localhost:1234", ("localhost_1234", "http://localhost:1234/v1")),
    ("http://localhost:11434/v1/", ("localhost_11434", "http://localhost:11434/v1")),
    ("gpu-box", ("gpu-box", "http://gpu-box/v1")),
    ("x=https://api.example.com/openai/v1", ("x", "https://api.example.com/openai/v1")),
    ("my box=localhost:8080", ("my_box", "http://localhost:8080/v1")),
    ("http://[::1]:8080", ("__1_8080", "http://[::1]:8080/v1")),
    ("http://host:1/v1?a=b", ("host_1", "http://host:1/v1")),
])
def test_parse_endpoint(spec, want):
    assert llm_bench.parse_endpoint(spec) == want


@pytest.mark.parametrize("spec", ["ftp://host", "http://", "x=", "file:///etc"])
def test_parse_endpoint_rejects(spec):
    with pytest.raises(ValueError):
        llm_bench.parse_endpoint(spec)


def test_parse_endpoint_name_is_path_safe():
    name, _ = llm_bench.parse_endpoint("../../etc=http://h:1")
    assert "/" not in name


@pytest.mark.parametrize(("name", "want"), [
    ("qwen/qwen3:8b", "qwen_qwen3_8b"), ("..", "_."), (".", "_"), ("", "_"), (".hidden", "_hidden"),
    ("a..b", "a..b"), ("../../etc", "_._.._etc"),
])
def test_safe_name(name, want):
    assert llm_bench.safe_name(name) == want


def sha16(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def test_model_dirs_hash_unsafe_ids():
    dirs = llm_bench.model_dirs([".foo", "_foo", "a/b", "a_b", "llama3.1-8b", "qwen/qwen3:8b"])
    assert all(dirs[m] == m for m in ("_foo", "a_b", "llama3.1-8b"))   # already safe: unchanged
    assert dirs[".foo"] == "_foo~" + sha16(".foo")
    assert dirs["a/b"] == "a_b~" + sha16("a/b")
    assert dirs["qwen/qwen3:8b"] == "qwen_qwen3_8b~" + sha16("qwen/qwen3:8b")
    assert llm_bench.model_dirs(["x", "x"]) == {"x": "x"}


def test_model_dirs_dont_depend_on_the_selection():
    """Runs that select different models never share a directory: a/b alone and a_b alone (and an ID equal to
    another's hashed name) get different names, so a later run can't delete an earlier run's transcripts."""
    hashed = llm_bench.model_dirs(["a/b"])["a/b"]
    assert llm_bench.model_dirs(["a_b"]) == {"a_b": "a_b"}
    assert llm_bench.model_dirs([hashed])[hashed] not in {hashed, "a_b"}   # "~" isn't safe, so it's hashed too
    assert llm_bench.model_dirs(["a_b", "a/b", hashed])["a/b"] == hashed


def test_model_dirs_fit_the_file_name_limit():
    """Names stay within MODEL_DIR_BYTES (file systems allow 255 bytes per name), also for long safe IDs and for
    multi-byte characters, which are never cut in half."""
    limit = llm_bench.MODEL_DIR_BYTES
    unsafe, safe, wide = "a" * 240 + "/", "b" * (limit + 1), "é" * 150 + "/"
    dirs = llm_bench.model_dirs([unsafe, safe, wide, "c" * limit])
    assert dirs["c" * limit] == "c" * limit   # exactly at the limit: unchanged
    assert dirs[unsafe] == "a" * (limit - 17) + "~" + sha16(unsafe)
    assert dirs[safe] == "b" * (limit - 17) + "~" + sha16(safe)
    assert dirs[wide] == "é" * ((limit - 17) // 2) + "~" + sha16(wide)
    assert all(len(d.encode()) <= limit for d in dirs.values())


def test_model_dirs_number_hash_collisions(monkeypatch):
    class FakeHash:
        def hexdigest(self):
            return "0" * 64
    monkeypatch.setattr(llm_bench.hashlib, "sha256", lambda data: FakeHash())
    assert llm_bench.model_dirs(["a/b", "a:b", "a b"]) == {
        "a/b": "a_b~" + "0" * 16, "a:b": "a_b~" + "0" * 16 + "-2", "a b": "a_b~" + "0" * 16 + "-3"}


@pytest.mark.parametrize(("out", "want"), [
    ("$ ./t\nharness: all checks passed\n", True),
    ("$ gcc x.c\n$ ./t\nstuff\nharness: all checks passed (3 checks)\nmore\n", True),   # a prefix match
    ("$ ./t\n", False),                                                  # ended early
    ("$ ./t\nall checks passed\n", False),
    ("$ ./t\nloadedharness: all checks passed\n", True),                # after the solution's unterminated output
    ("$ ./t\nall checks passed\nharness: all\n", False),
    ("harness: all checks passed\n$ ./t\n", False),                      # only before the last command
    ("$ gcc x.c\nharness: all checks passed\n", False),                  # the last command never started
    ("$ ./t\nharness: all checks passed\n$ ./t\n", False),               # the last "$ ./t" line counts
])
def test_finished(out, want):
    assert llm_bench.finished(out, "./t", llm_bench.HARNESS_FINAL_LINE) is want


def test_finished_rust_summary_line():
    out = "$ ./t\n\nrunning 3 tests\n...\ntest result: ok. 3 passed; 0 failed; 0 ignored\n"
    assert llm_bench.finished(out, "./t", llm_bench.LANGS["rust"]["final_line"])
    assert not llm_bench.finished("$ ./t\n\nrunning 3 tests\n", "./t", llm_bench.LANGS["rust"]["final_line"])


@pytest.mark.parametrize(("lang", "output", "passed"), [
    ("python", "harness: all checks passed\n", True),
    ("python", "", False),
    ("rust", "running 3 tests\ntest result: ok. 3 passed\n", True),
    ("rust", "running 3 tests\n", False),
])
def test_run_task_needs_the_final_line(monkeypatch, tmp_path, lang, output, passed):
    """Exit status 0 passes only with the language's final line; without it the attempt fails at the test stage
    and the output explains why. (run_cmd is stubbed: this checks run_task's logic, not the sandbox.)"""
    spec = llm_bench.LANGS[lang]
    rendered = [llm_bench.shlex.join(c) for c in spec["cmds"]]
    out = "".join(f"$ {r}\n" for r in rendered) + output
    monkeypatch.setattr(llm_bench, "run_cmd", lambda cmd, cwd: llm_bench.CmdResult(0, out, False))
    task = {"lang": lang, "test": "the harness"}
    ok, log, stage, cmd, fail_out = llm_bench.run_task(task, "the solution", tmp_path / "w")
    assert ok is passed
    assert (tmp_path / "w" / spec["sol"]).read_text() == "the solution"   # written separately, also for Rust
    assert (tmp_path / "w" / spec["test"]).read_text() == "the harness"
    assert log.endswith("[exit 0]")
    if passed:
        assert (stage, cmd, fail_out) == (None, None, None)
    else:
        assert (stage, cmd) == ("test", rendered[-1])
        note = f'its final line "{spec["final_line"]}" was never printed'
        assert note in fail_out
        assert note in log
        assert "Your solution failed. Output of `" in llm_bench.feedback(stage, cmd, fail_out)


def test_extract_code_strips_think():
    text = "<think>```python\nbad\n```</think>intro\n```python\nfirst\n```"
    assert llm_bench.extract_code(text, "python") == "first\n"


@pytest.mark.parametrize(("text", "want"), [
    ("reasoning\n```python\nbad\n```\n</think>\n```python\ngood\n```", "good\n"),   # unpaired </think>
    ("<think>never finished\n```python\nbad\n```", ""),                        # unclosed <think>
    ("  \n<think>\n```python\nbad\n```\n", ""),
    ("I removed the <think> tags.\n```python\ngood\n```", "good\n"),           # <think> in prose
    ("plan\n</think>\n```python\ngood\n```\nIt drops </think> tags.", "good\n"),  # </think> in prose
    ("```python\ngood\n```\nThe </think> tag is not used.", "good\n"),          # no reasoning at all
    ("plan ```python\nbad\n```\n</think>\nok:\n```python\ngood\n```", "good\n"),
    ("plan\n</think>\nx = 1\n", "\nx = 1\n"),                                   # no fence: after first
])
def test_extract_code_partial_think(text, want):
    assert llm_bench.extract_code(text, "python") == want


def test_extract_code_prefers_matching_language_tag():
    text = "```bash\npip install nothing here at all\n```\n```py\ncode\n```\nUsage:\n```\nexample()\n```"
    assert llm_bench.extract_code(text, "python") == "code\n"
    assert llm_bench.extract_code(text, "rust") == "pip install nothing here at all\n"   # no rust block: longest


def test_extract_code_takes_last_unless_much_shorter():
    full = "func Solution() int {\n\treturn 42\n}\n"
    # A short usage example after the solution loses to the solution.
    assert llm_bench.extract_code(f"```go\n{full}```\n```go\nSolution()\n```", "go") == full
    # Original first, then a slightly shorter fix: the fix (last) wins.
    orig, fixed = "def f(rows, n=3, totals={}):\n    return totals\n", "def f(rows, n=3):\n    return {}\n"
    assert llm_bench.extract_code(f"Original:\n```python\n{orig}```\nFixed:\n```python\n{fixed}```", "python") == fixed
    # Equally long blocks: the last one; tags are case-insensitive.
    assert llm_bench.extract_code("```c\na\n```\n```C\nb\n```", "c") == "b\n"


def test_extract_code_tag_with_suffix():
    text = "```python:solution.py\ncode\n```\n```bash\npython3 solution.py --help\n```"
    assert llm_bench.extract_code(text, "python") == "code\n"
    assert llm_bench.extract_code("```c++ title=x\nint x;\n```", "cpp") == "int x;\n"


@pytest.mark.parametrize(("text", "want"), [
    ("````python\nprint(1)\n````", "print(1)\n"),          # 4-backtick fence
    ("```python\nx = 1```", "x = 1"),                       # closing fence glued to code
    ("Here: ```python\nx = 1\n```", "x = 1\n"),             # opening fence mid-line
])
def test_extract_code_loose_fallback(text, want):
    assert llm_bench.extract_code(text, "python") == want


@pytest.mark.parametrize(("text", "want"), [
    ("Wrap code in ``` fences.\n```python\ngood\n```", "good\n"),       # prose mention isn't a fence
    ("Put it below ```\n```python\ngood\n```", "good\n"),                 # untagged mid-line fence isn't either
    ("```python\nx = '``` inside'\n```", "x = '``` inside'\n"),        # backticks mid-line in code
    ("````markdown\n```python\nnested\n```\n````", "```python\nnested\n```\n"),   # longer outer fence
    ("```python\nx = 1\n```text\ny = 2\n```", "x = 1\n```text\ny = 2\n"),       # ```text doesn't close
    ("```python\nprint(\"```\")\n```", "print(\"```\")\n"),                # nor a fence inside a string
])
def test_extract_code_fence_pairing(text, want):
    assert llm_bench.extract_code(text) == want


def test_extract_code_crlf_reply():
    text = "<think>\r\nplan\r\n</think>\r\nHere: ```bash\r\necho hi\r\n```\r\nDone.\r\n"
    assert llm_bench.extract_code(text, "bash") == "echo hi\n"
    assert llm_bench.extract_code("```python\r\nx = 1\r\n```\r\n", "python") == "x = 1\n"


def test_extract_code_mixes_loose_and_strict_blocks():
    solution = "def solve():\n    return 42\n"
    text = f"````python\n{solution}````\nUsage:\n```python\nsolve()\n```"
    assert llm_bench.extract_code(text, "python") == solution
    tagged = "Here: ```python\ns = '<think>x</think>'\n```"   # think tags inside a loose block stay
    assert llm_bench.extract_code(tagged, "python") == "s = '<think>x</think>'\n"


def test_extract_code_fence_details():
    # Info strings after the tag, indented fences and backticks inside the code.
    text = "  ```python title=solution.py\n  s = '```'\n  ```"
    assert llm_bench.extract_code(text, "python") == "  s = '```'\n"
    assert llm_bench.extract_code("```cpp\n```", "cpp") == ""


def test_extract_code_without_fence_returns_text():
    assert llm_bench.extract_code("<think>x</think>plain", "python") == "plain"
    assert llm_bench.extract_code("plain") == "plain"


def test_extract_code_keeps_think_tags_inside_code():
    text = "<think>plan</think>\n```python\ndef render():\n    return '</think>' + '<think>x</think>'\n```"
    assert llm_bench.extract_code(text, "python") == "def render():\n    return '</think>' + '<think>x</think>'\n"


def test_strip_think_is_linear(monkeypatch):
    """Many tags inside code must not rescan the reply once per tag."""
    scans = []
    real = llm_bench._code_blocks
    monkeypatch.setattr(llm_bench, "_code_blocks", lambda text: scans.append(1) or real(text))
    reply = "```python\n" + "s = '<think></think>'\n" * 20000 + "```\n"
    start = time.monotonic()
    assert llm_bench.strip_think(reply) == reply
    assert len(scans) <= 2
    assert time.monotonic() - start < 2


@pytest.mark.parametrize("reply", [
    "`" * 200000, "```" + " " * 200000, "```py\n" + "`" * 200000, "x " * 100000 + "```" + "\t" * 100000 + "y",
    "```py\na\n" * 50000, "Here: ```python\nx ```\n" * 50000, "````py\nx````\n" * 30000 + "```\n" * 30000,
])
def test_extract_code_degenerate_replies_are_fast(reply):
    start = time.monotonic()
    llm_bench.extract_code(reply, "python")
    assert time.monotonic() - start < 2


def test_strip_think_many_unclosed_tags_is_fast():
    start = time.monotonic()
    assert llm_bench.strip_think("<think>x " * 100000) == ""
    assert llm_bench.strip_think("<think>a</think>b " + "<think>x " * 100000).startswith("b ")
    assert time.monotonic() - start < 2


def test_strip_think():
    assert llm_bench.strip_think("<think>a</think>b<think>c</think>d") == "bd"
    assert llm_bench.strip_think("no reasoning") == "no reasoning"


def test_clip_keeps_head_and_tail():
    text = "H" * 100 + "T" * 100
    out = llm_bench.clip(text, limit=30)
    assert out.startswith("H" * 20)
    assert out.endswith("T" * 10)
    assert "truncated" in out
    assert llm_bench.clip("short", limit=30) == "short"


@pytest.mark.parametrize(("model", "keep"), [
    ("qwen3-coder:30b", True),
    ("nomic-embed-text", False),
    ("text-embedding-3-small", False),
    ("qwen2.5-vl-7b", False),
    ("Qwen/Qwen2.5-VL-7B", False),
    ("devlin-7b", True),
])
def test_default_model_filter(model, keep):
    assert llm_bench.default_model_filter(model) is keep


def test_check_toolchains_checks_the_tools_of_selected_languages(monkeypatch):
    """A language's "tools" are checked like its commands, and only for the selected tasks' languages."""
    monkeypatch.setattr(llm_bench.shutil, "which", lambda name: None if name in ("gawk", "go") else f"/usr/bin/{name}")
    with pytest.raises(SystemExit, match=r"missing toolchains on PATH: gawk\n"):
        llm_bench.check_toolchains([{"lang": "term"}, {"lang": "bash"}])
    llm_bench.check_toolchains([{"lang": "bash"}, {"lang": "python"}])   # gawk and go aren't needed


BUILTIN_TASKS = llm_bench.load_tasks([llm_bench.DEFAULT_TASKS_DIR])


def test_builtin_tasks_are_consistent():
    names = [t["name"] for t in BUILTIN_TASKS]
    assert len(names) == len(set(names))
    for t in BUILTIN_TASKS:
        assert t["name"].startswith(llm_bench.LANGS[t["lang"]]["prefix"] + "_")
        assert t["prompt"]
        assert t["test"].strip()
    per_lang = Counter(t["lang"] for t in BUILTIN_TASKS)
    assert set(per_lang) == set(llm_bench.LANGS)
    assert all(n == 4 for n in per_lang.values())
    assert all(sum(t["lang"] == lang and "_fix_" in t["name"] for t in BUILTIN_TASKS) == 1
               for lang in llm_bench.LANGS)


@pytest.mark.parametrize("task", BUILTIN_TASKS, ids=[t["name"] for t in BUILTIN_TASKS])
def test_builtin_harnesses_print_the_final_line(task):
    """Each harness prints its language's final line, which run_task requires (Rust: libtest prints it). Go
    harnesses print it from TestMain; Rust harnesses import the solution's public items by name, so a missing
    `pub` fails with rustc's "is private" error."""
    test, done = task["test"], llm_bench.LANGS[task["lang"]]["final_line"]
    if task["lang"] == "rust":
        assert done == "test result: ok."
        assert "super::" not in test
        assert "use solution::" in test
        assert "use solution::*" not in test
    else:
        assert done == llm_bench.HARNESS_FINAL_LINE
        assert test.count(done) == 1
    if task["lang"] == "go":
        assert "func TestMain(m *testing.M)" in test


def make_task(root, lang, name, prompt="Write it.", test="echo ok\n"):
    d = root / lang / name
    d.mkdir(parents=True)
    if prompt is not None:
        (d / "prompt.md").write_text(prompt)
    if test is not None:
        (d / llm_bench.LANGS[lang]["test"]).write_text(test)
    return d


def test_load_tasks_layout_and_order(tmp_path):
    make_task(tmp_path, "bash", "b_task")
    make_task(tmp_path, "python", "zeta", prompt="\n  Do Z.\n\n")
    make_task(tmp_path, "python", "alpha")
    (make_task(tmp_path, "rust", "r") / "reference").mkdir()   # extra files/dirs are ignored
    (tmp_path / "python" / "__pycache__").mkdir()
    (tmp_path / "README.md").write_text("ignored")
    tasks = llm_bench.load_tasks([tmp_path])
    assert [(t["name"], t["lang"]) for t in tasks] == [
        ("py_alpha", "python"), ("py_zeta", "python"), ("rust_r", "rust"), ("bash_b_task", "bash")]
    assert tasks[1]["prompt"] == "Do Z."
    assert tasks[0]["test"] == "echo ok\n"


def test_load_tasks_multiple_roots(tmp_path):
    make_task(tmp_path / "a", "go", "one")
    make_task(tmp_path / "b", "python", "two")
    make_task(tmp_path / "b", "go", "three")
    names = [t["name"] for t in llm_bench.load_tasks([tmp_path / "a", tmp_path / "b"])]
    assert names == ["py_two", "go_one", "go_three"]


@pytest.mark.parametrize(("setup", "error"), [
    (lambda r: make_task(r, "python", "x", prompt=None), "missing prompt.md"),
    (lambda r: make_task(r, "python", "x", test=None), "missing test_solution.py"),
    (lambda r: make_task(r, "python", "x", prompt=" \n"), "empty prompt"),
    (lambda r: make_task(r, "python", "Bad-Name"), "only a-z"),
    (lambda r: (r / "java" / "x").mkdir(parents=True), "unknown language"),
    (lambda r: None, "not found"),
])
def test_load_tasks_rejects(tmp_path, setup, error):
    root = tmp_path / "tasks"
    if error != "not found":
        root.mkdir()
    setup(root)
    with pytest.raises(ValueError, match=error):
        llm_bench.load_tasks([root])


def test_load_tasks_rejects_duplicates_across_roots(tmp_path):
    make_task(tmp_path / "a", "c", "same")
    make_task(tmp_path / "b", "c", "same")
    with pytest.raises(ValueError, match="duplicate task c_same"):
        llm_bench.load_tasks([tmp_path / "a", tmp_path / "b"])


def test_http_json_sends_api_key(mock_server):
    s = mock_server(api_key="sekrit")
    assert llm_bench.list_models("m", s.url, "sekrit") == ["test/model"]
    assert llm_bench.list_models("m", s.url, "wrong") == []   # 401 is reported and skipped


def test_http_json_enforces_size_cap(mock_server, monkeypatch):
    s = mock_server(models=["x" * 1000])
    monkeypatch.setattr(llm_bench, "MAX_RESPONSE_BYTES", 100)
    with pytest.raises(ValueError, match="exceeds"):
        llm_bench.http_json(f"{s.url}/models")


@pytest.mark.parametrize(("status", "location", "target"), [
    (302, "http://127.0.0.1:9/v1/models", "redirect to 'http://127.0.0.1:9/v1/models'"),
    (308, "https://example.com/v1/models", "redirect to 'https://example.com/v1/models'"),
    (302, "file:///etc/passwd", "redirect to 'file:///etc/passwd'"),   # urllib refuses this one itself
    (302, None, "redirect"),
    (300, "/v1/models/a", "redirect to '{base}/v1/models/a'"),       # urllib has no handler for 300
    (301, "http://[bad", "redirect to 'http://[bad'"),               # urljoin() can't parse it
])
def test_http_json_refuses_redirects(mock_server, status, location, target):
    # urllib's default handler would read the whole redirect body (no size cap; here it would wait for the
    # rest until the timeout) and send the API key to the new location. The error has an empty body.
    s = mock_server(api_key="sekrit", models_reply=Reply(status=status, body=b"<html>Moved</html>", length=10**9,
                                                         hold=10, headers={"Location": location} if location else {}))
    t0 = time.monotonic()
    with pytest.raises(urllib.error.HTTPError) as e:
        llm_bench.http_json(f"{s.url}/models", timeout=5, api_key="sekrit")
    assert time.monotonic() - t0 < 3
    assert e.value.code == status
    assert f"; {target.format(base=s.url.removesuffix('/v1'))} not followed (use the final URL" in e.value.reason
    assert e.value.read() == b""
    assert s.gets == ["/v1/models"]


def test_list_models_reports_redirect(mock_server, capsys):
    s = mock_server(models_reply=Reply(status=301, body=b"", headers={"Location": "/v2/models"}))
    assert llm_bench.list_models("m", s.url, None) == []
    err = capsys.readouterr().err
    assert f"HTTP Error 301: Moved Permanently; redirect to '{s.url.removesuffix('/v1')}/v2/models' not followed" in err
    assert s.gets == ["/v1/models"]


def test_list_models_unreachable(capsys):
    assert llm_bench.list_models("dead", "http://127.0.0.1:9/v1", None) == []
    assert "dead: skipping" in capsys.readouterr().err


def test_print_summary(capsys):
    rows = [
        {"endpoint": "a-long-endpoint-name", "model": "m1", "task": "py_x", "lang": "python", "passed": 1, "passed_on": 1,
         "prompt_tokens": 10, "completion_tokens": 5, "seconds": 1.0},
        {"endpoint": "a-long-endpoint-name", "model": "m1", "task": "go_x", "lang": "go", "passed": 0, "passed_on": 0,
         "prompt_tokens": 10, "completion_tokens": 5, "seconds": 1.0},
    ]
    llm_bench.print_summary(rows)
    out = capsys.readouterr().out
    for column in ("pass@1", "passed", "python", "go"):
        assert column in out
    assert "c" not in out.splitlines()[1].split()   # only languages that were run get a column
    assert "a-long-endpoint-name m1" in out


def run_main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["llm_bench.py", *argv])
    llm_bench.main()


def test_cli_requires_endpoint(monkeypatch, capsys):
    monkeypatch.delenv("LLM_BENCH_ENDPOINTS", raising=False)
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch)
    assert exc.value.code == 2
    assert "no endpoint given" in capsys.readouterr().err


def test_cli_list_tasks(monkeypatch, capsys):
    run_main(monkeypatch, "--list-tasks", "--task", "rust_*")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 4
    assert all(line.startswith("rust_") for line in lines)


def test_cli_tasks_dir(monkeypatch, capsys, tmp_path):
    make_task(tmp_path, "python", "mine")
    run_main(monkeypatch, "--list-tasks", "--tasks-dir", str(tmp_path))
    assert capsys.readouterr().out.split() == ["py_mine", "python"]
    run_main(monkeypatch, "--list-tasks", "--tasks-dir", str(tmp_path),
             "--tasks-dir", str(llm_bench.DEFAULT_TASKS_DIR))
    assert len(capsys.readouterr().out.splitlines()) == 1 + len(BUILTIN_TASKS)


def test_cli_bad_tasks_dir(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="cannot load tasks"):
        run_main(monkeypatch, "--list-tasks", "--tasks-dir", str(tmp_path / "nope"))


def test_cli_rejects_duplicate_endpoint_names(monkeypatch):
    with pytest.raises(SystemExit, match="duplicate"):
        run_main(monkeypatch, "a=h1:1", "a=h2:2")


@pytest.mark.parametrize("arg", ["--attempts=0", "--timeout=-1", "--max-tokens=x"])
def test_cli_rejects_bad_numbers(monkeypatch, arg):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "localhost:1", arg)
    assert exc.value.code == 2


@pytest.mark.parametrize(("spec", "want"), [
    ("top_p=0.9", ("top_p", 0.9)),
    ("seed=1", ("seed", 1)),
    ("stop=[\"END\"]", ("stop", ["END"])),
    ("reasoning_effort=low", ("reasoning_effort", "low")),
    ("x=", ("x", "")),
])
def test_parse_param(spec, want):
    assert llm_bench.parse_param(spec) == want


@pytest.mark.parametrize("args", [["--param", "noequals"], ["--param", "max_tokens=5"],
                                  ["--param", "model=x"], ["--temperature", "0.2", "--param", "temperature=0.5"]])
def test_cli_rejects_bad_params(monkeypatch, args):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "localhost:1", *args)
    assert exc.value.code == 2


def test_cli_summary_mode(monkeypatch, capsys, tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("endpoint,model,task,lang,passed,passed_on\ne,m,py_a,python,1,1\ne,m,py_b,python,0,0\n")
    monkeypatch.delenv("LLM_BENCH_ENDPOINTS", raising=False)
    run_main(monkeypatch, "--summary", str(path))
    assert "1/2" in capsys.readouterr().out


def test_cli_summary_bad_file(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="cannot read results"):
        run_main(monkeypatch, "--summary", str(tmp_path / "missing.csv"))


def test_cli_summary_formats(monkeypatch, capsys, tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("endpoint,model,task,lang,passed,passed_on\ne,m,py_a,python,1,1\ne,m,py_b,python,0,0\n")
    run_main(monkeypatch, "--summary", str(path), "--format", "markdown")
    assert "| e | m | 1/2 |" in capsys.readouterr().out
    run_main(monkeypatch, "--summary", str(path), "--format", "csv", "--per-task")
    assert capsys.readouterr().out.splitlines()[1:] == ["e,m,,py_a,python,1,1,1", "e,m,,py_b,python,1,0,0"]


@pytest.mark.parametrize("args", [["--format", "csv"], ["--format", "table"], ["--per-task"]])
def test_cli_summary_options_need_summary(monkeypatch, capsys, args):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "http://localhost:1/v1", *args)
    assert exc.value.code == 2
    assert "only with --summary" in capsys.readouterr().err


def test_cli_rejects_unknown_format(monkeypatch, tmp_path):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "--summary", str(tmp_path / "r.csv"), "--format", "html")
    assert exc.value.code == 2
