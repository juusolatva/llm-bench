"""Request handling and the per-endpoint loop. No sandbox needed: no reply here contains code to run."""
import csv
import socket
import threading
from types import SimpleNamespace

import pytest
from conftest import Reply

import llm_bench


def opts(**kwargs):
    defaults = {"timeout": 30, "api_key": None, "attempts": 1, "max_tokens": 100, "temperature": None}
    return SimpleNamespace(**{**defaults, **kwargs})


def chat(server, **kwargs):
    payload = {"model": "test/model", "messages": []}
    return llm_bench.chat("label", server.url, payload, opts(**kwargs), threading.Event())


@pytest.mark.parametrize(("reply", "error"), [
    (Reply(status=500, body=b'{"error": "model crashed"}'), "http_500"),
    (Reply(status=400, body=b'{"error": "context length exceeded"}'), "http_400"),
    (Reply(body=b"not json"), "bad_response"),
    (Reply(body=b'{"error": "no choices"}'), "bad_response"),
    (Reply(body=b'{"choices": []}'), "bad_response"),
    (Reply(body=b'{"choices": [{"message": {"content": 5}}]}'), "bad_response"),
    (Reply(body=b'{"choices": [{"message": {"content": "x"}}], "usage": 3}'), "bad_response"),
    (Reply(body=b'{"choices":', length=1000), "bad_response"),   # body cut off
    (Reply(close=True), "disconnected"),                          # server still answers /models
])
def test_chat_classifies_failures(mock_server, reply, error):
    s = mock_server(replies=[reply])
    assert chat(s) == ("", None, {}, error)


def test_chat_timeout(mock_server):
    s = mock_server(replies=[Reply(text="late", sleep=3)])
    assert chat(s, timeout=1)[3] == "timeout"


def test_chat_success(mock_server):
    s = mock_server(replies=["hello"])
    assert chat(s) == ("hello", "stop", {"prompt_tokens": 10, "completion_tokens": 5}, None)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_chat_server_down_retries_then_gives_up(monkeypatch, capsys):
    monkeypatch.setattr(llm_bench, "SERVER_RETRY_DELAYS_S", (0, 0))
    url = f"http://127.0.0.1:{free_port()}/v1"
    with pytest.raises(llm_bench.ServerDown):
        llm_bench.chat("label", url, {}, opts(), threading.Event())
    assert capsys.readouterr().err.count("retrying in 0s") == 2


def test_chat_server_down_interrupted(monkeypatch):
    monkeypatch.setattr(llm_bench, "SERVER_RETRY_DELAYS_S", (60,))
    stop = threading.Event()
    stop.set()
    with pytest.raises(llm_bench.Interrupted):
        llm_bench.chat("label", f"http://127.0.0.1:{free_port()}/v1", {}, opts(), stop)


TASKS = [{"name": f"py_t{i}", "lang": "python", "prompt": f"task {i}", "test": ""} for i in range(5)]


def run_endpoint(server, tmp_path, models=("test/model",), tasks=TASKS, **kwargs):
    rows = []
    llm_bench.run_endpoint("m", server.url, list(models), tasks, opts(**kwargs), tmp_path / "results.csv",
                           tmp_path / "runs", rows, threading.Event())
    return rows


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_model_errors_skip_rest_of_model_only(mock_server, tmp_path):
    s = mock_server(models=["a", "b"], replies=[Reply(status=500, body=b"{}")] * 6)
    rows = run_endpoint(s, tmp_path, models=["a", "b"])
    for model in ("a", "b"):   # the next model still runs: the server is fine, the model isn't
        finishes = [r["finish_reason"] for r in rows if r["model"] == model]
        assert finishes == ["http_500"] * 3 + ["skipped"] * 2
    assert len(s.requests) == 6
    assert len(read_csv(tmp_path / "results.csv")) == 10   # every task has a row, so x/N stays honest
    assert {r["fail_stage"] for r in rows} == {"request"}


def test_model_error_streak_resets_on_success(mock_server, tmp_path):
    err = Reply(status=500, body=b"{}")
    s = mock_server(replies=[err, err, "no code here", err, err])
    finishes = [r["finish_reason"] for r in run_endpoint(s, tmp_path)]
    assert finishes == ["http_500", "http_500", "stop", "http_500", "http_500"]


def test_no_code_reply(mock_server, tmp_path):
    s = mock_server(replies=["", "   "])
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1], attempts=2)
    assert (row["passed"], row["attempts"], row["fail_stage"]) == (0, 2, "no_code")
    assert "did not contain any code" in s.requests[1]["messages"][-1]["content"]
    assert (tmp_path / "runs/test_model/py_t0/attempt_1/log.txt").read_text() == "[no code in reply]"


def test_results_are_appended(mock_server, tmp_path):
    s = mock_server(replies=["", ""])
    run_endpoint(s, tmp_path, tasks=TASKS[:1])
    run_endpoint(s, tmp_path, tasks=TASKS[1:2])
    lines = (tmp_path / "results.csv").read_text().splitlines()
    assert lines[0] == ",".join(llm_bench.FIELDS)
    assert len(lines) == 3 and [r["task"] for r in read_csv(tmp_path / "results.csv")] == ["py_t0", "py_t1"]


def test_check_results_file(tmp_path):
    path = tmp_path / "results.csv"
    llm_bench.check_results_file(path)                     # missing: fine
    path.write_text(",".join(llm_bench.FIELDS) + "\n")
    llm_bench.check_results_file(path)                     # same columns: fine
    path.write_text("backend,model,task\n")
    with pytest.raises(SystemExit, match="different columns"):
        llm_bench.check_results_file(path)


def test_feedback_messages():
    assert "Output of `./t`" in llm_bench.feedback("test", "./t", "boom")
    assert "time limit" in llm_bench.feedback("time_limit", "./t", "")
    assert "did not contain any code" in llm_bench.feedback("no_code", None, None)
