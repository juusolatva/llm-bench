# AGENTS.md

Guidance for coding agents working in this repository.

## Overview

`llm_bench.py` is a standard-library-only Python script, and `tasks/` holds the benchmark tasks it loads at startup. It benchmarks LLMs served over an OpenAI-compatible API on coding tasks and builds and tests the generated code in a sandbox. See `README.md` for user-facing documentation; keep it in sync when you change options, output formats, requirements or tasks.

Repository layout:

- `llm_bench.py`, top to bottom:
  1. **Configuration**: defaults for CLI options, sandbox limits, the system prompt, and `LANGS` (per language: task name prefix, solution and harness file names, build/test commands).
  2. **Task loading**: `load_tasks()` reads task directories (layout below).
  3. **Runner**: HTTP client, endpoint parsing, sandbox (`run_cmd`), task execution, the per-endpoint loop (`run_endpoint`), summary, CLI.
- `tasks/<lang>/<task>/`: one directory per task, where `<lang>` is a `LANGS` key:
  - `prompt.md`: sent to the model verbatim (surrounding whitespace trimmed).
  - The hidden harness, named `LANGS[lang]["test"]` (`test_solution.py`, `test.c`, `test.cpp`, `test.rs`, `solution_test.go`, `test.sh`). Rust harnesses are appended to the solution file, not written separately.
  - `reference/<solution file>`: a known-correct solution named like `LANGS[lang]["sol"]` (`solution.py`, …, `lib.rs` for Rust). Never sent to models; `tests/test_reference.py` runs it through the sandbox.
  - Other files are ignored by the loader.
  - The task name is `<prefix>_<task>` (`tasks/python/parse_duration` is `py_parse_duration`). Directory names may only use `a-z`, `0-9` and `_`.
  - `--tasks-dir` loads the same layout from other directories (private task sets).
- `tests/`: pytest suite (see "Checking changes").
- `.github/workflows/` and `sonar-project.properties`: CI (see "CI").

## Constraints

- **Standard library only, one script.** Users run `llm_bench.py` from a clone with no install step. Don't add dependencies or turn it into a package without being asked. Task content belongs in `tasks/`, not in the script.
- **Never weaken the sandbox.** All model-generated code must run through `run_cmd`. Don't add an option that runs generated code on the host, don't expose more host paths, the network or the user's home, and don't loosen the resource limits or the cgroup check. Changes in this area need explicit sign-off from the maintainer.
- **Treat model output as untrusted.** Replies are size-capped before parsing and before anything is written to disk. Paths derived from model, endpoint or tag names go through `safe_name()`, which also turns "." and ".." into safe names. Keep both of these in place.
- **Server-agnostic.** Use only the OpenAI-compatible `/v1/models` and `/v1/chat/completions` endpoints. No vendor-specific APIs or code paths.
- **No personal or environment-specific data.** No hostnames, IPs, hardware details or local paths in code, comments, examples or docs. Use placeholders like `localhost` or `gpu-box`.

## Task conventions

- Add a task by creating its directory under `tasks/<lang>/`; no code changes are needed.
- Each language has 4 tasks: 3 "write this" tasks of increasing difficulty and 1 "fix this code" task (directory named `fix_*`).
- **Tests check only what the prompt states.** Any behaviour a test checks must be specified in the prompt. Don't test unstated edge cases.
- Test failures must print the input, the actual result and the expected result, because this output is the feedback for the next attempt.
- Prefix harness-defined identifiers (`harness_`, `HARNESS_`, `harness_tests`) so they can't collide with names in the solution. This matters most for C++ headers, Rust (the test module is appended to the solution file) and Go (same package).
- C/C++ harnesses use exact-size heap copies of their inputs so ASan catches out-of-bounds access.
- Bash harnesses run with `set -u` and `LC_ALL=C`, use a `mktemp -d` scratch dir, and include file names with spaces.
- Prompts name the target file (`solution.py`, `solution.c`, `solution.hpp`, `package solution`, …) to match `LANGS`.
- Task harnesses are data, excluded from ruff, and must stay verbatim: any change to a prompt or harness, including whitespace, changes what models see.
- Every task needs a reference solution in `reference/`, and `tests/test_reference.py` must pass for it. Before adding a task, also check that plausible wrong solutions fail it with useful output (e.g. by calling `run_task()` on them from a scratch script), including slow solutions where the prompt states a complexity bound: the harness needs its own timing check, because the 60 s sandbox limit alone lets O(n²) solutions through and gives poor feedback.
- Renaming, moving or changing a task makes old results incomparable. Mention this in the change description. The row's `config` hash changes automatically with the task's prompt, harness or language spec.
- Bump `BENCH_VERSION` in `llm_bench.py` (and `version` in `pyproject.toml`, then run `uv lock`) whenever a code change can change results: the system prompt, feedback text, code extraction, build/test handling or the context-size estimate. It's part of every row's `config` hash, so rows from different versions are never mixed.

## Checking changes

Run both before handing off a change:

```sh
uv run --locked --no-build --group dev ruff check .
uv run --locked --no-build --group dev pytest
```

(Or run `ruff check .` and `pytest` directly if both are installed.)

