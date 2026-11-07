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
import http.client
import json
import os
import re
import shlex
import shutil
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
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NamedTuple

# --- CONFIGURATION ---
# Defaults for the command-line options (see --help).
DEFAULT_TIMEOUT_S = 1800       # per request: ~max tokens / slowest model's tok/s (at long context) + load time
DEFAULT_MAX_TOKENS = 16384     # worst-case prompt (~9k tokens) + max tokens must fit in the context window
DEFAULT_ATTEMPTS = 3           # 1 = no feedback; N = initial attempt + N-1 attempts with build/test feedback
MAX_MODEL_ERRORS = 3           # skip the rest of a model after this many request errors in a row
SERVER_RETRY_DELAYS_S = (10, 30, 60)  # waits before retrying while the server is unreachable, then give up
FEEDBACK_CHARS = 6000          # max characters of failing build/test output sent back to the model
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
            "cmds": [["g++", "-std=c++17", "-O1", "-g", "-Wall", *SAN, "-pthread", "test.cpp", "-o", "t"],
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
          "completion_tokens", "seconds", "finish_reason", "fail_stage"]
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
        raise ValueError(f"response from {url} exceeds {MAX_RESPONSE_BYTES} bytes")
    return json.loads(body)


def list_models(name, base, api_key):
    try:
        return [m["id"] for m in http_json(f"{base}/models", timeout=10, api_key=api_key)["data"]]
    except (OSError, http.client.HTTPException, KeyError, TypeError, ValueError) as e:
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


class CmdResult(NamedTuple):
    rc: int
    out: str
    timed_out: bool   # killed at the CMD_TIMEOUT_S time limit


TIME_LIMIT_MARKER = "[killed: exceeded the {limit} s time limit for building and testing]"
ACTIVE_UNITS = set()          # systemd units of running sandboxes, stopped on interrupt
ACTIVE_UNITS_LOCK = threading.Lock()


def stop_active_units():
    with ACTIVE_UNITS_LOCK:
        units = list(ACTIVE_UNITS)
    for unit in units:
        subprocess.run(["systemctl", "--user", "stop", unit], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)


def run_cmd(cmd, cwd):
    """Run only inside a mandatory namespace sandbox and bounded systemd unit."""
    tools = {name: shutil.which(name) for name in ("bwrap", "systemd-run", "systemctl")}
    if not all(tools.values()):
        return CmdResult(-1, "sandbox requires bwrap, systemd-run and systemctl; refusing host execution", False)
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
        with ACTIVE_UNITS_LOCK:
            ACTIVE_UNITS.add(unit)
        t0 = time.monotonic()
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
                    with ACTIVE_UNITS_LOCK:
                        ACTIVE_UNITS.discard(unit)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return CmdResult(-1, f"sandbox failed: {exc}", isinstance(exc, subprocess.TimeoutExpired))
        # systemd kills the unit at RuntimeMaxSec; the exit status alone doesn't say so.
        timed_out = rc != 0 and time.monotonic() - t0 >= CMD_TIMEOUT_S
        output.seek(0)
        data = output.read(MAX_OUTPUT_BYTES + 1)
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_BYTES:
        return CmdResult(-1, text + "\n[output limit exceeded]", False)
    if timed_out:
        text += "\n" + TIME_LIMIT_MARKER.format(limit=CMD_TIMEOUT_S)
    return CmdResult(rc, text, timed_out)


def check_sandbox():
    """Fail before contacting endpoints if namespaces or resource limits do not work."""
    with tempfile.TemporaryDirectory(prefix="llm-sandbox-check-") as directory:
        rc, out, _ = run_cmd(["/usr/bin/true"], Path(directory))
    if rc != 0:
        sys.exit(f"sandbox unavailable; refusing to run generated code:\n{out}")


def feedback(stage, cmd, out):
    """The follow-up message sent to the model after a failed attempt."""
    if stage == "no_code":
        return ("Your reply did not contain any code. Reply with exactly one fenced code block containing the "
                "complete file.")
    if stage == "time_limit":
        head = (f"Your solution was stopped because building and testing it exceeded the {CMD_TIMEOUT_S} s "
                f"time limit. Output of `{cmd}` before it was stopped:")
    else:
        head = f"Your solution failed. Output of `{cmd}`:"
    return (f"{head}\n```\n{clip(out)}\n```\n"
            "Fix the problem. Reply with exactly one fenced code block containing the complete corrected file.")


