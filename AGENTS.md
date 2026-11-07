# AGENTS.md

Guidance for coding agents working in this repository.

## Overview

`llm_bench.py` is a single-file, standard-library-only Python script. It benchmarks LLMs served over an OpenAI-compatible API on coding tasks and builds and tests the generated code in a sandbox. See `README.md` for user-facing documentation; keep it in sync when you change options, output formats, requirements or tasks.

File layout, top to bottom:

1. **Configuration**: defaults for CLI options, sandbox limits, the system prompt, and `LANGS` (per-language file names and build/test commands).
2. **Tasks**: a `*_PROMPT` and a `*_TEST` string per task, then the `TASKS` registry.
3. **Runner**: HTTP client, endpoint parsing, sandbox (`run_cmd`), task execution, the per-endpoint loop (`run_endpoint`), summary, CLI.

## Constraints

- **Standard library only, single file.** Users run it by downloading one script. Don't add dependencies or split it into a package without being asked.
- **Never weaken the sandbox.** All model-generated code must run through `run_cmd`. Don't add an option that runs generated code on the host, don't expose more host paths, the network or the user's home, and don't loosen the resource limits or the cgroup check. Changes in this area need explicit sign-off from the maintainer.
- **Treat model output as untrusted.** Replies are size-capped before parsing and before anything is written to disk. Paths derived from model or endpoint names go through `UNSAFE_NAME_RE`. Keep both of these in place.
- **Server-agnostic.** Use only the OpenAI-compatible `/v1/models` and `/v1/chat/completions` endpoints. No vendor-specific APIs or code paths.
- **No personal or environment-specific data.** No hostnames, IPs, hardware details or local paths in code, comments, examples or docs. Use placeholders like `localhost` or `gpu-box`.

## Task conventions

- Each language has 4 tasks: 3 "write this" tasks of increasing difficulty and 1 "fix this code" task (named `<lang>_fix_*`).
- **Tests check only what the prompt states.** Any behaviour a test checks must be specified in the prompt. Don't test unstated edge cases.
- Test failures must print the input, the actual result and the expected result, because this output is the feedback for the next attempt.
- Prefix harness-defined identifiers (`harness_`, `HARNESS_`, `harness_tests`) so they can't collide with names in the solution. This matters most for C++ headers, Rust (the test module is appended to the solution file) and Go (same package).
- C/C++ harnesses use exact-size heap copies of their inputs so ASan catches out-of-bounds access.
- Bash harnesses run with `set -u` and `LC_ALL=C`, use a `mktemp -d` scratch dir, and include file names with spaces.
- Prompts name the target file (`solution.py`, `solution.c`, `solution.hpp`, `package solution`, …) to match `LANGS`.
- Before registering a new task, check that a correct reference solution passes it and that plausible wrong solutions fail it. A `MockServer` that returns those solutions works for this (see below).
- Renaming or changing a task makes old results incomparable. Mention this in the change description.

## Checking changes

Run both before handing off a change:

```sh
uv run --group dev ruff check .
uv run --group dev pytest
```

(Or run `ruff check .` and `pytest` directly if both are installed.)

- `tests/test_unit.py`: pure functions, the task registry and the CLI. No sandbox needed.
- `tests/test_e2e.py` (marker `sandbox`): full runs against the `MockServer` in `tests/conftest.py`, an OpenAI-compatible stdlib server that returns scripted replies, plus checks that the sandbox hides the home directory, the network and the environment. These tests skip themselves when bwrap + a systemd user session aren't available (e.g. in containers and on CI), so run them on a Linux host after touching the runner or the sandbox. Check the output for skips with `pytest -rs`.
- Add tests for new CLI options and runner behaviour. Use `MockServer(replies=[...])` to script model answers.
- `ruff format` isn't enforced. Don't reformat the whole file in an unrelated change.

## Future plans

Planned, not started. Discuss the design with the maintainer before implementing.

- **Container version.** Ship the benchmark as a container image (Podman/Docker) with pinned toolchain versions, so it runs on hosts without bwrap, a systemd user session or locally installed toolchains, and results are comparable across machines. The current sandbox doesn't work inside an ordinary container (no systemd user manager, user namespaces usually blocked), so the likely design is to use the container runtime itself as the sandbox for each build/test: a fresh container per attempt with `--network=none`, memory/swap, PID and CPU limits, a read-only root, all capabilities dropped and `no-new-privileges`, and the same timeouts and output caps. It must keep the existing guarantees (no network, no host files beyond the task inputs, enforced resource limits) and fail closed when they can't be applied, just like the current cgroup check. The bwrap + systemd sandbox stays as the native option. A container-based sandbox would also let the end-to-end tests run on CI instead of being skipped.
