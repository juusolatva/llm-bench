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


def test_tasks_are_consistent():
    names = [t["name"] for t in llm_bench.TASKS]
    assert len(names) == len(set(names))
    prefixes = {"python": "py_", "c": "c_", "cpp": "cpp_", "rust": "rust_", "go": "go_", "bash": "bash_"}
    for t in llm_bench.TASKS:
        assert t["lang"] in llm_bench.LANGS
        assert t["name"].startswith(prefixes[t["lang"]])
        assert t["prompt"].strip() and t["test"].strip()
    per_lang = Counter(t["lang"] for t in llm_bench.TASKS)
    assert set(per_lang) == set(llm_bench.LANGS)
    assert all(n == 4 for n in per_lang.values())
    assert all(sum(t["lang"] == lang and "_fix_" in t["name"] for t in llm_bench.TASKS) == 1
               for lang in llm_bench.LANGS)


def test_http_json_sends_api_key(mock_server):
    s = mock_server(api_key="sekrit")
    assert llm_bench.list_models("m", s.url, "sekrit") == ["test/model"]
    assert llm_bench.list_models("m", s.url, "wrong") == []   # 401 is reported and skipped


def test_http_json_enforces_size_cap(mock_server, monkeypatch):
    s = mock_server(models=["x" * 1000])
    monkeypatch.setattr(llm_bench, "MAX_RESPONSE_BYTES", 100)
    with pytest.raises(OSError, match="exceeds"):
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
    assert "c " not in out.splitlines()[1]   # only languages that were run get a column
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


def test_cli_rejects_duplicate_endpoint_names(monkeypatch):
    with pytest.raises(SystemExit, match="duplicate"):
        run_main(monkeypatch, "a=h1:1", "a=h2:2")


@pytest.mark.parametrize("arg", ["--attempts=0", "--timeout=-1", "--max-tokens=x"])
def test_cli_rejects_bad_numbers(monkeypatch, arg):
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, "localhost:1", arg)
    assert exc.value.code == 2
