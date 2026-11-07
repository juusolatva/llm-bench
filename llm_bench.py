#!/usr/bin/env python3
"""Benchmark LLMs served over an OpenAI-compatible API on Python, C, C++, Rust, Go and Bash tasks.

Works with any server exposing /v1/models and /v1/chat/completions (Ollama, LM Studio,
llama.cpp server, vLLM, ...). Generated code is built and run against a hidden test harness per task.
Tasks are loaded from tasks/<lang>/<task>/ next to this script (see load_tasks).
Output: results_<endpoint>.csv (one row per model x task) and runs/<endpoint>/<model>/<task>/
attempt_<n>/ (response.md = raw model reply, log.txt = build/test output).
Requires Linux, bubblewrap, a user systemd manager with cgroup v2 limits, and
toolchains on PATH: python3, gcc, g++, rustc, go, bash (+ coreutils/findutils).
Run with --help for usage.
"""
import argparse
import csv
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatchcase
from pathlib import Path

# --- CONFIGURATION ---
# Defaults for the command-line options (see --help).
DEFAULT_TIMEOUT_S = 1800       # per request: ~max tokens / slowest model's tok/s (at long context) + load time
DEFAULT_MAX_TOKENS = 16384     # worst-case prompt (~9k tokens) + max tokens must fit in the context window
DEFAULT_ATTEMPTS = 3           # 1 = no feedback; N = initial attempt + N-1 attempts with build/test feedback
MAX_CONSECUTIVE_FAILURES = 3   # stop an endpoint after this many connection failures in a row
FEEDBACK_CHARS = 6000          # max characters of failing build/test output sent back to the model
FEEDBACK = (
    "Your solution failed. Output of `{cmd}`:\n```\n{out}\n```\n"
    "Fix the problem. Reply with exactly one fenced code block containing the complete corrected file."
)
CMD_TIMEOUT_S = 60
SANDBOX_MEMORY_BYTES = 2 * 1024**3
SANDBOX_TASKS = 128
SANDBOX_TMP_BYTES = 512 * 1024**2
SANDBOX_FILE_BYTES = 64 * 1024**2
MAX_OUTPUT_BYTES = 1024**2
MAX_RESPONSE_BYTES = 8 * 1024**2  # API reply body cap, enforced before JSON parsing
MAX_CONTENT_CHARS = 1024**2        # completion text cap, enforced before anything is written under runs/
# Only the resolved Rust toolchain is exposed, never ~/.cargo or all of ~/.rustup.
RUST_SYSROOT = None

SYSTEM = (
    "You are an expert programmer. Reply with exactly one fenced code block containing the complete "
    "contents of the requested file. Do not include tests, example usage, or a main function."
)

SAN = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
# Per language: task name prefix, solution file, harness file, whether the harness is appended to the
# solution instead of written as its own file (Rust's #[cfg(test)] module), extra files, build/test commands.
LANGS = {
    "python": {"prefix": "py", "sol": "solution.py", "test": "test_solution.py",
               "cmds": [["python3", "test_solution.py"]]},
    "c": {"prefix": "c", "sol": "solution.c", "test": "test.c",
          "cmds": [["gcc", "-std=gnu17", "-O1", "-g", "-Wall", *SAN, "solution.c", "test.c", "-o", "t", "-lm"],
                   ["./t"]]},
    "cpp": {"prefix": "cpp", "sol": "solution.hpp", "test": "test.cpp",
            "cmds": [["g++", "-std=c++20", "-O1", "-g", "-Wall", *SAN, "-pthread", "test.cpp", "-o", "t"],
                     ["./t"]]},
    "rust": {"prefix": "rust", "sol": "lib.rs", "test": "test.rs", "append": True,
             "cmds": [["rustc", "--edition", "2021", "--test", "-O", "-o", "t", "lib.rs"], ["./t"]]},
    "go": {"prefix": "go", "sol": "solution.go", "test": "solution_test.go",
           "extra": {"go.mod": "module solution\n\ngo 1.22\n"},
           "cmds": [["go", "test", "-race", "-count=1", "."]]},
    "bash": {"prefix": "bash", "sol": "solution.sh", "test": "test.sh",
             "cmds": [["bash", "test.sh"]]},
}

