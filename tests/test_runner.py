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
    assert (tmp_path / "runs/test_model/py_t0/cfg/repeat_1/attempt_1/log.txt").read_text() == "[no code in reply]"


def test_colliding_model_ids_get_separate_transcripts(mock_server, tmp_path):
    s = mock_server(models=[".foo", "_foo"], replies=["", ""])
    run_endpoint(s, tmp_path, models=[".foo", "_foo"], tasks=TASKS[:1])
    dirs = sorted(p.name for p in (tmp_path / "runs").iterdir())
    assert len(dirs) == 2
    assert all(d.startswith("_foo-") for d in dirs)
    for d in dirs:
        assert (tmp_path / "runs" / d / "py_t0/cfg/repeat_1/attempt_1/response.md").is_file()


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
    assert (tmp_path / "runs/test_model/py_t0/cfg/repeat_2/attempt_1").is_dir()
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


def test_transcripts_of_other_configs_are_kept(mock_server, tmp_path):
    s = mock_server(replies=["first", "second"])
    run_endpoint(s, tmp_path, tasks=TASKS[:1])
    rows = run_endpoint(s, tmp_path, tasks=[{**TASKS[0], "config": "other"}])   # e.g. --attempts changed
    assert rows[0]["repeat"] == 1   # numbering restarts for the new config, but in its own directory
    for config, reply in (("cfg", "first"), ("other", "second")):
        response = tmp_path / f"runs/test_model/py_t0/{config}/repeat_1/attempt_1/response.md"
        assert response.read_text() == reply


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
    assert (g["n"], g["p1"], g["pass"], g["trials"]) == (2, 0.5, 1.0, [2, 2])   # py_a passed twice, once at attempt 1
    assert g["var1"] == pytest.approx(0.5)   # p=0.5 over 2 trials: 0.25 * 2/1
    assert (g["ct"], g["s"], g["load"]) == (10, 2.0, 2.0)   # means per round, summed over tasks


def test_summarize_keeps_newest_task_version_and_splits_settings():
    rows = [row("py_a", 0, config="old"), row("py_a", 1, config="new"), row("py_a", 1, settings="s2")]
    groups, dropped = llm_bench.summarize(rows)
    assert dropped == 1
    assert sorted((g["settings"], g["pass"]) for g in groups) == [("s1", 1.0), ("s2", 1.0)]


def test_summarize_scores_all_models_on_the_same_task_version():
    # Model a only has trials of py_a's old version; model b was re-run after the task changed.
    rows = [row("py_a", 1, model="a", config="old", run_id="20261101T000000Z"),
            row("py_b", 1, model="a", run_id="20261101T000000Z"),
            row("py_a", 0, model="b", config="old", run_id="20261101T000000Z"),
            row("py_a", 1, model="b", config="new", run_id="20261102T000000Z")]
    groups, dropped = llm_bench.summarize(rows)
    assert dropped == 2
    assert {g["model"]: (g["n"], g["pass"]) for g in groups} == {"a": (1, 1.0), "b": (1, 1.0)}


def test_summarize_newest_task_version_is_the_latest_run_not_the_last_row():
    # Results files can be passed in any order: the newest version is the one from the latest run.
    rows = [row("py_a", 1, model="a", config="new", run_id="20261102T000000Z"),
            row("py_a", 0, model="b", config="old", run_id="20261101T000000Z"),
            row("py_b", 1, model="b", run_id="20261101T000000Z")]
    groups, dropped = llm_bench.summarize(rows)
    assert dropped == 1
    assert {g["model"]: g["n"] for g in groups} == {"a": 1, "b": 1}   # b keeps only py_b


def test_newest_configs():
    rows = [row("py_a", 0, config="v2", run_id="20261102T000000.000Z"),
            row("py_a", 0, config="v1", run_id="20261101T000000.000Z"),   # older run, later row
            row("py_a", 0, config="v0"),                                    # old file without run_id
            row("py_b", 0, config="b1"), row("py_b", 0, config="b2"),       # no run_id: row order decides
            row("py_a", 0, config="s2", settings="s2")]
    assert llm_bench.newest_configs(rows) == {("s1", "py_a"): "v2", ("s1", "py_b"): "b2", ("s2", "py_a"): "s2"}


