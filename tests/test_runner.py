"""Request handling and the per-endpoint loop. No sandbox needed: no reply here contains code to run."""
import csv
import json
import socket
import threading
from types import SimpleNamespace

import pytest
from conftest import Reply

import llm_bench


def opts(**kwargs):
    defaults = {"timeout": 30, "api_key": None, "attempts": 1, "max_tokens": 100, "params": {},
                "context_check": True, "run_id": "test-run", "settings_hash": "set", "repeat": 1, "resume": False,
                "max_length_finishes": None}
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
    url, options, stop = f"http://127.0.0.1:{free_port()}/v1", opts(), threading.Event()
    with pytest.raises(llm_bench.ServerDown):
        llm_bench.chat("label", url, {}, options, stop)
    assert capsys.readouterr().err.count("retrying in 0s") == 2


def test_chat_server_down_interrupted(monkeypatch):
    monkeypatch.setattr(llm_bench, "SERVER_RETRY_DELAYS_S", (60,))
    stop = threading.Event()
    stop.set()
    url, options = f"http://127.0.0.1:{free_port()}/v1", opts()
    with pytest.raises(llm_bench.Interrupted):
        llm_bench.chat("label", url, {}, options, stop)


TASKS = [{"name": f"py_t{i}", "lang": "python", "prompt": f"task {i}", "test": "", "config": "cfg"}
         for i in range(5)]


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
    assert (tmp_path / "runs/test_model/py_t0/repeat_1/attempt_1/log.txt").read_text() == "[no code in reply]"


def test_results_are_appended(mock_server, tmp_path):
    s = mock_server(replies=["", ""])
    run_endpoint(s, tmp_path, tasks=TASKS[:1])
    run_endpoint(s, tmp_path, tasks=TASKS[1:2])
    lines = (tmp_path / "results.csv").read_text().splitlines()
    assert lines[0] == ",".join(llm_bench.FIELDS)
    assert len(lines) == 3
    assert [r["task"] for r in read_csv(tmp_path / "results.csv")] == ["py_t0", "py_t1"]


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


@pytest.mark.parametrize(("server", "options", "context"), [
    ({}, {}, "ok"),
    ({}, {"max_tokens": 5000}, "ok"),
    ({"context": 500}, {}, "short:500"),                         # server truncates prompts to its context
    ({"context": 3000}, {"max_tokens": 5000}, "short:3000"),
    ({"reject_over": 800}, {}, "rejected:http_400"),              # even the calibration prompt is refused
    ({"reject_over": 3000}, {"max_tokens": 5000}, "rejected:http_400"),   # only the full-size prompt is refused
    ({"probe_reply": Reply(body=b'{"choices": [{"message": {"content": "OK"}}]}')}, {}, "unchecked"),  # no usage
])
def test_context_check(mock_server, tmp_path, server, options, context):
    s = mock_server(replies=[""], **server)
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1], **options)
    assert row["context"] == context
    assert row["finish_reason"] == "stop"   # the task still runs
    if context == "ok":
        need = llm_bench.context_needed(opts(**options))
        assert len(s.probes) == 3
        assert 10 + len(s.probes[2]["messages"][0]["content"].split()) >= 0.99 * need   # mock: 1 token per word


def test_context_check_disabled(mock_server, tmp_path):
    s = mock_server(replies=[""], context=500)
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1], context_check=False)
    assert row["context"] == "unchecked"
    assert len(s.probes) == 1


def test_load_failure_skips_model(mock_server, tmp_path):
    s = mock_server(models=["a", "b"], probe_reply=Reply(status=500, body=b'{"error": "out of memory"}'))
    rows = run_endpoint(s, tmp_path, models=["a", "b"], tasks=TASKS[:2])
    assert [(r["model"], r["finish_reason"], r["fail_stage"]) for r in rows] == [
        ("a", "http_500", "load"), ("a", "http_500", "load"), ("b", "http_500", "load"), ("b", "http_500", "load")]
    assert s.requests == []   # no task was sent


def test_load_time_is_separate_from_task_time(mock_server, tmp_path):
    s = mock_server(replies=[""], probe_reply=Reply(text="OK", sleep=1))
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1])
    assert row["load_seconds"] >= 1
    assert row["seconds"] < 1


def test_params_metadata_and_config_in_rows(mock_server, tmp_path):
    s = mock_server(replies=[""])
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1], params={"top_p": 0.5, "seed": 1})
    assert s.requests[0]["top_p"] == 0.5
    assert s.probes[0]["seed"] == 1
    assert (row["params"], row["run_id"], row["config"]) == ('{"seed":1,"top_p":0.5}', "test-run", "cfg")
    (csv_row,) = read_csv(tmp_path / "results.csv")
    assert list(csv_row) == llm_bench.FIELDS


def test_config_hash():
    task = {"name": "py_x", "lang": "python", "prompt": "p", "test": "t"}
    base = {"timeout": 1800, "max_tokens": 100, "attempts": 3}
    settings = llm_bench.settings_fingerprint(opts(**base))
    h = llm_bench.config_hash(settings, task)
    assert len(h) == 12
    assert h == llm_bench.config_hash(settings, dict(task))
    assert h != llm_bench.config_hash(settings, {**task, "prompt": "p2"})
    assert h != llm_bench.config_hash(settings, {**task, "test": "t2"})
    for change in ({"max_tokens": 101}, {"attempts": 2}, {"params": {"seed": 1}}):
        other = llm_bench.settings_fingerprint(opts(**{**base, **change}))
        assert h != llm_bench.config_hash(other, task)