- `tests/test_unit.py`: pure functions, task loading (including the built-in task set's consistency) and the CLI. No sandbox needed.
- `tests/test_runner.py`: request handling (`chat()` failure classification: HTTP errors, malformed or truncated replies, dropped connections, timeouts, server down) and the per-endpoint loop, against the mock server. No sandbox needed, so these replies never contain code.
- `tests/test_reference.py`: every built-in task has a reference solution (no sandbox needed) and it passes the task's harness (marker `sandbox`; warms the Go build cache once, which takes about a minute).
- `tests/test_e2e.py` (marker `sandbox`): full runs against the `MockServer` in `tests/conftest.py`, an OpenAI-compatible stdlib server that returns scripted replies, plus checks that the sandbox hides the home directory, the network and the environment. These tests skip themselves when bwrap + a systemd user session aren't available (e.g. in containers and on CI), so run them on a Linux host after touching the runner or the sandbox. Check the output for skips with `pytest -rs`.
- Add tests for new CLI options and runner behaviour. Use `MockServer(replies=[...])` to script model answers; a `Reply(...)` entry scripts HTTP errors, raw bodies, dropped connections or slow replies. Warm-up and context-check requests (`max_tokens=1`) don't consume replies; they're recorded in `MockServer.probes`, and the `context`, `reject_over` and `probe_reply` options simulate truncating, refusing or failing servers.
- `ruff format` isn't enforced. Don't reformat the whole file in an unrelated change.
- pytest collects only from `tests/` (`testpaths`), so Python harnesses under `tasks/` (named `test_solution.py`) are never run as tests themselves.

## CI

- `.github/workflows/`: `ci.yml` (ruff + pytest on Python 3.13 and 3.14), `sonarqube.yml` (runs pytest under `coverage`, then SonarQube Cloud analysis, configured in `sonar-project.properties`; automatic analysis is off; the quality gate requires 80 % coverage of new code, and sandbox tests skip on CI, so new runner code needs tests that work without the sandbox too), `osv-scanner.yml` (OSV-Scanner over the whole repository; `uv.lock` is currently its only lockfile) and `codeql.yml` (CodeQL for Python and the workflows, `tasks/` excluded). OSV and CodeQL upload their results to GitHub code scanning.
- Pin actions to full commit SHAs with the version in a comment, set `persist-credentials: false` on checkouts, and check workflow changes with `actionlint` and `zizmor --persona=auditor`.
- Don't commit files named `*old-results.json`, `*new-results.json` or `*.sarif`: the OSV PR scan writes its baseline to these paths, and the `guard-osv-results` job fails a PR that tracks one.

## Future plans

Planned, not started. Discuss the design with the maintainer before implementing.

- **Container version.** Ship the benchmark as a container image (Podman/Docker) with pinned toolchain versions, so it runs on hosts without bwrap, a systemd user session or locally installed toolchains, and results are comparable across machines. The current sandbox doesn't work inside an ordinary container (no systemd user manager, user namespaces usually blocked), so the likely design is to use the container runtime itself as the sandbox for each build/test: a fresh container per attempt with `--network=none`, memory/swap, PID and CPU limits, a read-only root, all capabilities dropped and `no-new-privileges`, and the same timeouts and output caps. It must keep the existing guarantees (no network, no host files beyond the task inputs, enforced resource limits) and fail closed when they can't be applied, just like the current cgroup check. The bwrap + systemd sandbox stays as the native option. A container-based sandbox would also let the end-to-end tests run on CI instead of being skipped.
- **More tasks, mainly new languages.** Candidates: TypeScript/JavaScript (Node), Java or Kotlin, C#, SQL (SQLite), Zig, and possibly Haskell or OCaml. Keep the same structure (3 "write this" tasks of increasing difficulty + 1 "fix this code" task per language) and the task conventions above. Constraints for a new language: the toolchain must build and test fully offline inside the sandbox (no package downloads, so no test frameworks outside the standard distribution unless they're preinstalled system-wide under `/usr`); it must work within the sandbox limits (2 GiB memory, 128 tasks, 60 s per build+test), which can be tight for JVM/.NET startup and thread counts; and toolchains installed outside `/usr` need an explicit read-only mount like the Rust sysroot. Adding a language also means a `LANGS` entry (with a unique task name prefix), a `tasks/<lang>/` directory, the toolchain check, the README task table and requirements, and the task consistency test in `tests/test_unit.py`.
- **Summary export.** `--summary` prints a terminal table; add Markdown (for READMEs and issues) and CSV output of the same aggregated numbers, and optionally a per-task breakdown showing which tasks separate the models.
- **Audit the older task harnesses.** The tasks added in 0.4.0 (`c_eval_expr`, `cpp_interval_set`, `go_parallel_map`, `rust_topo_order`) were reviewed against the task conventions; the other 20 weren't. Check each against "Task conventions": every failure prints the input, the actual result and the expected result; tests check only what the prompt states; prompts that state a complexity bound have a timing check; plausible wrong solutions fail with useful output. Known gaps from a first pass: bare `assert_eq!` without the input in `rust_csv_line`, `rust_version` and `rust_fix_inventory`; bare asserts in `py_fix_top_customers` and `py_retry_decorator`; `go_fix_count_lengths` reports "wrong counts" without the values. Changing a harness makes that task's results incomparable with earlier runs (its `config` hash changes), so batch the fixes into one change and mention it.
- **Reduce cognitive complexity.** SonarQube Cloud flags 8 functions above its cognitive-complexity limit of 15 (as of 0.4.0): `load_tasks` (39), `main` (32), `run_endpoint` (32), `chat` (30), `print_summary` (23), `read_results` (20), `run_cmd` (18), `run_one_task` (17). Split the worst ones into focused helpers (e.g. task-directory validation, results-file setup, per-model loop, CLI-mode dispatch, summary formatting) without changing behaviour; the existing tests cover them. Splitting code that reads well top to bottom just to get under 15 isn't the goal.
- **Speed metrics.** Report tokens per second per model (completion tokens / request time, from data already collected), and reasoning tokens separately where the server returns them (`usage.completion_tokens_details.reasoning_tokens`).