def test_newest_configs_ranks_whole_second_run_ids_first_within_their_second():
    rows = [row("py_a", 0, config="new", run_id="20261107T202918.123Z"),
            row("py_a", 0, config="old", run_id="20261107T202918Z")]   # older version wrote whole seconds
    assert llm_bench.newest_configs(rows) == {("s1", "py_a"): "new"}


def test_new_run_id_has_milliseconds():
    from datetime import UTC, datetime
    assert llm_bench.new_run_id(datetime(2026, 11, 7, 20, 29, 18, 123456, UTC)) == "20261107T202918.123Z"
    assert llm_bench.new_run_id(datetime(2026, 11, 7, 20, 29, 18, 999, UTC)) == "20261107T202918.000Z"


def test_summarize_omits_models_without_current_trials():
    rows = [row("py_a", 1, model="a", config="old", run_id="1"), row("py_a", 1, model="b", config="new", run_id="2")]
    groups, dropped = llm_bench.summarize(rows)
    assert (dropped, [g["model"] for g in groups]) == (1, ["b"])


def test_print_summary_with_repeats(capsys):
    llm_bench.print_summary([row("py_a", 1), row("py_a", 0), row("py_b", 1), row("py_b", 1)])
    out = capsys.readouterr().out
    assert "1.5±0.7/2" in out
    assert "rounds" in out
    assert "mean passes per round" in out


def test_print_summary_warns_about_different_task_sets(capsys):
    llm_bench.print_summary([row("py_a", 1, model="a"), row("py_b", 1, model="a"), row("py_a", 1, model="b"),
                             row("py_c", 1, model="c"), row("py_a", 1, model="d", settings="s2")])
    out = capsys.readouterr().out
    assert ("warning: models with the same settings were scored on different tasks, so their scores aren't "
            "comparable: e/a [s1] (missing py_c), e/b [s1] (missing py_b, py_c), e/c [s1] (missing py_a, py_b)") in out


def test_print_summary_warnings_name_the_settings_when_they_differ(capsys):
    llm_bench.print_summary([row("py_a", 1), row("py_a", 1, settings="s2", context="short:4000"),
                             row("py_b", 1, settings="s2", model="n")])
    out = capsys.readouterr().out
    assert "comparable: e/m [s2] (missing py_b), e/n [s2] (missing py_a)" in out
    assert "results may be cut off: e/m [s2] (short:4000)" in out


def test_print_summary_no_task_set_warning_when_tasks_match(capsys):
    llm_bench.print_summary([row("py_a", 1, model="a"), row("py_a", 0, model="b")])
    assert "different tasks" not in capsys.readouterr().out


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


def usage_reply(text="", **usage):
    return Reply(body=json.dumps({"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                                  "usage": {"prompt_tokens": 10, "completion_tokens": 5, **usage}}).encode())


def test_reasoning_tokens_are_summed_over_attempts(mock_server, tmp_path):
    s = mock_server(replies=[usage_reply(completion_tokens_details={"reasoning_tokens": 7}),
                             usage_reply(completion_tokens_details={"reasoning_tokens": 3})])
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1], attempts=2)
    assert row["reasoning_tokens"] == 10
    assert read_csv(tmp_path / "results.csv")[0]["reasoning_tokens"] == "10"


@pytest.mark.parametrize("usage", [
    {},                                                       # not reported
    {"completion_tokens_details": None},
    {"completion_tokens_details": "lots"},                    # malformed: ignored, not a bad response
    {"completion_tokens_details": {"reasoning_tokens": "7"}},
    {"completion_tokens_details": {"reasoning_tokens": True}},
])
def test_reasoning_tokens_empty_when_not_reported(mock_server, tmp_path, usage):
    s = mock_server(replies=[usage_reply(**usage)])
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1])
    assert (row["finish_reason"], row["reasoning_tokens"]) == ("stop", None)
    assert read_csv(tmp_path / "results.csv")[0]["reasoning_tokens"] == ""


def test_reasoning_tokens_count_attempts_that_report_them(mock_server, tmp_path):
    s = mock_server(replies=[usage_reply(), usage_reply(completion_tokens_details={"reasoning_tokens": 4})])
    (row,) = run_endpoint(s, tmp_path, tasks=TASKS[:1], attempts=2)
    assert row["reasoning_tokens"] == 4


def test_skipped_trials_have_no_reasoning_tokens(mock_server, tmp_path):
    s = mock_server(replies=[Reply(status=500, body=b"{}")] * 3)
    rows = run_endpoint(s, tmp_path)
    assert {r["reasoning_tokens"] for r in rows} == {None}


