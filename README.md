# llm-bench

A dependency-free benchmark for checking how well LLMs write and fix code. It sends 24 small programming tasks to every model on one or more OpenAI-compatible servers, extracts the code from each reply, and builds and tests it against a hidden harness inside a sandbox. When a solution fails, the build/test output is sent back so the model can try again.

It works with any server that implements `GET /v1/models` and `POST /v1/chat/completions`, including Ollama, LM Studio, the llama.cpp server, vLLM and hosted OpenAI-compatible APIs.

## Tasks

There are 4 tasks per language: 3 "write this" tasks of increasing difficulty and 1 "fix this code" task.

| Language | Tasks |
|---|---|
| Python | `py_parse_duration`, `py_fix_top_customers`, `py_deep_merge`, `py_retry_decorator` |
| C | `c_trim`, `c_join_path`, `c_fix_intvec`, `c_parse_kv` (built with ASan + UBSan) |
| C++ | `cpp_split`, `cpp_top_words`, `cpp_fix_buffer`, `cpp_lru_cache` (built with ASan + UBSan) |
| Rust | `rust_word_count`, `rust_version`, `rust_fix_inventory`, `rust_csv_line` |
| Go | `go_reverse`, `go_word_freq`, `go_fix_count_lengths`, `go_kv_http` (run with `-race`) |
| Bash | `bash_top_words`, `bash_rotate_backups`, `bash_fix_rename`, `bash_access_log` |

The tests check only what the prompt states. Run `./llm_bench.py --list-tasks` to list them.

Each task is a directory under [`tasks/`](tasks):

```
tasks/<lang>/<task>/
  prompt.md          # sent to the model as is
  test_solution.py   # hidden test harness (test.c, test.cpp, test.rs, solution_test.go or test.sh for other languages)
```

The task name is the language prefix plus the directory name, so `tasks/python/parse_duration` is `py_parse_duration`.

### Private tasks

Tasks published on the internet can end up in model training data. To benchmark with tasks of your own, create a directory with the same layout and pass it with `--tasks-dir`. It replaces the built-in tasks; to run both, also pass the built-in directory:

```sh
./llm_bench.py localhost:11434 --tasks-dir ~/my-tasks
./llm_bench.py localhost:11434 --tasks-dir ~/my-tasks --tasks-dir ./tasks
```

## Requirements

