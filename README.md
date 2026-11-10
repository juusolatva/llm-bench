# llm-bench

[![CI](https://github.com/juusolatva/llm-bench/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/juusolatva/llm-bench/actions/workflows/ci.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=juusolatva_llm-bench&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=juusolatva_llm-bench)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=juusolatva_llm-bench&metric=coverage)](https://sonarcloud.io/summary/overall?id=juusolatva_llm-bench)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Python](https://img.shields.io/badge/python-3.13%20%7C%203.14-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/github/license/juusolatva/llm-bench)](LICENSE)

A dependency-free benchmark for checking how well LLMs write and fix code. It sends 32 small programming and terminal tasks to every model on one or more OpenAI-compatible servers, extracts the code from each reply, and builds and tests it against a hidden harness inside a sandbox. When a solution fails, the build/test output is sent back so the model can try again.

It works with any server that implements `GET /v1/models` and `POST /v1/chat/completions`, including Ollama, LM Studio, the llama.cpp server, vLLM and hosted OpenAI-compatible APIs.

## Tasks

There are 4 tasks per language: 3 "write this" tasks of increasing difficulty and 1 "fix this code" task.

| Language | Tasks |
|---|---|
| Python | `py_parse_duration`, `py_fix_top_customers`, `py_deep_merge`, `py_retry_decorator` |
| C | `c_join_path`, `c_parse_kv`, `c_fix_intvec`, `c_eval_expr` (built with ASan + UBSan) |
| C++ | `cpp_top_words`, `cpp_lru_cache`, `cpp_fix_buffer`, `cpp_interval_set` (built with ASan + UBSan) |
| Rust | `rust_version`, `rust_csv_line`, `rust_fix_inventory`, `rust_topo_order` |
| Go | `go_word_freq`, `go_kv_http`, `go_fix_count_lengths`, `go_parallel_map` (run with `-race`) |
| TypeScript | `ts_parse_config`, `ts_map_limit`, `ts_fix_route`, `ts_broadcaster` (checked with `tsc --strict`) |
| Bash | `bash_top_words`, `bash_rotate_backups`, `bash_fix_rename`, `bash_access_log` |
| Terminal | `term_find_refs`, `term_set_port`, `term_fix_portable`, `term_compare_dirs` |

Bash tasks ask for reusable scripts: arguments, usage errors, exit codes and the Bash language itself. Terminal tasks ask for the one-off commands you would type to search, edit and compare files with everyday tools (grep, sed, awk, find, sort, comm, xargs), including fixing commands written for macOS so they work with the GNU tools. They run with no arguments in a prepared directory with tricky file names (spaces, quotes, leading dashes, hidden files) and allow no other interpreters.

The tests check only what the prompt states. Run `./llm_bench.py --list-tasks` to list them.

Each task is a directory under [`tasks/`](tasks):

```
tasks/<lang>/<task>/
  prompt.md          # sent to the model as is
  test_solution.py   # hidden test harness (test.c, test.cpp, test.rs, solution_test.go, test.ts or test.sh for other languages)
  reference/
    solution.py      # a known-correct solution (not sent to the model), named like the model's solution file
```

The task name is the language prefix plus the directory name, so `tasks/python/parse_duration` is `py_parse_duration`.

A solution passes when its harness exits with status 0 and has printed its final line, `harness: all checks passed`, after its last check (Rust harnesses use libtest's `test result: ok.` summary instead). So a solution that ends the process early with status 0, for example with `sys.exit(0)` at import, fails instead of skipping the remaining checks. Rust solutions are built as a library crate and the harness as a separate test crate, so the functions and types a prompt asks for must be `pub`. TypeScript solutions are compiled together with the harness by `tsc --strict`, so a type error in either file fails the build, and the harness imports the names the prompt asks for (`import { route } from "./solution.js";`), which must be exported.

### Private tasks

Tasks published on the internet can end up in model training data. To benchmark with tasks of your own, create a directory with the same layout and pass it with `--tasks-dir`. It replaces the built-in tasks; to run both, also pass the built-in directory:

```sh
./llm_bench.py localhost:11434 --tasks-dir ~/my-tasks
./llm_bench.py localhost:11434 --tasks-dir ~/my-tasks --tasks-dir ./tasks
```

Their harnesses must print the final line too (Rust harnesses import the solution's items from the `solution` crate: `use solution::parse_csv_line;`, TypeScript harnesses from `./solution.js`). A harness that ends with a plain `ok`, as before benchmark version 0.5.0, fails every solution.

## Requirements

- Linux with cgroup v2 and a user systemd manager (`systemd-run --user` must work). This is the default on current Fedora, Ubuntu, Debian, Arch etc. desktop and server installs.
- [bubblewrap](https://github.com/containers/bubblewrap) 0.8 or newer (`bwrap`); 0.11 or newer for the Go build cache (see [Go tasks](#go-tasks)).
- Python 3.13+ (standard library only, nothing to `pip install`). Run the script from a clone of this repository so it finds `tasks/`.
- The toolchains for the languages you benchmark, on `PATH`: `python3`, `gcc`, `g++` (C++17), `rustc` (edition 2021), `go` (1.22+), `node` (22+) and `tsc` (TypeScript 5.5 to 6.x), `bash`, plus coreutils/findutils; GNU diffutils (`diff`, `cmp`), `grep`, `sed` and `gawk` for the terminal tasks. You only need the toolchains for the tasks you select with `--task`.

Example installs:

```sh
# Fedora
sudo dnf install bubblewrap gcc gcc-c++ libasan libubsan golang rust
# Debian / Ubuntu
sudo apt install bubblewrap build-essential golang rustc gawk
```

`rustc` installed via rustup also works: the sandbox exposes only the resolved toolchain directory, not `~/.cargo` or `~/.rustup`.

Node and TypeScript can come from a version manager such as fnm or nvm, or from a system-wide install: the benchmark uses the `node` and `tsc` that come first on `PATH` (for example after `npm install -g typescript@6` in the Node installation you use) and exposes only the Node binary and the `typescript` package directory to the sandbox, not the rest of a version manager's installation, its global packages or your home directory. A system-wide install under `/usr` is visible like the rest of `/usr`, which the sandbox mounts read-only for every language, global packages in `/usr/lib/node_modules` included. Wrappers that replace `tsc` with a script or binary of their own (Volta, asdf or pnpm shims) aren't supported, and neither is TypeScript 7, whose compiler is a native binary in separate per-platform packages that the sandbox doesn't mount. Tested with Node 24.22.1 and TypeScript 6.0.3; TypeScript results can differ between `tsc` versions, whose checks and error messages change.

## Usage

```sh
./llm_bench.py http://localhost:11434/v1            # Ollama
./llm_bench.py localhost:1234                       # LM Studio (http:// and /v1 are added)
./llm_bench.py a=host-a:11434 b=host-b:1234         # two servers, benchmarked in parallel
./llm_bench.py localhost:8080 -m 'qwen*' --task 'py_*' --task 'rust_*'
./llm_bench.py localhost:11434 --resume              # continue an interrupted run
./llm_bench.py localhost:11434 --repeat 3 --resume   # top up to 3 trials per task
./llm_bench.py --summary results_*.csv               # summary table of earlier runs
./llm_bench.py --summary results_*.csv --format markdown --per-task   # for a README or an issue
```

Endpoints are given as `[NAME=]URL`. `NAME` labels the endpoint in output files (default: `HOST_PORT`). If no endpoint is given on the command line, they are read from the space-separated `LLM_BENCH_ENDPOINTS` environment variable. HTTP redirects are never followed (a redirect would send the API key to another location), so give the final URL.

| Option | Default | Description |
|---|---|---|
| `-m, --model PATTERN` | all | Only models whose ID matches an exact ID or shell glob. Repeatable. Without `-m`, embedding models and vision-language (`vl`) variants are skipped. |
| `--task PATTERN` | all | Only tasks whose name matches a shell glob, e.g. `'py_*'`. Repeatable. |
| `--list-tasks` | | List tasks and exit. |
| `--tasks-dir DIR` | `tasks/` | Load tasks from `DIR` instead of the built-in ones. Repeatable. |
| `--api-key KEY` | | Bearer token sent to every endpoint. Also read from `LLM_BENCH_API_KEY` or `OPENAI_API_KEY`. |
| `--timeout SEC` | 1800 | Per-request timeout. It must cover model load time plus generating `--max-tokens` tokens on your slowest model. |
| `--max-tokens N` | 16384 | Completion token limit. The prompt (up to ~9k tokens with feedback) plus `N` must fit in the model's context window. |
| `--attempts N` | 3 | `1` = single shot; `N` = first attempt plus `N-1` retries with build/test feedback. |
| `--temperature T` | server default | Sampling temperature. Same as `--param temperature=T`. |
| `--param KEY=VALUE` | | Extra request parameter such as `top_p=0.9`, `seed=1` or `reasoning_effort=low`. `VALUE` is parsed as JSON when possible (numbers, `true`, lists), otherwise used as a string. Repeatable. |
| `--no-context-check` | | Skip the per-model context check (see below). |
| `--repeat K` | 1 | Run `K` rounds: `K` trials of every task per model. Results vary between trials (sampling), so several rounds show how much of a difference between models is noise. |
| `--resume` | | Skip trials that already have a finished row in the results file with the same settings and task version (`config`), e.g. after an interruption or to add `--repeat` rounds. Trials that failed on request errors (`http_*`, `bad_response`, `disconnected`, `skipped`) are run again. |
| `--max-length-finishes K` | never | Skip a model's remaining trials after `K` of them ended with a reply cut off at `--max-tokens`, so one model that rambles can't eat the whole run. |
| `--summary CSV...` | | Print the summary table of existing results files and exit. No endpoint needed. |
| `--format FORMAT` | `table` | With `--summary`: print the summary as a terminal `table`, `markdown` (a pipe table, notes as paragraphs below it) or `csv` (plain numbers, see below). |
| `--per-task` | | With `--summary`: also print a task × model table of passes per trial, to see which tasks separate the models. With `--format csv`, it's printed instead of the summary. |
| `-o, --output-dir DIR` | `.` | Where results and transcripts are written. |
| `-t, --tag TAG` | | Write `results_<endpoint>_<TAG>.csv`, so runs with different settings don't overwrite each other. |

### Server setup tips

- **Context length.** With the defaults a retry request can need about 25k tokens of context (roughly 1k + 4k per retry + `--max-tokens`). Configure the server for at least 32k. Many servers default to much less and silently truncate the prompt. For example, Ollama uses `OLLAMA_CONTEXT_LENGTH=32768`, and LM Studio sets the context length in the model's load settings. If you can't, lower `--max-tokens` or `--attempts` so the need fits.
- **Context check.** Before each model's first task, the benchmark loads it with a tiny request (its time goes into `load_seconds`, not the first task) and then checks the context: it measures the model's tokens per word with a short filler prompt, sends a filler prompt of the needed size, and compares the prompt tokens the server reports. A server that truncates reports too few; one that refuses answers with an error. Token counts that aren't plausible (not whole numbers, or under 0.5 or over 10 tokens per word) are never used to size the prompt: too few tokens per word means even the calibration prompt was cut off (`short`), and anything else leaves the context `unchecked`. The result is recorded in the `context` column and a failed check is repeated under the summary. It costs one long prompt per model; `--no-context-check` skips it.
- **One model at a time.** Models are benchmarked one after another. If the server keeps earlier models loaded, the next model may not fit in VRAM and run partly on the CPU, which only affects timing. Let the server evict old models: Ollama with `OLLAMA_MAX_LOADED_MODELS=1`, LM Studio with the auto-evict option for JIT-loaded models.
- **Thinking models.** `<think>…</think>` blocks are removed before code extraction, as is everything before a `</think>` without an opening tag (some chat templates put the opening tag in the prompt). Tags inside a fenced code block are left alone, as part of the code. A reply that is only unfinished reasoning (an opening `<think>` that never closes, typically cut off at `--max-tokens`) counts as containing no code. Reasoning returned in a separate field is ignored, but its token count is recorded in `reasoning_tokens` when the server reports it. Reasoning tokens still count toward `--max-tokens`, so raise it if replies end with `finish_reason=length`.
- **Code extraction.** The system prompt asks for exactly one fenced code block. If a reply has several, the blocks tagged with the task's language (for example ` ```python ` or ` ```py `) are the candidates, or all blocks if none is tagged that way. The last candidate is used, which is the fix when a reply quotes the original code first, unless it is less than half as long as the longest one (a usage example or a snippet after the full file); then the longest is used. A reply without a fenced block is used as is.

## Output

- `results_<endpoint>[_<tag>].csv`: one row per trial (one model working on one task, through all its attempts), written as each trial finishes, so an interrupted run keeps its results. Rows are **appended**, so re-running a few models adds to an existing file instead of replacing it. Re-running the same model and task under the same settings adds another trial of it (unless `--resume` finds it already done). Columns:

  | Column | Meaning |
  |---|---|
  | `run_id` | UTC start time of the run with milliseconds, e.g. `20261107T202918.123Z` (older versions wrote whole seconds). |
  | `endpoint`, `model`, `task`, `lang` | What was run. |
  | `repeat` | Number of this trial of the task for this model and `config` (1, 2, …), continuing after the rows already in the file. |
  | `passed`, `passed_on`, `attempts` | 1 if any attempt passed; which attempt passed (0 = none); attempts made. |
  | `prompt_tokens`, `completion_tokens` | Token usage summed over all attempts, as reported by the server (counts that aren't non-negative integers are ignored). |
  | `reasoning_tokens` | The part of `completion_tokens` spent on reasoning, summed over all attempts (`usage.completion_tokens_details.reasoning_tokens`). Empty unless every reply reported it. |
  | `seconds` | Time spent waiting for replies (not building and testing). |
  | `usage_seconds` | Request time of the replies that reported their completion tokens (even 0), without waits for an unreachable server: the throughput's time base. Empty in rows from older versions. |
  | `load_seconds` | Time of the model's warm-up request, i.e. mostly load time. The same for all of a model's rows in a run. |
  | `finish_reason`, `fail_stage` | See below. |
  | `context` | Result of the context check: `ok`, `short:<tokens>` (truncated at about that many tokens), `rejected:<error>`, or `unchecked`. |
  | `params` | Request parameters set with `--param` / `--temperature`, as JSON. Anything not listed is the server's default. |
  | `settings` | Hash of the settings alone (benchmark version, system prompt, limits, parameters). The summary only averages rows with the same `settings`. |
  | `config` | Hash of everything that affects the result: benchmark version, system prompt, `--max-tokens`, `--attempts`, `--timeout`, parameters, sandbox limits, and the task's own prompt, harness and build commands. Rows with equal hashes were produced under the same conditions. |

  A file written by an older version whose columns are all still current is upgraded before a run appends to it: it's rewritten once with the current columns, and the new ones are empty in its existing rows. The benchmark refuses to append to a file with other columns (or the same column twice), and leaves a file it can't upgrade untouched.
- `runs/<endpoint>[_<tag>]/<model>/<task>/<config>/repeat_<r>/attempt_<n>/`: `response.md` (raw model reply), `log.txt` (build/test output), and the files that were tested. `<config>` and `r` match the row's `config` and `repeat`, so later trials never overwrite earlier transcripts, even after settings or a task change. `<model>` is the model ID if it only contains letters, digits, `.`, `_` and `-` (and doesn't start with a dot). Otherwise those other characters (and a leading dot) are replaced by `_` and `~` plus a 16-digit hash of the ID is appended, so `org/model` becomes `org_model~<hash>`. The name doesn't depend on which other models are run, so two models practically never share a directory, not even across runs (that takes a collision of the 64-bit hashes; within a run, `-2`, `-3`, … are appended then). IDs longer than 200 bytes are cut to fit before the hash is added.
- A summary table on stdout, one line per endpoint and model: `pass@1` (tasks passed on the first attempt), `passed` (tasks passed within `--attempts`), per-language results, token counts (`reason_tok` only when some row reports reasoning tokens; `-` for a model unless every trial that got a reply reported them, since a partial count isn't on the same scale as `compl_tok`), total reply time (`sec`), throughput (`tok/s`: completion tokens per second of the replies that reported them, from `usage_seconds`; `-` without any, or when no tokens were generated; rows from older versions without `usage_seconds` count with all their reply time if they ended with a reply that reported token usage; it includes prompt processing, so it's lower than the pure generation speed) and load time. Models are sorted by `passed`, then `pass@1`. With `--resume` the table covers the whole results file; otherwise just this run. Ctrl-C stops the run promptly and still prints the summary of the trials finished so far.

  A **round** is one trial of every task. When tasks have several trials (`--repeat`, or re-runs under the same settings), scores are mean passes per round, shown as `mean±sd/tasks`, and a `rounds` column shows the number of trials per task. The ± is the standard deviation of a single round's score, estimated from each task's pass rate: if two models are closer than that, one round can't tell them apart. Tokens and seconds are then means per round. `--summary` works the same on any set of results files; rows are only averaged when their `settings` match (otherwise a `settings` column tells the groups apart). Models with the same settings are all scored on the same version of each task, its newest one (from the latest `run_id`): rows of older versions are left out, so a model without trials of a task's newest version is scored without that task. Scores are only comparable between models scored on the same tasks; when models with the same settings were scored on different tasks (because of `--task`, or a task version that only some of them were run on), a warning under the table names the tasks each one is missing.

  `--summary --format csv` prints the same numbers unformatted, one record per endpoint, model and settings: `endpoint`, `model`, `settings`, `tasks`, `rounds_min`, `rounds_max`, `pass1`, `pass1_sd`, `passed`, `passed_sd` (the spreads are empty with one round), per language `<lang>` (mean passes) and `<lang>_tasks`, then `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `seconds` (means per round), `tok_per_s` and `load_seconds`. Unknown values are empty, and notes go to stderr. With `--per-task` the CSV has one record per model and task instead: `endpoint`, `model`, `settings`, `task`, `lang`, `trials`, `passed`, `passed_on_first`.

`finish_reason` is the server's value for the last reply (`stop`, `length`, …) or one of these:

| Value | Meaning |
|---|---|
| `timeout` | No reply within `--timeout`. |
| `http_<code>` | The server returned an HTTP error, e.g. the model failed to load or crashed, or the prompt didn't fit its context, or a redirect (`http_3xx`), which isn't followed. |
| `bad_response` | The reply wasn't a valid chat completion (invalid or truncated JSON, no `choices`, a body over 8 MiB, …). |
| `disconnected` | The connection dropped while the server itself stayed reachable (typically a crashed model process). |
| `oversized` | The reply text exceeded 1,048,576 characters. Nothing is written to disk for it. |
| `skipped` | Not attempted: the model had 3 request errors (`http_*`, `bad_response`, `disconnected`) in a row (`fail_stage` `request`), or reached `--max-length-finishes` (`fail_stage` `budget`), so its remaining trials were skipped. |

If the model's warm-up request fails (for example it can't be loaded), all its tasks get that request error as `finish_reason` with `fail_stage` `load`, and the next model runs.

If the server itself becomes unreachable, the benchmark retries the request after 10, 30 and 60 seconds, then stops that endpoint. Tasks it didn't get to have no rows.

`fail_stage` says where the last attempt failed: `build` (compiling), `test` (the test harness failed, or exited with status 0 without printing its final line), `time_limit` (building and testing exceeded the 60 s sandbox limit), `no_code` (the reply contained no code), `request` (one of the request-level failures above), `load` (the model failed to load) or `budget` (skipped by `--max-length-finishes`). It's empty when the task passed.

## Go tasks

`go test -race` needs a race-instrumented build of the Go standard library, which takes about 35 s to compile from scratch on a 2-CPU sandbox: over half of the 60 s limit. So when Go tasks are selected, the benchmark first compiles it once into a temporary build cache (about 1–2 minutes, running only trusted code). Each sandbox then sees that cache through an overlay whose writes go to a private tmpfs, so attempts can't change it for each other. This needs bubblewrap 0.11+ and overlayfs in user namespaces (Linux 5.11+); otherwise the benchmark warns and every Go attempt compiles from scratch.

## TypeScript tasks

The solution and harness are compiled with a fixed `tsconfig.json` (`strict`, target ES2023, the ES2023 and DOM libraries, `"types": []`) and run with `node` as ES modules. There is no `@types/node`, so solutions can use the ECMAScript standard library and the web-standard globals Node also provides (`console`, `URL`, `setTimeout`, ...), but no Node modules or globals such as `process`; the prompts say so. `tsc` prints its errors with the offending source line, and the benchmark removes the color codes from that output before sending it back to the model. At startup the benchmark checks that `tsc` runs inside the sandbox, so a TypeScript install that needs files outside its own package stops the run instead of failing every solution.

## Sandbox

Model-generated code never runs directly on the host. Each build and test runs inside:

- a **bubblewrap** sandbox with all namespaces unshared (no network), all capabilities dropped and a cleared environment. Only `/usr`, `/bin`, `/lib*`, the Rust toolchain, the Node binary, the TypeScript package and a read-only copy of the task's files are visible, and everything is written to private tmpfs mounts.
- a transient **systemd user unit** with a memory limit (2 GiB, no swap), a task limit (128), a CPU limit (200 %), a 60 s run time limit and a file-size limit. Before starting the sandbox, a small launcher checks that these cgroup limits were actually applied and refuses to run if not.

If the sandbox is unavailable, the benchmark exits before contacting any server. There is no option to run without it.

## Development

```sh
uv run --locked --no-build --group dev ruff check .
uv run --locked --no-build --group dev ruff format --check .
uv run --locked --no-build --group dev pytest -rs
```

The end-to-end tests run scripted replies from a mock OpenAI-compatible server through the real sandbox. They and the reference-solution runs skip themselves where the sandbox isn't available (containers, CI), and the reference runs also skip languages whose toolchain is missing. Run the full suite on a Linux host with the sandbox requirements above before changing the runner, the sandbox or a task; the first Go reference run warms the Go build cache, which takes about a minute.

CI (GitHub Actions) runs the ruff linter and format check and pytest on Python 3.13 and 3.14, SonarQube Cloud analysis with test coverage, CodeQL (GitHub's default setup), and an OSV-Scanner scan of the repository's dependency lockfiles (currently just `uv.lock`).

To add a task, create its directory under `tasks/`, including a reference solution. No code changes are needed. `tests/test_reference.py` runs every reference solution through the sandbox and expects it to pass, which catches broken harnesses. See [AGENTS.md](AGENTS.md) for the conventions tasks follow.

## License

[MIT](LICENSE)