# --------------------------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------------------------
# A task is a directory tasks/<lang>/<task>/ containing prompt.md (sent to the model verbatim, surrounding
# whitespace trimmed) and the hidden test harness named LANGS[lang]["test"]. Other files are ignored.
# The task name is "<prefix>_<task>": tasks/python/parse_duration is py_parse_duration.

DEFAULT_TASKS_DIR = Path(__file__).resolve().parent / "tasks"
TASK_DIR_RE = re.compile(r"[a-z0-9][a-z0-9_]*")


def load_tasks(roots):
    """Load the tasks under each root directory. Tasks are ordered by language (LANGS order), then by
    root, then by directory name. Raises ValueError for malformed layouts or duplicate task names."""
    tasks, seen = [], {}
    for root in map(Path, roots):
        if not root.is_dir():
            raise ValueError(f"task directory not found: {root}")
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and entry.name[0] not in "._" and entry.name not in LANGS:
                raise ValueError(f"{entry}: unknown language directory (known: {', '.join(LANGS)})")
        for lang, spec in LANGS.items():
            langdir = root / lang
            if not langdir.is_dir():
                continue
            for taskdir in sorted(p for p in langdir.iterdir() if p.is_dir() and p.name[0] not in "._"):
                if not TASK_DIR_RE.fullmatch(taskdir.name):
                    raise ValueError(f"{taskdir}: task directory names may contain only a-z, 0-9 and _")
                prompt_file, test_file = taskdir / "prompt.md", taskdir / spec["test"]
                for f in (prompt_file, test_file):
                    if not f.is_file():
                        raise ValueError(f"{taskdir}: missing {f.name}")
                name = f"{spec['prefix']}_{taskdir.name}"
                if name in seen:
                    raise ValueError(f"duplicate task {name}: {seen[name]} and {taskdir}")
                seen[name] = taskdir
                prompt = prompt_file.read_text().strip()
                if not prompt:
                    raise ValueError(f"{prompt_file}: empty prompt")
                tasks.append({"name": name, "lang": lang, "prompt": prompt, "test": test_file.read_text()})
    order = list(LANGS)
    return sorted(tasks, key=lambda t: order.index(t["lang"]))   # stable: keeps root and name order

# --------------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------------

FIELDS = ["endpoint", "model", "task", "lang", "passed", "passed_on", "attempts", "prompt_tokens",
          "completion_tokens", "seconds", "finish_reason"]
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
CODE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
VL_RE = re.compile(r"(?<![a-z0-9])vl(?![a-z0-9])")
UNSAFE_NAME_RE = re.compile(r"[^\w.-]")


PRINT_LOCK = threading.Lock()


def log(msg, err=False):
    """Thread-safe line output (one write per line, so lines from different endpoints never interleave)."""
    with PRINT_LOCK:
        f = sys.stderr if err else sys.stdout
        f.write(msg + "\n")
        f.flush()