def test_read_results_reasoning_tokens(tmp_path):
    path = tmp_path / "r.csv"
    path.write_text("endpoint,model,task,lang,passed,passed_on,reasoning_tokens\n"
                    "e,m,py_a,python,1,1,12\ne,m,py_b,python,1,1,\n")
    assert [r["reasoning_tokens"] for r in llm_bench.read_results(path)] == [12, None]


def test_check_results_file_upgrades_older_columns(tmp_path, capsys):
    old = [f for f in llm_bench.FIELDS if f != "reasoning_tokens"]
    path = tmp_path / "results.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old)
        w.writeheader()
        w.writerow({k: "" for k in old} | {"endpoint": "e", "model": "m", "task": "py_a", "lang": "python",
                                           "passed": "1", "passed_on": "1", "completion_tokens": "5"})
    llm_bench.check_results_file(path)
    assert path.read_text().splitlines()[0] == ",".join(llm_bench.FIELDS)
    (r,) = read_csv(path)
    assert (r["model"], r["completion_tokens"], r["reasoning_tokens"]) == ("m", "5", "")
    assert "upgraded" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == [path]   # no temp file left behind


def test_check_results_file_refuses_unreadable_old_file(tmp_path):
    path = tmp_path / "results.csv"
    path.write_text("endpoint,model,task\ne,m,py_a\n")   # known columns, but not a results file
    with pytest.raises(SystemExit, match="cannot read"):
        llm_bench.check_results_file(path)
    assert path.read_text() == "endpoint,model,task\ne,m,py_a\n"


def test_summarize_throughput_counts_only_trials_with_a_reply():
    rows = [row("py_a", 1, completion_tokens=100, seconds=10.0),
            row("py_b", 0, completion_tokens=50, seconds=5.0, finish_reason="oversized"),   # a reply, just too long
            row("py_c", 0, completion_tokens=0, seconds=30.0, finish_reason="timeout"),
            row("py_d", 0, completion_tokens=0, seconds=2.0, finish_reason="http_500"),
            row("py_e", 0, completion_tokens=0, seconds=0.0, finish_reason="skipped")]
    (g,) = llm_bench.summarize(rows)[0]
    assert g["tps"] == pytest.approx(10.0)   # 150 tokens in 15 s


def test_summarize_throughput_unknown_without_replies():
    (g,) = llm_bench.summarize([row("py_a", 0, completion_tokens=0, seconds=30.0, finish_reason="timeout")])[0]
    assert g["tps"] is None


def test_summarize_reasoning_tokens_mean_per_round():
    rows = [row("py_a", 1, reasoning_tokens=20), row("py_a", 1, reasoning_tokens=10),
            row("py_b", 1, reasoning_tokens=4), row("py_b", 1, reasoning_tokens=None),
            row("py_a", 1, model="n", reasoning_tokens=None)]
    groups = {g["model"]: g for g in llm_bench.summarize(rows)[0]}
    assert groups["m"]["rt"] == pytest.approx(19.0)   # py_a: mean 15, py_b: mean of the reported trials, 4
    assert groups["n"]["rt"] is None


def test_summarize_per_task_counts():
    rows = [row("py_a", 1), row("py_a", 2), row("py_a", 0), row("go_b", 0, lang="go")]
    (g,) = llm_bench.summarize(rows)[0]
    assert g["per_task"] == {"py_a": {"lang": "python", "trials": 3, "passed": 2, "passed_on_first": 1},
                             "go_b": {"lang": "go", "trials": 1, "passed": 0, "passed_on_first": 0}}


def test_print_summary_table_shows_throughput(capsys):
    llm_bench.print_summary([row("py_a", 1, completion_tokens=100, seconds=4.0)])
    head, line = capsys.readouterr().out.strip().splitlines()[:2]
    assert "tok/s" in head.split()
    assert "reason_tok" not in head   # no row reports reasoning tokens
    assert line.split()[-2:] == ["25.0", "2.0"]   # tok/s, load


def test_print_summary_table_shows_reasoning_tokens_when_reported(capsys):
    llm_bench.print_summary([row("py_a", 1, model="a", reasoning_tokens=40), row("py_a", 1, model="b")])
    lines = capsys.readouterr().out.strip().splitlines()
    cells = {line.split()[1]: line.split() for line in lines[1:3]}
    reason = lines[0].split().index("reason_tok")
    assert (cells["a"][reason], cells["b"][reason]) == ("40", "-")