def run_task(task, code, workdir):
    """Write solution + harness into workdir, build and test in one sandbox.
    Returns (passed, log, fail_stage, failing command, its output); the last three are None on success.
    fail_stage is "build" (a command before the last failed), "test" (the last command failed) or
    "time_limit" (the sandbox was killed at CMD_TIMEOUT_S)."""
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
    rendered = [shlex.join(cmd) for cmd in lang["cmds"]]
    script = []
    for r in rendered:
        script += ["printf '%s\\n' " + shlex.quote(f"$ {r}"), r]
    # Build and execute in one sandbox so private compiler outputs persist only
    # for this attempt. Parent-owned source/transcript files are read-only inputs.
    rc, out, timed_out = run_cmd(["/bin/bash", "-ec", "\n".join(script)], workdir)
    run_log = f"{out}\n[exit {rc}]"
    if rc == 0:
        return True, run_log, None, None, None
    # The failing command is the last one whose "$ cmd" marker appears in the output.
    markers = {f"$ {r}": i for i, r in enumerate(rendered)}
    index = max((markers[line] for line in out.splitlines() if line in markers), default=0)
    if timed_out:
        stage = "time_limit"
    elif index == len(rendered) - 1:
        stage = "test"
    else:
        stage = "build"
    return False, run_log, stage, rendered[index], out


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


class ServerDown(Exception):
    """The endpoint stayed unreachable after all retries."""


class Interrupted(Exception):
    """The run was interrupted (Ctrl-C) while waiting."""


def server_reachable(base, api_key):
    try:
        http_json(f"{base}/models", timeout=10, api_key=api_key)
        return True
    except (OSError, ValueError, http.client.HTTPException):
        return False


def chat(label, base, payload, opts, stop):
    """POST one chat completion. Returns (text, finish_reason, usage, error).
    error is None for a usable reply; otherwise it is the row's finish_reason for a failure that is the
    model's (or its loader's) problem rather than the server's: "timeout", "http_<code>", "bad_response"
    or "disconnected". If the server itself is unreachable, wait and retry the same request; raise
    ServerDown when it stays down, Interrupted if the run is interrupted while waiting."""
    for delay in (*SERVER_RETRY_DELAYS_S, None):
        try:
            resp = http_json(f"{base}/chat/completions", payload, timeout=opts.timeout, api_key=opts.api_key)
        except urllib.error.HTTPError as e:   # the server answered: model failed to load, crashed, prompt too long
            try:
                detail = e.read(500).decode("utf-8", errors="replace").strip()
            except (OSError, http.client.HTTPException):
                detail = ""
            log(f"{label}: HTTP {e.code}: {detail or e.reason}", err=True)
            return "", None, {}, f"http_{e.code}"
        except TimeoutError:   # raised directly only while waiting for the reply: the model was too slow
            log(f"{label}: no reply within {opts.timeout}s", err=True)
            return "", None, {}, "timeout"
        except (OSError, http.client.HTTPException) as e:
            # Refused, reset or dropped connection. If the server still answers, the model process
            # (not the server) died; otherwise wait for the server to come back.
            if server_reachable(base, opts.api_key):
                log(f"{label}: connection lost ({e}), server still reachable", err=True)
                return "", None, {}, "disconnected"
            if delay is None:
                raise ServerDown(str(e)) from e
            log(f"{label}: server unreachable ({e}); retrying in {delay}s", err=True)
            if stop.wait(delay):
                raise Interrupted from None
            continue
        except ValueError as e:   # invalid JSON, truncated body or a reply over MAX_RESPONSE_BYTES
            log(f"{label}: bad response: {e}", err=True)
            return "", None, {}, "bad_response"
        try:
            choice = resp["choices"][0]
            text = choice["message"].get("content") or ""
            if not isinstance(text, str):
                raise TypeError(f"content is {type(text).__name__}")
            usage = resp.get("usage") or {}
            if not isinstance(usage, dict):
                raise TypeError(f"usage is {type(usage).__name__}")
        except (KeyError, IndexError, TypeError, AttributeError) as e:
            log(f"{label}: bad response: {type(e).__name__}: {e}: {json.dumps(resp)[:300]}", err=True)
            return "", None, {}, "bad_response"
        return text, choice.get("finish_reason"), usage, None
    raise AssertionError("unreachable")


# Request-level failures that count towards MAX_MODEL_ERRORS.
MODEL_ERRORS = ("bad_response", "disconnected")


def is_model_error(finish):
    return finish in MODEL_ERRORS or (finish or "").startswith("http_")


