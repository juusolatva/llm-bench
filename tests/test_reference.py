"""Reference solutions: every built-in task has one, and it passes the task's harness in the real sandbox.

This catches broken or over-strict harnesses, which otherwise only show up as models failing."""
import pytest

import llm_bench

TASKS = llm_bench.load_tasks([llm_bench.DEFAULT_TASKS_DIR])
GO_TASKS = [t for t in TASKS if t["lang"] == "go"]
OTHER_TASKS = [t for t in TASKS if t["lang"] != "go"]


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


def check_reference(task, tmp_path):
    """Run the task's reference solution in the sandbox and expect it to pass (skip without its toolchain)."""
    try:
        llm_bench.check_toolchains([task])
    except SystemExit as exc:
        pytest.skip(str(exc))
    passed, _, stage, cmd, out = llm_bench.run_task(task, reference_file(task).read_text(), tmp_path / "work")
    assert passed, f"{task['name']}: reference failed at {stage} ({cmd}):\n{out}"


@pytest.mark.sandbox
@pytest.mark.parametrize("task", OTHER_TASKS, ids=[t["name"] for t in OTHER_TASKS])
def test_reference_passes(task, tmp_path):
    """The reference solution passes the task's harness in the sandbox."""
    check_reference(task, tmp_path)


@pytest.mark.sandbox
@pytest.mark.parametrize("task", GO_TASKS, ids=[t["name"] for t in GO_TASKS])
def test_go_reference_passes(task, tmp_path, go_cache):
    """Like test_reference_passes, for Go tasks, which need the warmed build cache."""
    check_reference(task, tmp_path)