def test_repeat_runs_each_task_k_times_repeat_major(mock_server, tmp_path):
    s = mock_server(replies=[""] * 4)
    rows = run_endpoint(s, tmp_path, tasks=TASKS[:2], repeat=2)
    assert [(r["task"], r["repeat"]) for r in rows] == [("py_t0", 1), ("py_t1", 1), ("py_t0", 2), ("py_t1", 2)]
    assert (tmp_path / "runs/test_model/py_t0/repeat_2/attempt_1").is_dir()
    assert len(s.probes) == 3   # one warm-up and context check per model, not per repeat


def test_repeat_numbers_continue_across_runs(mock_server, tmp_path):
    s = mock_server(replies=[""] * 2)
    run_endpoint(s, tmp_path, tasks=TASKS[:1])
    run_endpoint(s, tmp_path, tasks=TASKS[:1])
    assert [r["repeat"] for r in llm_bench.read_results(tmp_path / "results.csv")] == [1, 2]


def test_resume_skips_finished_and_retries_request_errors(mock_server, tmp_path):
    err = Reply(status=500, body=b"{}")
    s = mock_server(replies=["", err, ""])
    run_endpoint(s, tmp_path, tasks=TASKS[:2])          # t0 finishes, t1 gets http_500
    rows = run_endpoint(s, tmp_path, tasks=TASKS[:2], resume=True)
    assert [(r["task"], r["repeat"], r["finish_reason"]) for r in rows] == [("py_t1", 2, "stop")]
    rows = run_endpoint(s, tmp_path, tasks=TASKS[:2], resume=True)
    assert rows == []
    assert len(s.requests) == 3           # nothing left: not even a warm-up


def test_resume_with_repeat_tops_up(mock_server, tmp_path):
    s = mock_server(replies=[""] * 3)
    run_endpoint(s, tmp_path, tasks=TASKS[:1])
    rows = run_endpoint(s, tmp_path, tasks=TASKS[:1], repeat=3, resume=True)
    assert [r["repeat"] for r in rows] == [2, 3]


def test_resume_ignores_rows_with_other_config(mock_server, tmp_path):
    s = mock_server(replies=[""] * 2)
    run_endpoint(s, tmp_path, tasks=TASKS[:1])
    changed = [{**TASKS[0], "config": "other"}]          # e.g. the prompt changed
    assert len(run_endpoint(s, tmp_path, tasks=changed, resume=True)) == 1


def test_length_budget_skips_rest_of_model(mock_server, tmp_path):
    long = Reply(body=json.dumps({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}).encode())
    s = mock_server(models=["a", "b"], replies=[long, long, long, long])
    rows = run_endpoint(s, tmp_path, models=["a", "b"], tasks=TASKS[:3], max_length_finishes=2)
    assert [(r["model"], r["finish_reason"], r["fail_stage"]) for r in rows] == [
        ("a", "length", "no_code"), ("a", "length", "no_code"), ("a", "skipped", "budget"),
        ("b", "length", "no_code"), ("b", "length", "no_code"), ("b", "skipped", "budget")]


def row(task, passed_on, **extra):
    return {"endpoint": "e", "model": "m", "task": task, "lang": "python", "passed": int(passed_on > 0),
            "passed_on": passed_on, "prompt_tokens": 10, "completion_tokens": 5, "seconds": 1.0,
            "load_seconds": 2.0, "settings": "s1", "config": "c1", "context": "ok", **extra}


def test_summarize_repeats():
    rows = [row("py_a", 1), row("py_a", 2), row("py_b", 0), row("py_b", 0)]
    (g,) = llm_bench.summarize(rows)[0]
    assert (g["n"], g["p1"], g["pass"], g["runs"]) == (2, 0.5, 1.0, [2, 2])   # py_a passed twice, once at attempt 1
    assert g["var1"] == pytest.approx(0.5)   # p=0.5 over 2 runs: 0.25 * 2/1
    assert (g["ct"], g["s"], g["load"]) == (10, 2.0, 2.0)   # means per run, summed over tasks


def test_summarize_keeps_newest_task_version_and_splits_settings():
    rows = [row("py_a", 0, config="old"), row("py_a", 1, config="new"), row("py_a", 1, settings="s2")]
    groups, dropped = llm_bench.summarize(rows)
    assert dropped == 1
    assert sorted((g["settings"], g["pass"]) for g in groups) == [("s1", 1.0), ("s2", 1.0)]


def test_print_summary_with_repeats(capsys):
    llm_bench.print_summary([row("py_a", 1), row("py_a", 0), row("py_b", 1), row("py_b", 1)])
    out = capsys.readouterr().out
    assert "1.5±0.7/2" in out
    assert "runs" in out
    assert "mean passes per run" in out


def test_read_results_accepts_old_files(tmp_path):
    path = tmp_path / "old.csv"
    path.write_text("backend,model,task,lang,passed,passed_on,attempts,prompt_tokens,completion_tokens,seconds,"
                    "finish_reason\nollama,m,py_a,python,1,2,2,10,5,1.5,stop\n")
    (r,) = llm_bench.read_results(path)
    assert (r["endpoint"], r["repeat"], r["passed_on"], r["seconds"], r["config"]) == ("ollama", 1, 2, 1.5, "")


def test_read_results_rejects_other_csv(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="not a results file"):
        llm_bench.read_results(path)