def run_one_task(label, base, model, task, taskdir, opts, stop):
    """Run all attempts of one task. Returns the result fields of its CSV row."""
    if taskdir.exists():
        shutil.rmtree(taskdir)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": task["prompt"]},
    ]
    result = {"passed": 0, "passed_on": 0, "attempts": 0, "prompt_tokens": 0, "completion_tokens": 0,
              "seconds": 0.0, "finish_reason": None, "fail_stage": None}
    for attempt in range(1, opts.attempts + 1):
        if stop.is_set():
            raise Interrupted
        payload = {"model": model, "max_tokens": opts.max_tokens, "messages": messages}
        if opts.temperature is not None:
            payload["temperature"] = opts.temperature
        log(f"{label}: attempt {attempt}/{opts.attempts}, waiting for response...", err=True)
        t0 = time.time()
        try:
            text, finish, usage, error = chat(label, base, payload, opts, stop)
        finally:
            result["seconds"] += time.time() - t0
        result["attempts"] = attempt
        if error:
            result["finish_reason"], result["fail_stage"] = error, "request"
            break
        result["finish_reason"] = finish
        result["prompt_tokens"] += usage.get("prompt_tokens") or 0
        result["completion_tokens"] += usage.get("completion_tokens") or 0
        if len(text) > MAX_CONTENT_CHARS:  # counted as failure, nothing written to disk
            log(f"{label}: response exceeds {MAX_CONTENT_CHARS} chars", err=True)
            result["finish_reason"], result["fail_stage"] = "oversized", "request"
            break
        adir = taskdir / f"attempt_{attempt}"
        code = extract_code(text)
        if code.strip():
            passed, run_log, stage, fail_cmd, fail_out = run_task(task, code, adir)
        else:
            adir.mkdir(parents=True)
            passed, run_log, stage, fail_cmd, fail_out = False, "[no code in reply]", "no_code", None, None
        (adir / "response.md").write_text(text)
        (adir / "log.txt").write_text(run_log)
        result["fail_stage"] = stage
        if passed:
            result["passed"], result["passed_on"] = 1, attempt
            break
        if finish == "length":  # hit max tokens: counted as failure, no retry
            break
        messages = messages + [
            {"role": "assistant", "content": THINK_RE.sub("", text).strip()},
            {"role": "user", "content": feedback(stage, fail_cmd, fail_out)},
        ]
    result["seconds"] = round(result["seconds"], 2)
    return result


def run_endpoint(name, base, models, tasks, opts, out_path, runs_dir, rows, stop):
    """Run the tasks for the given models of one endpoint. Appends each row to out_path (and to rows)
    as it completes."""
    new_file = not out_path.exists() or out_path.stat().st_size == 0
    # Rows are written as they complete, so an aborted run keeps every finished model x task.
    with open(out_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
            f.flush()

        def record(model, task, result):
            row = {"endpoint": name, "model": model, "task": task["name"], "lang": task["lang"], **result}
            rows.append(row)
            w.writerow(row)
            f.flush()
            log(str(row))

        try:
            for model in models:
                model_errors = 0   # consecutive tasks that ended in a request-level model error
                for i, task in enumerate(tasks):
                    if model_errors >= MAX_MODEL_ERRORS:
                        log(f"{name}/{model}: {model_errors} request errors in a row; skipping its remaining "
                            f"{len(tasks) - i} task(s)", err=True)
                        for skipped in tasks[i:]:
                            record(model, skipped, {"passed": 0, "passed_on": 0, "attempts": 0,
                                                    "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0,
                                                    "finish_reason": "skipped", "fail_stage": "request"})
                        break
                    taskdir = runs_dir / UNSAFE_NAME_RE.sub("_", model) / task["name"]
                    result = run_one_task(f"{name}/{model}/{task['name']}", base, model, task, taskdir, opts,
                                          stop)
                    model_errors = model_errors + 1 if is_model_error(result["finish_reason"]) else 0
                    record(model, task, result)
        except ServerDown as e:
            log(f"{name}: server unreachable ({e}); stopping this endpoint", err=True)
        except Interrupted:
            pass


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


def check_results_file(path):
    """Results are appended; refuse to mix rows into a file written with different columns."""
    if not path.exists() or path.stat().st_size == 0:
        return
    with open(path, newline="") as f:
        header = next(csv.reader(f), [])
    if header != FIELDS:
        sys.exit(f"{path} has different columns (written by another version?); "
                 f"move it away or use another --tag or --output-dir")


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
    suffix = f"_{args.tag}" if args.tag else ""
    outputs = {name: (args.output_dir / f"results_{name}{suffix}.csv", args.output_dir / "runs" / f"{name}{suffix}")
               for name in plan}
    for csv_path, _ in outputs.values():
        check_results_file(csv_path)

    rows, stop, threads = [], threading.Event(), []
    for name, models in plan.items():
        csv_path, runs_dir = outputs[name]
        # Daemon threads: on Ctrl-C the process exits without waiting for in-flight requests.
        t = threading.Thread(target=run_endpoint, name=name, daemon=True,
                             args=(name, endpoints[name], models, tasks, args, csv_path, runs_dir, rows, stop))
        t.start()
        threads.append(t)
    try:
        for t in threads:
            while t.is_alive():
                t.join(0.5)
    except KeyboardInterrupt:
        stop.set()
        log("interrupted; results so far are in the CSV file(s)", err=True)
        stop_active_units()
        print_summary(list(rows), args.attempts)
        sys.exit(130)
    print_summary(rows, args.attempts)


if __name__ == "__main__":
    main()