def test_print_summary_markdown(capsys):
    llm_bench.print_summary([row("py_a", 1, config="old"), row("py_a", 1)], fmt="markdown")
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("| endpoint | model | pass@1 | passed | python |")
    assert lines[1].startswith("| --- | --- | ---: | ---: | ---: |")
    assert lines[2].startswith("| e | m | 1/1 | 1/1 | 1/1 |")
    assert "row(s) from older versions" in lines[-1]   # notes follow the table as paragraphs
    assert lines[3] == ""


def test_print_summary_markdown_escapes_pipes(capsys):
    llm_bench.print_summary([row("py_a", 1, model="org|model")], fmt="markdown")
    assert "| org\\|model |" in capsys.readouterr().out


def test_print_summary_csv(capsys):
    rows = [row("go_b", 0, lang="go", completion_tokens=900, seconds=2.0, config="old"),   # left out
            row("py_a", 1, completion_tokens=100, seconds=4.0, reasoning_tokens=30),
            row("py_a", 0, completion_tokens=100, seconds=4.0, reasoning_tokens=10),
            row("go_b", 1, lang="go", completion_tokens=100, seconds=2.0)]
    llm_bench.print_summary(rows, fmt="csv")
    out, err = capsys.readouterr()
    (rec,) = csv.DictReader(out.splitlines())
    assert rec == {"endpoint": "e", "model": "m", "settings": "s1", "tasks": "2", "rounds_min": "1",
                   "rounds_max": "2", "pass1": "1.5", "pass1_sd": "0.707", "passed": "1.5", "passed_sd": "0.707",
                   "python": "0.5", "python_tasks": "1", "go": "1.0", "go_tasks": "1", "prompt_tokens": "20.0",
                   "completion_tokens": "200.0", "reasoning_tokens": "20.0", "seconds": "6.0",
                   "tok_per_s": "30.0", "load_seconds": "2.0"}
    assert "row(s) from older versions" in err   # notes go to stderr, so stdout stays a CSV file


def test_print_summary_csv_single_round_has_no_spread(capsys):
    llm_bench.print_summary([row("py_a", 0, completion_tokens=0, finish_reason="timeout")], fmt="csv")
    (rec,) = csv.DictReader(capsys.readouterr().out.splitlines())
    assert (rec["pass1_sd"], rec["passed_sd"], rec["reasoning_tokens"], rec["tok_per_s"]) == ("", "", "", "")


PER_TASK_ROWS = [row("py_a", 1, model="a"), row("py_a", 0, model="a"), row("go_b", 2, lang="go", model="a"),
                 row("py_a", 1, model="b")]


def test_print_summary_per_task_table(capsys):
    llm_bench.print_summary(PER_TASK_ROWS, per_task=True)
    out = capsys.readouterr().out
    lines = out[out.index("\ntask"):].strip().splitlines()
    assert lines[0].split() == ["task", "e/a", "e/b"]   # models in the summary's order
    assert lines[1].split() == ["py_a", "1/2", "1/1"]   # tasks in language order
    assert lines[2].split() == ["go_b", "1/1", "-"]


def test_print_summary_per_task_markdown(capsys):
    llm_bench.print_summary(PER_TASK_ROWS, fmt="markdown", per_task=True)
    out = capsys.readouterr().out
    assert "| task | e/a | e/b |\n| --- | ---: | ---: |\n| py_a | 1/2 | 1/1 |\n| go_b | 1/1 | - |" in out


def test_print_summary_per_task_csv(capsys):
    llm_bench.print_summary(PER_TASK_ROWS, fmt="csv", per_task=True)
    recs = list(csv.DictReader(capsys.readouterr().out.splitlines()))
    assert [(r["model"], r["task"], r["lang"], r["trials"], r["passed"], r["passed_on_first"]) for r in recs] == [
        ("a", "py_a", "python", "2", "1", "1"), ("a", "go_b", "go", "1", "1", "0"),
        ("b", "py_a", "python", "1", "1", "1")]
    assert list(recs[0]) == ["endpoint", "model", "settings", "task", "lang", "trials", "passed", "passed_on_first"]


def test_print_summary_no_results_csv(capsys):
    llm_bench.print_summary([], fmt="csv")
    out, err = capsys.readouterr()
    assert (out, err.strip()) == ("", "no results")