- Linux with cgroup v2 and a user systemd manager (`systemd-run --user` must work). This is the default on current Fedora, Ubuntu, Debian, Arch etc. desktop and server installs.
- [bubblewrap](https://github.com/containers/bubblewrap) 0.8 or newer (`bwrap`); 0.11 or newer for the Go build cache (see [Go tasks](#go-tasks)).
- Python 3.13+ (standard library only, nothing to `pip install`). Run the script from a clone of this repository so it finds `tasks/`.
- The toolchains for the languages you benchmark, on `PATH`: `python3`, `gcc`, `g++` (C++17), `rustc` (edition 2021), `go` (1.22+), `bash`, plus coreutils/findutils. You only need the toolchains for the tasks you select with `--task`.

Example installs:

```sh
# Fedora
sudo dnf install bubblewrap gcc gcc-c++ libasan libubsan golang rust
# Debian / Ubuntu
sudo apt install bubblewrap build-essential golang rustc
```

`rustc` installed via rustup also works: the sandbox exposes only the resolved toolchain directory, not `~/.cargo` or `~/.rustup`.

## Usage

```sh
./llm_bench.py http://localhost:11434/v1            # Ollama
./llm_bench.py localhost:1234                       # LM Studio (http:// and /v1 are added)
./llm_bench.py a=host-a:11434 b=host-b:1234         # two servers, benchmarked in parallel
./llm_bench.py localhost:8080 -m 'qwen*' --task 'py_*' --task 'rust_*'
./llm_bench.py localhost:11434 --resume              # continue an interrupted run
./llm_bench.py localhost:11434 --repeat 3 --resume   # top up to 3 runs per task
./llm_bench.py --summary results_*.csv               # summary table of earlier runs
```

Endpoints are given as `[NAME=]URL`. `NAME` labels the endpoint in output files (default: `HOST_PORT`). If no endpoint is given on the command line, they are read from the space-separated `LLM_BENCH_ENDPOINTS` environment variable.

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
| `--repeat K` | 1 | Run every task `K` times per model. Results vary between runs (sampling), so repeats show how much of a difference between models is noise. |
| `--resume` | | Skip runs that already have a finished row in the results file with the same settings and task version (`config`), e.g. after an interruption or to add `--repeat` runs. Rows that failed on request errors (`http_*`, `bad_response`, `disconnected`, `skipped`) are run again. |
| `--max-length-finishes K` | never | Skip a model's remaining runs after `K` of them ended with a reply cut off at `--max-tokens`, so one model that rambles can't eat the whole run. |
| `--summary CSV...` | | Print the summary table of existing results files and exit. No endpoint needed. |
| `-o, --output-dir DIR` | `.` | Where results and transcripts are written. |
| `-t, --tag TAG` | | Write `results_<endpoint>_<TAG>.csv`, so runs with different settings don't overwrite each other. |

### Server setup tips

- **Context length.** With the defaults a retry request can need about 25k tokens of context (roughly 1k + 4k per retry + `--max-tokens`). Configure the server for at least 32k. Many servers default to much less and silently truncate the prompt. For example, Ollama uses `OLLAMA_CONTEXT_LENGTH=32768`, and LM Studio sets the context length in the model's load settings. If you can't, lower `--max-tokens` or `--attempts` so the need fits.
- **Context check.** Before each model's first task, the benchmark loads it with a tiny request (its time goes into `load_seconds`, not the first task) and then checks the context: it measures the model's tokens per word with a short filler prompt, sends a filler prompt of the needed size, and compares the prompt tokens the server reports. A server that truncates reports too few; one that refuses answers with an error. The result is recorded in the `context` column and a failed check is repeated under the summary. It costs one long prompt per model; `--no-context-check` skips it.
- **One model at a time.** Models are benchmarked one after another. If the server keeps earlier models loaded, the next model may not fit in VRAM and run partly on the CPU, which only affects timing. Let the server evict old models: Ollama with `OLLAMA_MAX_LOADED_MODELS=1`, LM Studio with the auto-evict option for JIT-loaded models.
- **Thinking models.** `<think>…</think>` blocks are removed before code extraction. Reasoning returned in a separate field is ignored. Reasoning tokens still count toward `--max-tokens`, so raise it if replies end with `finish_reason=length`.

## Output

- `results_<endpoint>[_<tag>].csv`: one row per model × task, written as each task finishes, so an interrupted run keeps its results. Rows are **appended**, so re-running a few models adds to an existing file instead of replacing it. Re-running the same model and task under the same settings adds another repeat of it (unless `--resume` finds it already done). Columns:

  | Column | Meaning |
  |---|---|
  | `run_id` | UTC start time of the run, e.g. `20261107T202918Z`. |
  | `endpoint`, `model`, `task`, `lang` | What was run. |
  | `repeat` | Number of this run of the task for this model and `config` (1, 2, …), continuing after the rows already in the file. |
  | `passed`, `passed_on`, `attempts` | 1 if any attempt passed; which attempt passed (0 = none); attempts made. |
  | `prompt_tokens`, `completion_tokens` | Token usage summed over all attempts, as reported by the server. |
  | `seconds` | Time spent waiting for replies (not building and testing). |
  | `load_seconds` | Time of the model's warm-up request, i.e. mostly load time. The same for all of a model's rows in a run. |
  | `finish_reason`, `fail_stage` | See below. |
  | `context` | Result of the context check: `ok`, `short:<tokens>` (truncated at about that many tokens), `rejected:<error>`, or `unchecked`. |
  | `params` | Request parameters set with `--param` / `--temperature`, as JSON. Anything not listed is the server's default. |
  | `settings` | Hash of the settings alone (benchmark version, system prompt, limits, parameters). The summary only averages rows with the same `settings`. |
  | `config` | Hash of everything that affects the result: benchmark version, system prompt, `--max-tokens`, `--attempts`, `--timeout`, parameters, sandbox limits, and the task's own prompt, harness and build commands. Rows with equal hashes were produced under the same conditions. |

  The benchmark refuses to append to a file that has different columns (e.g. from an older version).
- `runs/<endpoint>[_<tag>]/<model>/<task>/repeat_<r>/attempt_<n>/`: `response.md` (raw model reply), `log.txt` (build/test output), and the files that were tested. `r` matches the row's `repeat`, so later runs never overwrite earlier transcripts.
- A summary table on stdout, one line per endpoint and model: `pass@1` (tasks passed on the first attempt), `passed` (tasks passed within `--attempts`), per-language results, token counts, total reply time and load time. Models are sorted by `passed`, then `pass@1`. With `--resume` the table covers the whole results file; otherwise just this run. Ctrl-C stops the run promptly and still prints the summary of the tasks finished so far.

  When tasks have several runs (`--repeat`, or re-runs under the same settings), scores are mean passes per run, shown as `mean±sd/tasks`. The ± is the standard deviation of a single run's score, estimated from each task's pass rate: if two models are closer than that, one run can't tell them apart. Tokens and seconds are then means per run. `--summary` works the same on any set of results files; rows are only averaged when their `settings` match (otherwise a `settings` column tells the groups apart), and for each task only rows of its newest version count.

`finish_reason` is the server's value for the last reply (`stop`, `length`, …) or one of these:

| Value | Meaning |
|---|---|
| `timeout` | No reply within `--timeout`. |
| `http_<code>` | The server returned an HTTP error, e.g. the model failed to load or crashed, or the prompt didn't fit its context. |
| `bad_response` | The reply wasn't a valid chat completion (invalid or truncated JSON, no `choices`, …). |
| `disconnected` | The connection dropped while the server itself stayed reachable (typically a crashed model process). |
| `oversized` | The reply text exceeded 1 MiB. |
| `skipped` | Not attempted: the model had 3 request errors (`http_*`, `bad_response`, `disconnected`) in a row (`fail_stage` `request`), or reached `--max-length-finishes` (`fail_stage` `budget`), so its remaining runs were skipped. |

If the model's warm-up request fails (for example it can't be loaded), all its tasks get that request error as `finish_reason` with `fail_stage` `load`, and the next model runs.

