"""Reference solutions: every built-in task has one, and it passes the task's harness in the real sandbox.

This catches broken or over-strict harnesses, which otherwise only show up as models failing."""
import tempfile

import pytest

import llm_bench

TASKS = llm_bench.load_tasks([llm_bench.DEFAULT_TASKS_DIR])


def reference_file(task):
    """tasks/<lang>/<task>/reference/<solution file> for a built-in task."""
    lang = llm_bench.LANGS[task["lang"]]
    directory = task["name"].removeprefix(lang["prefix"] + "_")
    return llm_bench.DEFAULT_TASKS_DIR / task["lang"] / directory / "reference" / lang["sol"]


@pytest.mark.parametrize("task", TASKS, ids=[t["name"] for t in TASKS])
def test_reference_exists(task):
    """Every built-in task has a non-empty reference solution."""
    path = reference_file(task)
    assert path.is_file(), f"missing reference solution {path}"
    assert path.read_text().strip()


@pytest.fixture(scope="session")
def go_cache():
    """Warm the Go build cache once, like a real run does, so Go tasks stay under the time limit."""
    with tempfile.TemporaryDirectory(prefix="llm-bench-test-go-") as d:
        llm_bench.prepare_go_cache(d)
        if llm_bench.GO_CACHE is None:
            pytest.fail("warming the Go build cache failed (see the warning above); without it Go tasks "
                        "compile the standard library each time and hit the time limit")
        yield
        llm_bench.GO_CACHE = None


@pytest.mark.sandbox
@pytest.mark.parametrize("task", TASKS, ids=[t["name"] for t in TASKS])
def test_reference_passes(task, tmp_path, request):
    """The reference solution passes the task's harness in the sandbox (skipped without its toolchain)."""
    try:
        llm_bench.check_toolchains([task])
    except SystemExit as exc:
        pytest.skip(str(exc))
    if task["lang"] == "go":
        request.getfixturevalue("go_cache")
    passed, _, stage, cmd, out = llm_bench.run_task(task, reference_file(task).read_text(), tmp_path / "work")
    assert passed, f"{task['name']}: reference failed at {stage} ({cmd}):\n{out}"
