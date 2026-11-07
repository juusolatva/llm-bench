import sys
from collections import Counter

import pytest

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


def test_extract_code_takes_last_block_and_strips_think():
    text = "<think>```python\nbad\n```</think>intro\n```python\nfirst\n```\nthen\n```c\nlast\n```"
    assert llm_bench.extract_code(text) == "last\n"


def test_extract_code_without_fence_returns_text():
    assert llm_bench.extract_code("<think>x</think>plain") == "plain"


def test_clip_keeps_head_and_tail():
    text = "H" * 100 + "T" * 100
    out = llm_bench.clip(text, limit=30)
    assert out.startswith("H" * 20) and out.endswith("T" * 10) and "truncated" in out
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


BUILTIN_TASKS = llm_bench.load_tasks([llm_bench.DEFAULT_TASKS_DIR])


def test_builtin_tasks_are_consistent():
    names = [t["name"] for t in BUILTIN_TASKS]
    assert len(names) == len(set(names))
    for t in BUILTIN_TASKS:
        assert t["name"].startswith(llm_bench.LANGS[t["lang"]]["prefix"] + "_")
        assert t["prompt"] and t["test"].strip()
    per_lang = Counter(t["lang"] for t in BUILTIN_TASKS)
    assert set(per_lang) == set(llm_bench.LANGS)
    assert all(n == 4 for n in per_lang.values())
    assert all(sum(t["lang"] == lang and "_fix_" in t["name"] for t in BUILTIN_TASKS) == 1
               for lang in llm_bench.LANGS)


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


def test_list_models_unreachable(capsys):
    assert llm_bench.list_models("dead", "http://127.0.0.1:9/v1", None) == []
    assert "dead: skipping" in capsys.readouterr().err


def test_print_summary(capsys):
    rows = [
        {"endpoint": "a-long-endpoint-name", "model": "m1", "lang": "python", "passed": 1, "passed_on": 1,
         "prompt_tokens": 10, "completion_tokens": 5, "seconds": 1.0},
        {"endpoint": "a-long-endpoint-name", "model": "m1", "lang": "go", "passed": 0, "passed_on": 0,
         "prompt_tokens": 10, "completion_tokens": 5, "seconds": 1.0},
    ]
    llm_bench.print_summary(rows, 3)
    out = capsys.readouterr().out
    assert "pass@3" in out and "python" in out and "go" in out
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
    assert len(lines) == 4 and all(line.startswith("rust_") for line in lines)


def test_cli_tasks_dir(monkeypatch, capsys, tmp_path):
    make_task(tmp_path, "python", "mine")
    run_main(monkeypatch, "--list-tasks", "--tasks-dir", str(tmp_path))
    assert capsys.readouterr().out.split() == ["py_mine", "python"]
    run_main(monkeypatch, "--list-tasks", "--tasks-dir", str(tmp_path),
             "--tasks-dir", str(llm_bench.DEFAULT_TASKS_DIR))
    assert len(capsys.readouterr().out.splitlines()) == 25


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