def http_json(url, payload=None, timeout=60, api_key=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        # Read one byte past the cap so oversized bodies are caught regardless of Content-Length.
        body = r.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise OSError(f"response from {url} exceeds {MAX_RESPONSE_BYTES} bytes")
    return json.loads(body)


def list_models(name, base, api_key):
    try:
        return [m["id"] for m in http_json(f"{base}/models", timeout=10, api_key=api_key)["data"]]
    except (OSError, KeyError, TypeError, ValueError) as e:
        log(f"{name}: skipping, cannot list models at {base}/models: {e}", err=True)
        return []


def default_model_filter(model_id):
    """Skip embedding models and dedicated vision-language variants ("vl" as a separate name token)."""
    lower = model_id.lower()
    return "embed" not in lower and not VL_RE.search(lower)


def parse_endpoint(spec):
    """'[NAME=]URL' -> (name, base URL). A missing scheme becomes http://, a missing path /v1."""
    name, sep, url = spec.partition("=")
    if not sep or "://" in name:
        name, url = "", spec
    if "://" not in url:
        url = "http://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"invalid endpoint {spec!r}: expected [NAME=]http(s)://HOST[:PORT][/PATH]")
    path = parts.path.rstrip("/") or "/v1"
    base = urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    if not name:
        name = parts.hostname if parts.port is None else f"{parts.hostname}_{parts.port}"
    name = UNSAFE_NAME_RE.sub("_", name)
    return name, base


def extract_code(text):
    text = THINK_RE.sub("", text)
    blocks = CODE_RE.findall(text)
    return blocks[-1] if blocks else text


# This trusted launcher runs before bwrap, outside its hidden /sys. Verify that
# systemd actually applied aggregate limits; unsupported controllers must fail closed.
CGROUP_GUARD = """
import os, sys
from pathlib import Path
relative = next(s.split("::", 1)[1] for s in
                Path("/proc/self/cgroup").read_text().splitlines() if s.startswith("0::"))
group = Path("/sys/fs/cgroup") / relative.lstrip("/")
memory = (group / "memory.max").read_text().strip()
tasks = (group / "pids.max").read_text().strip()
swap = (group / "memory.swap.max").read_text().strip()
quota, period = (group / "cpu.max").read_text().split()
if (memory == "max" or not 0 < int(memory) <= int(sys.argv[1])
        or tasks == "max" or not 0 < int(tasks) <= int(sys.argv[2])
        or swap != "0" or quota == "max" or int(quota) > 2 * int(period)):
    raise SystemExit("sandbox cgroup limits are not enforced")
os.execv(sys.argv[3], sys.argv[3:])
"""


def run_cmd(cmd, cwd):
    """Run only inside a mandatory namespace sandbox and bounded systemd unit."""
    tools = {name: shutil.which(name) for name in ("bwrap", "systemd-run", "systemctl")}
    if not all(tools.values()):
        return -1, "sandbox requires bwrap, systemd-run and systemctl; refusing host execution"
    unit = f"llm-bench-{uuid.uuid4().hex}.service"
    sandbox = [tools["bwrap"], "--unshare-all", "--unshare-user", "--disable-userns", "--die-with-parent",
               "--new-session", "--cap-drop", "ALL", "--clearenv"]
    # Expose runtime/toolchain files, not all of /etc, /home, /run or the host root.
    for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/alternatives"):
        if Path(path).exists():
            sandbox += ["--ro-bind", path, path]
    if Path("/etc/ld.so.cache").is_file():
        sandbox += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    if RUST_SYSROOT is not None:
        sandbox += ["--ro-bind", str(RUST_SYSROOT), "/opt/rust"]
    sandbox += ["--proc", "/proc", "--dev", "/dev",
                "--size", str(SANDBOX_TMP_BYTES), "--tmpfs", "/tmp",
                "--size", str(SANDBOX_TMP_BYTES), "--tmpfs", "/work",
                "--ro-bind", str(Path(cwd).resolve()), "/input", "--chdir", "/work"]
    # Preserve system installations such as /usr/local/go/bin, while excluding
    # home/project/relative PATH entries that are not exposed inside the sandbox.
    system_path = [path for path in os.get_exec_path()
                   if Path(path).is_absolute() and Path(path).resolve().is_relative_to("/usr")]
    sandbox_path = ":".join(["/opt/rust/bin", *system_path, "/usr/bin", "/bin"])
    for key, value in {
        "PATH": sandbox_path, "HOME": "/tmp", "TMPDIR": "/tmp", "LC_ALL": "C",
        "GOCACHE": "/tmp/go-cache", "GOPATH": "/tmp/go", "GOPROXY": "off",
        "GOSUMDB": "off", "GOTOOLCHAIN": "local", "GOMAXPROCS": "2",
    }.items():
        sandbox += ["--setenv", key, value]
    # Copy inputs into private tmpfs. Generated files never reach parent reports,
    # including symlinks named response.md/log.txt or compiler-created artifacts.
    sandbox += ["--", "/bin/bash", "-ec",
                'cp -a /input/. /work/\nexec "$@"', "sandbox", *cmd]
    command = [
        tools["systemd-run"], "--user", "--quiet", "--wait", "--pipe", "--collect",
        f"--unit={unit}", f"--property=MemoryMax={SANDBOX_MEMORY_BYTES}",
        "--property=MemorySwapMax=0", f"--property=TasksMax={SANDBOX_TASKS}",
        "--property=CPUQuota=200%", f"--property=RuntimeMaxSec={CMD_TIMEOUT_S}s",
        "--property=TimeoutStopSec=2s", "--property=KillMode=control-group",
        "--property=OOMPolicy=kill", "--property=NoNewPrivileges=yes",
        "--property=LimitCORE=0", f"--property=LimitFSIZE={SANDBOX_FILE_BYTES}",
        sys.executable, "-c", CGROUP_GUARD, str(SANDBOX_MEMORY_BYTES),
        str(SANDBOX_TASKS), *sandbox,
    ]
    # A regular file plus hard LimitFSIZE bounds output without an unbounded
    # communicate() buffer. Read only a bounded prefix back into the parent.
    with tempfile.TemporaryFile() as output:
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT)
            try:
                rc = process.wait(timeout=CMD_TIMEOUT_S + 10)
            finally:
                # Also kill detached descendants after normal completion or interruption.
                try:
                    subprocess.run([tools["systemctl"], "--user", "stop", unit], check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return -1, f"sandbox failed: {exc}"
        output.seek(0)
        data = output.read(MAX_OUTPUT_BYTES + 1)
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_BYTES:
        return -1, text + "\n[output limit exceeded]"
    return rc, text


def check_sandbox():
    """Fail before contacting endpoints if namespaces or resource limits do not work."""
    with tempfile.TemporaryDirectory(prefix="llm-sandbox-check-") as directory:
        rc, out = run_cmd(["/usr/bin/true"], Path(directory))
    if rc != 0:
        sys.exit(f"sandbox unavailable; refusing to run generated code:\n{out}")


def run_task(task, code, workdir):
    """Write solution + harness into workdir, build and test.
    Returns (passed, log, failing command, failing command output)."""
    lang = LANGS[task["lang"]]
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    if lang.get("append"):
        (workdir / lang["sol"]).write_text(code + "\n\n" + task["test"])
    else:
        (workdir / lang["sol"]).write_text(code)
        (workdir / lang["test"]).write_text(task["test"])
    for name, content in lang.get("extra", {}).items():
        (workdir / name).write_text(content)
    commands = []
    for cmd in lang["cmds"]:
        rendered = shlex.join(cmd)
        commands += ["printf '%s\\n' " + shlex.quote(f"$ {rendered}"), rendered]
    # Build and execute in one sandbox so private compiler outputs persist only
    # for this attempt. Parent-owned source/transcript files are read-only inputs.
    rc, out = run_cmd(["/bin/bash", "-ec", "\n".join(commands)], workdir)
    run_log = f"{out}\n[exit {rc}]"
    if rc != 0:
        return False, run_log, "build/test", out
    return True, run_log, None, None


def clip(text, limit=FEEDBACK_CHARS):
    """Keep the head (first errors) and tail (summary) of long output."""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + "\n[... truncated ...]\n" + text[-(limit - head):]


def check_toolchains(tasks):
    """Verify the toolchains needed by the selected tasks only."""
    global RUST_SYSROOT
    langs = {t["lang"] for t in tasks}
    missing = sorted({cmd[0] for lang in langs for cmd in LANGS[lang]["cmds"]
                      if not cmd[0].startswith("./") and shutil.which(cmd[0]) is None})
    if missing:
        sys.exit(f"missing toolchains on PATH: {', '.join(missing)}\n"
                 f"install them or skip their tasks with --task (e.g. --task 'py_*' --task 'c_*')")
    if "rust" not in langs:
        return
    # rustc may be a rustup proxy under ~/.cargo. Expose the actual compiler
    # installation instead of the proxy, user home or rustup configuration.
    try:
        result = subprocess.run(["rustc", "--print", "sysroot"], check=True,
                                capture_output=True, text=True, timeout=10)
        RUST_SYSROOT = Path(result.stdout.strip()).resolve(strict=True)
        if not (RUST_SYSROOT / "bin/rustc").is_file():
            raise ValueError("Rust sysroot does not contain bin/rustc")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit(f"cannot resolve isolated Rust toolchain: {exc}")


def run_endpoint(name, base, models, tasks, opts, out_path, runs_dir):
    """Run the tasks for the given models of one endpoint.
    Appends each row to out_path as it completes; returns the rows."""
    rows = []
    failures = 0          # consecutive connection-level request failures
    # Rows are written as they complete, so an aborted run keeps every finished model x task.
    f = open(out_path, "w", newline="")  # noqa: SIM115 -- closed in the finally below
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    f.flush()
    try:
        for model in models:
            if failures >= MAX_CONSECUTIVE_FAILURES:
                break
            for task in tasks:
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    log(f"{name}: {failures} consecutive request failures, server unreachable; "
                        f"stopping this endpoint", err=True)
                    break
                taskdir = runs_dir / name / UNSAFE_NAME_RE.sub("_", model) / task["name"]
                if taskdir.exists():
                    shutil.rmtree(taskdir)
                messages = [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": task["prompt"]},
                ]
                pt = ct = 0
                secs = 0.0
                passed_on = attempts = 0
                finish = None
                skip = False
                for attempt in range(1, opts.attempts + 1):
                    payload = {
                        "model": model,
                        "max_tokens": opts.max_tokens,
                        "messages": messages,
                    }
                    if opts.temperature is not None:
                        payload["temperature"] = opts.temperature
                    log(f"{name}/{model}/{task['name']}: attempt {attempt}/{opts.attempts}, "
                        f"waiting for response...", err=True)
                    t0 = time.time()
                    try:
                        resp = http_json(f"{base}/chat/completions", payload, timeout=opts.timeout,
                                         api_key=opts.api_key)
                    except OSError as e:
                        secs += time.time() - t0
                        # A bare socket timeout is raised only while waiting for the reply, i.e. the model was
                        # too slow. Connection-level errors (refused, unreachable, connect timeout) arrive wrapped
                        # in URLError: the server is down, which says nothing about the model.
                        if isinstance(e, socket.timeout) and not isinstance(e, urllib.error.URLError):
                            log(f"{name}/{model}/{task['name']}: timed out after {time.time() - t0:.0f}s",
                                err=True)
                            failures = 0  # the server accepted the request, so it is reachable
                            attempts = attempt
                            finish = "timeout"
                        else:
                            log(f"{name}/{model}/{task['name']}: request failed: {e}", err=True)
                            failures += 1
                            skip = True
                        break
                    failures = 0
                    secs += time.time() - t0
                    attempts = attempt
                    choice = resp["choices"][0]
                    text = choice["message"].get("content") or ""
                    finish = choice.get("finish_reason")
                    usage = resp.get("usage") or {}
                    pt += usage.get("prompt_tokens") or 0
                    ct += usage.get("completion_tokens") or 0
                    if len(text) > MAX_CONTENT_CHARS:  # counted as failure, nothing written to disk
                        log(f"{name}/{model}/{task['name']}: response exceeds {MAX_CONTENT_CHARS} chars",
                            err=True)
                        finish = "oversized"
                        break
                    adir = taskdir / f"attempt_{attempt}"
                    passed, run_log, fail_cmd, fail_out = run_task(task, extract_code(text), adir)
                    (adir / "response.md").write_text(text)
                    (adir / "log.txt").write_text(run_log)
                    if passed:
                        passed_on = attempt
                        break
                    if finish == "length":  # hit max tokens: counted as failure, no retry
                        break
                    messages = messages + [
                        {"role": "assistant", "content": THINK_RE.sub("", text).strip()},
                        {"role": "user", "content": FEEDBACK.format(cmd=fail_cmd, out=clip(fail_out))},
                    ]
                if skip:
                    continue
                row = {
                    "endpoint": name,
                    "model": model,
                    "task": task["name"],
                    "lang": task["lang"],
                    "passed": int(passed_on > 0),
                    "passed_on": passed_on,
                    "attempts": attempts,
                    "prompt_tokens": pt,
                    "completion_tokens": ct,
                    "seconds": round(secs, 2),
                    "finish_reason": finish,
                }
                rows.append(row)
                w.writerow(row)
                f.flush()               # keep completed rows on disk if the run is aborted
                log(str(row))
    finally:
        f.close()
    return rows


def print_summary(rows, max_attempts):
    if not rows:
        print("\nno results")
        return
    langs = sorted({r["lang"] for r in rows}, key=list(LANGS).index)
    agg = defaultdict(lambda: {"pass": 0, "p1": 0, "n": 0, "pt": 0, "ct": 0, "s": 0.0,
                               **{lang: [0, 0] for lang in langs}})
    for r in rows:
        a = agg[(r["endpoint"], r["model"])]
        a["pass"] += r["passed"]
        a["p1"] += int(r["passed_on"] == 1)
        a["n"] += 1
        a["pt"] += r["prompt_tokens"]
        a["ct"] += r["completion_tokens"]
        a["s"] += r["seconds"]
        a[r["lang"]][0] += r["passed"]
        a[r["lang"]][1] += 1

    ew = max(8, *(len(e) for e, _ in agg))
    head = (f"\n{'endpoint':{ew}} {'model':40} {'pass@1':>6} {'pass@' + str(max_attempts):>6} "
            + " ".join(f"{lang:>6}" for lang in langs))
    print(head + f" {'prompt_tok':>10} {'compl_tok':>10} {'sec':>8}")
    for (e, m), a in sorted(agg.items(), key=lambda kv: (-kv[1]["pass"], kv[1]["ct"])):
        per = " ".join(f"{a[lang][0]:>4}/{a[lang][1]}" for lang in langs)
        print(f"{e:{ew}} {m[:40]:40} {a['p1']:>3}/{a['n']:<2} {a['pass']:>3}/{a['n']:<2} {per} "
              f"{a['pt']:>10} {a['ct']:>10} {a['s']:>8.1f}")


def positive_int(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


EPILOG = """\
examples:
  %(prog)s http://localhost:11434/v1                       # Ollama
  %(prog)s localhost:1234                                  # LM Studio (/v1 is added)
  %(prog)s box1=gpu-box-1:11434 box2=gpu-box-2:1234        # two servers in parallel
  %(prog)s localhost:8080 -m 'qwen*' --task 'py_*' --task 'rust_*'
  %(prog)s localhost:11434 --tasks-dir ~/my-tasks           # private tasks instead of the built-in ones
  %(prog)s --list-tasks

Endpoints can also be given in the LLM_BENCH_ENDPOINTS environment variable (space-separated).
The API key is read from --api-key, LLM_BENCH_API_KEY or OPENAI_API_KEY, in that order.
"""


def parse_args():
    ap = argparse.ArgumentParser(
        description="Benchmark LLMs served over an OpenAI-compatible API on Python, C, C++, Rust, Go "
                    "and Bash coding tasks. Generated code is built and tested in a sandbox.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("endpoints", nargs="*", metavar="[NAME=]URL",
                    help="OpenAI-compatible base URL(s), e.g. http://localhost:11434/v1. NAME labels the "
                         "endpoint in output (default: HOST_PORT). Multiple endpoints run in parallel")
    ap.add_argument("-m", "--model", action="append", default=[], metavar="PATTERN",
                    help="run only models whose ID matches PATTERN: an exact ID or a shell glob such as "
                         "'google/gemma-4-12b*' (quote it). Repeatable. Default: all models except "
                         "embedding and vision-language (\"vl\") models")
    ap.add_argument("--task", action="append", default=[], metavar="PATTERN",
                    help="run only tasks whose name matches PATTERN (shell glob, e.g. 'py_*'). Repeatable")
    ap.add_argument("--list-tasks", action="store_true", help="list task names and exit")
    ap.add_argument("--tasks-dir", action="append", type=Path, default=[], metavar="DIR",
                    help="load tasks from DIR (same layout as the built-in tasks/ directory) instead of the "
                         "built-in tasks. Repeatable; also pass the built-in directory to combine them")
    ap.add_argument("--api-key", help="bearer token sent to every endpoint")
    ap.add_argument("--timeout", type=positive_int, default=DEFAULT_TIMEOUT_S, metavar="SEC",
                    help="per-request timeout; must cover model load time plus generating max tokens "
                         "on the slowest model (default: %(default)s)")
    ap.add_argument("--max-tokens", type=positive_int, default=DEFAULT_MAX_TOKENS, metavar="N",
                    help="completion token limit per request; prompt (up to ~9k tokens with feedback) + N "
                         "must fit in the model's context window (default: %(default)s)")
    ap.add_argument("--attempts", type=positive_int, default=DEFAULT_ATTEMPTS, metavar="N",
                    help="1 = no feedback; N = first attempt + N-1 retries with build/test output as "
                         "feedback (default: %(default)s)")
    ap.add_argument("--temperature", type=float, metavar="T",
                    help="sampling temperature (default: the server's/model's default)")
    ap.add_argument("-o", "--output-dir", type=Path, default=Path("."), metavar="DIR",
                    help="where results_<endpoint>.csv and runs/ are written (default: current directory)")
    ap.add_argument("-t", "--tag",
                    help="write results_<endpoint>_<TAG>.csv instead of results_<endpoint>.csv")
    args = ap.parse_args()
    if not args.endpoints:
        args.endpoints = os.environ.get("LLM_BENCH_ENDPOINTS", "").split()
    if not args.endpoints and not args.list_tasks:
        ap.error("no endpoint given (e.g. http://localhost:11434/v1 for Ollama, "
                 "http://localhost:1234/v1 for LM Studio)")
    args.api_key = args.api_key or os.environ.get("LLM_BENCH_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if args.tag:
        args.tag = UNSAFE_NAME_RE.sub("_", args.tag)
    return args


def main():
    args = parse_args()
    try:
        all_tasks = load_tasks(args.tasks_dir or [DEFAULT_TASKS_DIR])
    except (OSError, UnicodeDecodeError, ValueError) as e:
        sys.exit(f"cannot load tasks: {e}")
    tasks = [t for t in all_tasks if not args.task or any(fnmatchcase(t["name"], p) for p in args.task)]
    if args.list_tasks:
        for t in tasks:
            print(f"{t['name']:24} {t['lang']}")
        return
    for p in args.task:
        if not any(fnmatchcase(t["name"], p) for t in all_tasks):
            log(f"warning: task pattern {p!r} matched no task (see --list-tasks)", err=True)
    if not tasks:
        sys.exit("no tasks selected")

    endpoints = {}
    for spec in args.endpoints:
        try:
            name, base = parse_endpoint(spec)
        except ValueError as e:
            sys.exit(str(e))
        if name in endpoints:
            sys.exit(f"duplicate endpoint name {name!r}; label them with NAME=URL")
        endpoints[name] = base

    check_toolchains(tasks)
    check_sandbox()

    plan = {}
    for name, base in endpoints.items():
        ids = list_models(name, base, args.api_key)
        if args.model:
            models = [m for m in ids if any(fnmatchcase(m, p) for p in args.model)]
        else:
            models = [m for m in ids if default_model_filter(m)]
        if models:
            plan[name] = models
            log(f"{name} ({base}): {len(models)} model(s): {', '.join(models)}", err=True)
    for p in args.model:
        if not any(fnmatchcase(m, p) for models in plan.values() for m in models):
            log(f"warning: pattern {p!r} matched no model", err=True)
    if not plan:
        sys.exit("no models selected")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = args.output_dir / "runs"
    suffix = f"_{args.tag}" if args.tag else ""
    with ThreadPoolExecutor(max_workers=len(plan)) as ex:
        futures = [ex.submit(run_endpoint, name, endpoints[name], models, tasks, args,
                             args.output_dir / f"results_{name}{suffix}.csv", runs_dir)
                   for name, models in plan.items()]
        rows = [r for fut in futures for r in fut.result()]
    print_summary(rows, args.attempts)


if __name__ == "__main__":
    main()
