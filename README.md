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
- [bubblewrap](https://github.com/containers/bubblewrap) 0.8 or newer (`bwrap`).
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
| `--temperature T` | server default | Sampling temperature. |
| `-o, --output-dir DIR` | `.` | Where results and transcripts are written. |
| `-t, --tag TAG` | | Write `results_<endpoint>_<TAG>.csv`, so runs with different settings don't overwrite each other. |

### Server setup tips

- **Context length.** With the defaults a request can need about 25k tokens of context. Configure the server for at least 32k. Many servers default to much less and silently truncate the prompt. For example, Ollama uses `OLLAMA_CONTEXT_LENGTH=32768`, and LM Studio sets the context length in the model's load settings.
- **One model at a time.** Models are benchmarked one after another. If the server keeps earlier models loaded, the next model may not fit in VRAM and run partly on the CPU, which only affects timing. Let the server evict old models: Ollama with `OLLAMA_MAX_LOADED_MODELS=1`, LM Studio with the auto-evict option for JIT-loaded models.
- **Thinking models.** `<think>…</think>` blocks are removed before code extraction. Reasoning returned in a separate field is ignored. Reasoning tokens still count toward `--max-tokens`, so raise it if replies end with `finish_reason=length`.

## Output

- `results_<endpoint>[_<tag>].csv`: one row per model × task, written as each task finishes, so an interrupted run keeps its results. Rows are **appended**, so re-running a few models adds to an existing file instead of replacing it. Re-running the same model and task adds another row; the later row is the newer result. Columns: `endpoint, model, task, lang, passed, passed_on, attempts, prompt_tokens, completion_tokens, seconds, finish_reason, fail_stage`. The benchmark refuses to append to a file that has different columns (e.g. from an older version).
- `runs/<endpoint>[_<tag>]/<model>/<task>/attempt_<n>/`: `response.md` (raw model reply), `log.txt` (build/test output), and the files that were tested. Re-running a model and task replaces its transcripts for the same tag.
- A summary table on stdout, with pass@1 (passed on the first attempt), pass@N (passed within `--attempts`), per-language results, token counts and total time per model. Ctrl-C stops the run promptly and still prints the summary of the tasks finished so far.

`finish_reason` is the server's value for the last reply (`stop`, `length`, …) or one of these:

| Value | Meaning |
|---|---|
| `timeout` | No reply within `--timeout`. |
| `http_<code>` | The server returned an HTTP error, e.g. the model failed to load or crashed, or the prompt didn't fit its context. |
| `bad_response` | The reply wasn't a valid chat completion (invalid or truncated JSON, no `choices`, …). |
| `disconnected` | The connection dropped while the server itself stayed reachable (typically a crashed model process). |
| `oversized` | The reply text exceeded 1 MiB. |
| `skipped` | Not attempted: the model had 3 request errors (`http_*`, `bad_response`, `disconnected`) in a row, so its remaining tasks were skipped. |

If the server itself becomes unreachable, the benchmark retries the request after 10, 30 and 60 seconds, then stops that endpoint. Tasks it didn't get to have no rows.

`fail_stage` says where the last attempt failed: `build` (compiling), `test` (the test harness failed), `time_limit` (building and testing exceeded the 60 s sandbox limit), `no_code` (the reply contained no code), or `request` (one of the request-level failures above). It's empty when the task passed.

## Sandbox

Model-generated code never runs directly on the host. Each build and test runs inside:

- a **bubblewrap** sandbox with all namespaces unshared (no network), all capabilities dropped and a cleared environment. Only `/usr`, `/bin`, `/lib*`, the Rust toolchain and a read-only copy of the task's files are visible, and everything is written to private tmpfs mounts.
- a transient **systemd user unit** with a memory limit (2 GiB, no swap), a task limit (128), a CPU limit (200 %), a 60 s run time limit and a file-size limit. Before starting the sandbox, a small launcher checks that these cgroup limits were actually applied and refuses to run if not.

If the sandbox is unavailable, the benchmark exits before contacting any server. There is no option to run without it.

## Development

```sh
uv run --locked --group dev ruff check .
uv run --locked --group dev pytest -rs
```

The end-to-end tests run scripted replies from a mock OpenAI-compatible server through the real sandbox. They skip themselves where the sandbox isn't available (containers, CI).

To add a task, create its directory under `tasks/`. No code changes are needed. See [AGENTS.md](AGENTS.md) for the conventions tasks follow.

## License

[MIT](LICENSE)