If the server itself becomes unreachable, the benchmark retries the request after 10, 30 and 60 seconds, then stops that endpoint. Tasks it didn't get to have no rows.

`fail_stage` says where the last attempt failed: `build` (compiling), `test` (the test harness failed), `time_limit` (building and testing exceeded the 60 s sandbox limit), `no_code` (the reply contained no code), `request` (one of the request-level failures above), `load` (the model failed to load) or `budget` (skipped by `--max-length-finishes`). It's empty when the task passed.

## Go tasks

`go test -race` needs a race-instrumented build of the Go standard library, which takes about 35 s to compile from scratch on a 2-CPU sandbox: over half of the 60 s limit. So when Go tasks are selected, the benchmark first compiles it once into a temporary build cache (about 1–2 minutes, running only trusted code). Each sandbox then sees that cache through an overlay whose writes go to a private tmpfs, so attempts can't change it for each other. This needs bubblewrap 0.11+ and overlayfs in user namespaces (Linux 5.11+); otherwise the benchmark warns and every Go attempt compiles from scratch.

## Sandbox

Model-generated code never runs directly on the host. Each build and test runs inside:

- a **bubblewrap** sandbox with all namespaces unshared (no network), all capabilities dropped and a cleared environment. Only `/usr`, `/bin`, `/lib*`, the Rust toolchain and a read-only copy of the task's files are visible, and everything is written to private tmpfs mounts.
- a transient **systemd user unit** with a memory limit (2 GiB, no swap), a task limit (128), a CPU limit (200 %), a 60 s run time limit and a file-size limit. Before starting the sandbox, a small launcher checks that these cgroup limits were actually applied and refuses to run if not.

If the sandbox is unavailable, the benchmark exits before contacting any server. There is no option to run without it.

## Development

```sh
uv run --locked --no-build --group dev ruff check .
uv run --locked --no-build --group dev pytest -rs
```

The end-to-end tests run scripted replies from a mock OpenAI-compatible server through the real sandbox. They skip themselves where the sandbox isn't available (containers, CI).

To add a task, create its directory under `tasks/`. No code changes are needed. See [AGENTS.md](AGENTS.md) for the conventions tasks follow.

## License

[MIT](LICENSE)
