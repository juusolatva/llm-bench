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
import hashlib
import http.client
import json
import math
import os
import random
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
from collections import Counter, defaultdict
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NamedTuple

# --- CONFIGURATION ---
# Part of every row's config hash: bump it whenever a change can change results (prompting, feedback,
# code extraction, build/test handling), so rows from different versions are never mixed.
BENCH_VERSION = "0.4.0"
# Defaults for the command-line options (see --help).
DEFAULT_TIMEOUT_S = 1800       # per request: ~max tokens / slowest model's tok/s (at long context) + load time
DEFAULT_MAX_TOKENS = 16384     # worst-case prompt (~9k tokens) + max tokens must fit in the context window
DEFAULT_ATTEMPTS = 3           # 1 = no feedback; N = initial attempt + N-1 attempts with build/test feedback
MAX_MODEL_ERRORS = 3           # skip the rest of a model after this many request errors in a row
SERVER_RETRY_DELAYS_S = (10, 30, 60)  # waits before retrying while the server is unreachable, then give up
# Context check: a run needs roughly BASE + (attempts - 1) * PER_RETRY + max tokens of context
# (system + task prompt; each retry adds the previous reply and the clipped build/test output).
CONTEXT_BASE_TOKENS = 1000
CONTEXT_PER_RETRY_TOKENS = 4000
CONTEXT_CALIBRATION_WORDS = 2000   # filler words used to measure the tokenizer's tokens per word
CONTEXT_TOLERANCE = 0.95           # reported prompt tokens below this share of the expected count = truncated
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
BASH = "/bin/bash"
LD_SO_CACHE = "/etc/ld.so.cache"
GO_CACHE_MOUNT = "/opt/go-cache"   # where sandboxes see the Go build cache
# Host directory with a pre-built Go build cache (race-instrumented standard library), shown to each sandbox
# through a throwaway overlay so attempts can't change it for each other. None: every sandbox starts empty.
GO_CACHE = None
GO_CACHE_WARM_TIMEOUT_S = 900   # warming compiles the whole standard library once, with -race

SYSTEM = (
    "You are an expert programmer. Reply with exactly one fenced code block containing the complete "
    "contents of the requested file. Do not include tests, example usage, or a main function."
)

SAN = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
# Per language: task name prefix, solution file, harness file, code block language tags (preferred by
# extract_code), whether the harness is appended to the solution instead of written as its own file (Rust's
# #[cfg(test)] module), extra files, build/test commands.
LANGS = {
    "python": {"prefix": "py", "sol": "solution.py", "test": "test_solution.py", "tags": ("python", "py", "python3"),
               "cmds": [["python3", "test_solution.py"]]},
    "c": {"prefix": "c", "sol": "solution.c", "test": "test.c", "tags": ("c", "h"),
          "cmds": [["gcc", "-std=gnu17", "-O1", "-g", "-Wall", *SAN, "solution.c", "test.c", "-o", "t", "-lm"],
                   ["./t"]]},
    "cpp": {"prefix": "cpp", "sol": "solution.hpp", "test": "test.cpp", "tags": ("cpp", "c++", "cxx", "cc", "hpp", "h++"),
            "cmds": [["g++", "-std=c++17", "-O1", "-g", "-Wall", *SAN, "-pthread", "test.cpp", "-o", "t"],
                     ["./t"]]},
    "rust": {"prefix": "rust", "sol": "lib.rs", "test": "test.rs", "tags": ("rust", "rs"), "append": True,
             "cmds": [["rustc", "--edition", "2021", "--test", "-O", "-o", "t", "lib.rs"], ["./t"]]},
    "go": {"prefix": "go", "sol": "solution.go", "test": "solution_test.go", "tags": ("go", "golang"),
           "extra": {"go.mod": "module solution\n\ngo 1.22\n"},
           "cmds": [["go", "test", "-race", "-count=1", "."]]},
    "bash": {"prefix": "bash", "sol": "solution.sh", "test": "test.sh", "tags": ("bash", "sh", "shell"),
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

FIELDS = ["run_id", "endpoint", "model", "task", "lang", "repeat", "passed", "passed_on", "attempts",
          "prompt_tokens", "completion_tokens", "seconds", "load_seconds", "finish_reason", "fail_stage", "context",
          "params", "settings", "config"]
RESERVED_PARAMS = {"model", "messages", "max_tokens", "stream", "n"}
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# A fenced block: an opening fence with an optional info string (its first word is the language tag) and a
# closing fence, each on its own line (indentation allowed).
CODE_RE = re.compile(r"^[ \t]*```[ \t]*([^\s`]*)[^\n`]*\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)
VL_RE = re.compile(r"(?<![a-z0-9])vl(?![a-z0-9])")
UNSAFE_NAME_RE = re.compile(r"[^\w.-]")


def safe_name(name):
    """A single path component derived from a model, endpoint or tag name: unsafe characters become "_",
    and a leading dot too, so the result is never "", "." or ".." (or a hidden file)."""
    return re.sub(r"^\.", "_", UNSAFE_NAME_RE.sub("_", name)) or "_"


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
    return safe_name(name), base


def _in_code(text, pos):
    return any(m.start() <= pos < m.end() for m in CODE_RE.finditer(text))


def strip_think(text):
    """Remove reasoning: <think>...</think> blocks, everything before an unpaired </think> (servers that
    drop the opening tag) and everything after an unclosed <think> (reasoning cut off by max_tokens).
    Tags inside fenced code blocks are part of the code and kept."""
    text = THINK_RE.sub(lambda m: m.group(0) if _in_code(text, m.start()) else "", text)
    closes = [m.start() for m in re.finditer("</think>", text) if not _in_code(text, m.start())]
    if closes:
        text = text[closes[-1] + len("</think>"):]
    opens = [m.start() for m in re.finditer("<think>", text) if not _in_code(text, m.start())]
    return text[:opens[0]] if opens else text


def extract_code(text, lang=None):
    """The solution in a reply: the longest fenced block tagged with one of the language's tags (any block
    if none is tagged so), the last one on ties. A reply without a fenced block is taken as code."""
    text = strip_think(text)
    blocks = CODE_RE.findall(text)
    if not blocks:
        return text
    tags = LANGS[lang]["tags"] if lang else ()
    candidates = [code for tag, code in blocks if tag.lower() in tags] or [code for _, code in blocks]
    return max(reversed(candidates), key=lambda code: len(code.strip()))


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


def run_cmd(cmd, cwd, timeout=None, go_cache_rw=None):
    """Run only inside a mandatory namespace sandbox and bounded systemd unit.
    timeout: run time limit (default CMD_TIMEOUT_S). go_cache_rw: host directory mounted writable as the Go
    build cache, used only to warm GO_CACHE with trusted code; otherwise GO_CACHE (if set) is mounted as an
    overlay whose writes go to a private tmpfs."""
    timeout = timeout or CMD_TIMEOUT_S
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
    if Path(LD_SO_CACHE).is_file():
        sandbox += ["--ro-bind", LD_SO_CACHE, LD_SO_CACHE]
    if RUST_SYSROOT is not None:
        sandbox += ["--ro-bind", str(RUST_SYSROOT), "/opt/rust"]
    sandbox += ["--proc", "/proc", "--dev", "/dev",
                "--size", str(SANDBOX_TMP_BYTES), "--tmpfs", "/tmp",
                "--size", str(SANDBOX_TMP_BYTES), "--tmpfs", "/work",
                "--ro-bind", str(Path(cwd).resolve()), "/input", "--chdir", "/work"]
    if go_cache_rw is not None:
        sandbox += ["--bind", str(go_cache_rw), GO_CACHE_MOUNT]
    elif GO_CACHE is not None:
        sandbox += ["--overlay-src", str(GO_CACHE), "--tmp-overlay", GO_CACHE_MOUNT]
    # Preserve system installations such as /usr/local/go/bin, while excluding
    # home/project/relative PATH entries that are not exposed inside the sandbox.
    system_path = [path for path in os.get_exec_path()
                   if Path(path).is_absolute() and Path(path).resolve().is_relative_to("/usr")]
    sandbox_path = ":".join(["/opt/rust/bin", *system_path, "/usr/bin", "/bin"])
    for key, value in {
        "PATH": sandbox_path, "HOME": "/tmp", "TMPDIR": "/tmp", "LC_ALL": "C",
        "GOCACHE": GO_CACHE_MOUNT if go_cache_rw is not None or GO_CACHE is not None else "/tmp/go-cache",
        "GOPATH": "/tmp/go", "GOPROXY": "off",
        "GOSUMDB": "off", "GOTOOLCHAIN": "local", "GOMAXPROCS": "2",
    }.items():
        sandbox += ["--setenv", key, value]
    # Copy inputs into private tmpfs. Generated files never reach parent reports,
    # including symlinks named response.md/log.txt or compiler-created artifacts.
    sandbox += ["--", BASH, "-ec",
                'cp -a /input/. /work/\nexec "$@"', "sandbox", *cmd]
    command = [
        tools["systemd-run"], "--user", "--quiet", "--wait", "--pipe", "--collect",
        f"--unit={unit}", f"--property=MemoryMax={SANDBOX_MEMORY_BYTES}",
        "--property=MemorySwapMax=0", f"--property=TasksMax={SANDBOX_TASKS}",
        "--property=CPUQuota=200%", f"--property=RuntimeMaxSec={timeout}s",
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
                rc = process.wait(timeout=timeout + 10)
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
        timed_out = rc != 0 and time.monotonic() - t0 >= timeout
        output.seek(0)
        data = output.read(MAX_OUTPUT_BYTES + 1)
    text = data[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_BYTES:
        return CmdResult(-1, text + "\n[output limit exceeded]", False)
    if timed_out:
        text += "\n" + TIME_LIMIT_MARKER.format(limit=timeout)
    return CmdResult(rc, text, timed_out)


def check_sandbox():
    """Fail before contacting endpoints if namespaces or resource limits do not work."""
    with tempfile.TemporaryDirectory(prefix="llm-sandbox-check-") as directory:
        rc, out, _ = run_cmd(["/usr/bin/true"], Path(directory))
    if rc != 0:
        sys.exit(f"sandbox unavailable; refusing to run generated code:\n{out}")


GO_WARM_TEST = """package solution

import (
	"testing"
)

func TestWarm(t *testing.T) {}
"""


def prepare_go_cache(directory):
    """Warm a Go build cache in `directory` and enable it for all sandboxes (sets GO_CACHE).
    Only trusted code runs while the cache is writable: `go build -race std` and an empty test package.
    Falls back to an empty cache per sandbox (with a warning) if overlays or warming don't work."""
    global GO_CACHE
    directory = Path(directory)
    work = directory / "warm-src"
    cache = directory / "cache"
    work.mkdir()
    cache.mkdir()
    for name, content in LANGS["go"].get("extra", {}).items():
        (work / name).write_text(content)
    (work / "solution_test.go").write_text(GO_WARM_TEST)
    log("go: warming the build cache (race-instrumented standard library), this takes a minute...", err=True)
    t0 = time.monotonic()
    warm = run_cmd([BASH, "-ec", "go build -race std\n" + shlex.join(LANGS["go"]["cmds"][-1])], work,
                   timeout=GO_CACHE_WARM_TIMEOUT_S, go_cache_rw=cache)
    if warm.rc != 0:
        log(f"go: warning: warming the build cache failed; each Go attempt compiles the standard library "
            f"from scratch and may hit the {CMD_TIMEOUT_S} s limit:\n{clip(warm.out)}", err=True)
        return
    GO_CACHE = cache
    probe = run_cmd([BASH, "-ec", f"touch {GO_CACHE_MOUNT}/llm-bench-probe\n"
                     + shlex.join(LANGS["go"]["cmds"][-1])], work)
    if probe.rc != 0 or (cache / "llm-bench-probe").exists():
        GO_CACHE = None
        log("go: warning: the warmed build cache can't be mounted as a private overlay (needs bubblewrap 0.11+ "
            f"and overlayfs in user namespaces); each Go attempt compiles the standard library from scratch "
            f"and may hit the {CMD_TIMEOUT_S} s limit:\n{clip(probe.out)}", err=True)
        return
    log(f"go: build cache ready in {time.monotonic() - t0:.0f}s", err=True)


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
    rc, out, timed_out = run_cmd([BASH, "-ec", "\n".join(script)], workdir)
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
        payload = {**opts.params, "model": model, "max_tokens": opts.max_tokens, "messages": messages}
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
        code = extract_code(text, task["lang"])
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
            {"role": "assistant", "content": strip_think(text).strip()},
            {"role": "user", "content": feedback(stage, fail_cmd, fail_out)},
        ]
    result["seconds"] = round(result["seconds"], 2)
    return result


def context_needed(opts):
    return CONTEXT_BASE_TOKENS + (opts.attempts - 1) * CONTEXT_PER_RETRY_TOKENS + opts.max_tokens


FILLER_WORDS = (  # noqa: SIM905 -- easier to read than a list literal
    "time year people way day man thing woman life child world school state family student group country "
    "problem hand part place case week company system program question work number night point home water "
    "room mother area money story fact month lot right study book eye job word business issue side kind head "
    "house service friend father power hour game line end member law car city community name team minute idea "
    "body information back parent face level office door health person art history party result change "
    "morning reason research girl moment air teacher force education"
).split()


def filler(words):
    rng = random.Random(words)
    return " ".join(rng.choice(FILLER_WORDS) for _ in range(words))


def probe(label, base, model, content, opts, stop):
    payload = {**opts.params, "model": model, "max_tokens": 1, "messages": [{"role": "user", "content": content}]}
    return chat(label, base, payload, opts, stop)


def check_context(label, base, model, opts, stop, base_tokens):
    """Check that the model's context holds context_needed(opts) tokens. Tokenizers differ, so first
    measure tokens per filler word, then send a prompt of the needed size and compare the prompt tokens
    the server reports. Returns "ok", "short:<reported tokens>", "rejected:<error>" or "unchecked"."""
    need = context_needed(opts)
    prefix = "Reply with OK. Ignore the following text.\n\n"
    _, _, usage, error = probe(label, base, model, prefix + filler(CONTEXT_CALIBRATION_WORDS), opts, stop)
    sample_tokens = usage.get("prompt_tokens")
    if error and error.startswith("http_"):   # even the short calibration prompt doesn't fit
        log(f"{label}: warning: the server rejected a ~{CONTEXT_CALIBRATION_WORDS}-word prompt ({error}); the "
            f"context is far below the {need} tokens needed", err=True)
        return f"rejected:{error}"
    if error or not base_tokens or not sample_tokens or sample_tokens <= base_tokens:
        log(f"{label}: warning: can't check the context size ({error or 'the server reports no token usage'})",
            err=True)
        return "unchecked"
    per_word = (sample_tokens - base_tokens) / CONTEXT_CALIBRATION_WORDS
    words = math.ceil((need - base_tokens) / per_word)
    expected = base_tokens + per_word * words
    log(f"{label}: checking that the context holds {need} tokens...", err=True)
    _, _, usage, error = probe(label, base, model, prefix + filler(words), opts, stop)
    if error:
        log(f"{label}: warning: the server rejected a {need}-token prompt ({error}); the context is probably "
            f"smaller. Raise the server's context length or lower --max-tokens / --attempts", err=True)
        return f"rejected:{error}"
    got = usage.get("prompt_tokens") or 0
    if got < CONTEXT_TOLERANCE * expected:
        log(f"{label}: warning: the context holds only about {got} of the {need} tokens needed; long replies and "
            f"retries will be cut off. Raise the server's context length or lower --max-tokens / --attempts",
            err=True)
        return f"short:{got}"
    return "ok"


def prepare_model(label, base, model, opts, stop):
    """Load the model with a tiny request, so load time isn't counted against its first task, and check its
    context size unless disabled. Returns (load_seconds, context, error)."""
    log(f"{label}: loading...", err=True)
    t0 = time.time()
    _, _, usage, error = probe(label, base, model, "Reply with OK.", opts, stop)
    load_seconds = round(time.time() - t0, 2)
    if error:
        return load_seconds, "unchecked", error
    log(f"{label}: first reply after {load_seconds:.1f}s", err=True)
    if not opts.context_check:
        return load_seconds, "unchecked", None
    return load_seconds, check_context(label, base, model, opts, stop, usage.get("prompt_tokens")), None


def settings_fingerprint(opts):
    """Everything besides the task itself that can change a result."""
    return {"version": BENCH_VERSION, "system": SYSTEM, "max_tokens": opts.max_tokens, "attempts": opts.attempts,
            "params": opts.params, "timeout": opts.timeout, "cmd_timeout": CMD_TIMEOUT_S,
            "feedback_chars": FEEDBACK_CHARS, "sandbox": [SANDBOX_MEMORY_BYTES, SANDBOX_TASKS, SANDBOX_TMP_BYTES,
                                                         SANDBOX_FILE_BYTES]}


def settings_hash(settings):
    """Short hash of the settings alone: rows of one model with equal hashes can be summarized together."""
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:12]


def config_hash(settings, task):
    """Short hash of the settings plus this task's prompt, harness and language spec: rows with equal hashes
    were produced under the same conditions."""
    data = {"settings": settings, "task": {k: task[k] for k in ("name", "lang", "prompt", "test")},
            "lang": LANGS[task["lang"]]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


def skipped_result(finish_reason, fail_stage):
    return {"passed": 0, "passed_on": 0, "attempts": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "seconds": 0.0, "finish_reason": finish_reason, "fail_stage": fail_stage}


INT_FIELDS = ("repeat", "passed", "passed_on", "attempts", "prompt_tokens", "completion_tokens")
FLOAT_FIELDS = ("seconds", "load_seconds")
# Rows with these finish reasons failed for reasons outside the model's answer; --resume runs them again.
RETRY_FINISHES = ("bad_response", "disconnected", "skipped")


def read_results(path):
    """Rows of a results CSV, numeric fields converted. Files from older versions are accepted: missing
    columns get defaults (repeat 1, empty strings) and an old "backend" column is read as "endpoint"."""
    rows = []
    with open(path, newline="") as f:
        for raw in csv.DictReader(f):
            row = {k: v for k, v in raw.items() if k is not None}
            if "endpoint" not in row and "backend" in row:
                row["endpoint"] = row.pop("backend")
            missing = {"endpoint", "model", "task", "lang", "passed", "passed_on"} - row.keys()
            if missing:
                raise ValueError(f"{path}: not a results file (missing columns: {', '.join(sorted(missing))})")
            for k in INT_FIELDS:
                row[k] = int(row.get(k) or (1 if k == "repeat" else 0))
            for k in FLOAT_FIELDS:
                row[k] = float(row.get(k) or 0)
            for k in FIELDS:
                if row.get(k) is None:
                    row[k] = ""
            rows.append(row)
    return rows


def is_finished(row):
    finish = row.get("finish_reason") or ""
    return not (finish in RETRY_FINISHES or finish.startswith("http_"))


def run_endpoint(name, base, models, tasks, opts, out_path, runs_dir, rows, stop):
    """Run every task opts.repeat times for each model of one endpoint (with opts.resume, only the runs not
    yet finished in out_path). Appends each row to out_path (and to rows) as it completes."""
    existing = []
    if out_path.exists() and out_path.stat().st_size > 0:
        existing = [r for r in read_results(out_path) if r["endpoint"] == name]
    # Repeat numbers continue after the rows already in the file, so transcripts are never overwritten.
    numbered = Counter((r["model"], r["task"], r["config"]) for r in existing)
    finished = Counter((r["model"], r["task"], r["config"]) for r in existing if is_finished(r))
    new_file = not existing and (not out_path.exists() or out_path.stat().st_size == 0)
    # Rows are written as they complete, so an aborted run keeps every finished model x task.
    with open(out_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
            f.flush()

        params = json.dumps(opts.params, sort_keys=True, separators=(",", ":"))

        def record(model, task, result, model_info):
            key = (model, task["name"], task["config"])
            numbered[key] += 1
            row = {"run_id": opts.run_id, "endpoint": name, "model": model, "task": task["name"],
                   "lang": task["lang"], "repeat": numbered[key], **result, **model_info, "params": params,
                   "settings": opts.settings_hash, "config": task["config"]}
            rows.append(row)
            w.writerow(row)
            f.flush()
            log(str(row))

        def skip_rest(model, todo, why, finish_reason, fail_stage, model_info):
            log(f"{name}/{model}: {why}; skipping its remaining {len(todo)} run(s)", err=True)
            for task in todo:
                record(model, task, skipped_result(finish_reason, fail_stage), model_info)

        try:
            for model in models:
                # Repeat-major order: one full pass over the tasks finishes before the second one starts.
                todo = [task for rep in range(opts.repeat) for task in tasks
                        if not opts.resume or finished[(model, task["name"], task["config"])] <= rep]
                total = opts.repeat * len(tasks)
                if not todo:
                    log(f"{name}/{model}: all {total} run(s) already in {out_path}; skipping", err=True)
                    continue
                if len(todo) < total:
                    log(f"{name}/{model}: resuming, {len(todo)} of {total} run(s) to go", err=True)
                load_seconds, context, error = prepare_model(f"{name}/{model}", base, model, opts, stop)
                model_info = {"load_seconds": load_seconds, "context": context}
                if error:
                    skip_rest(model, todo, f"loading failed ({error})", error, "load", model_info)
                    continue
                model_errors = 0     # consecutive runs that ended in a request-level model error
                length_finishes = 0  # runs whose last reply hit --max-tokens
                for i, task in enumerate(todo):
                    if model_errors >= MAX_MODEL_ERRORS:
                        skip_rest(model, todo[i:], f"{model_errors} request errors in a row", "skipped", "request",
                                  model_info)
                        break
                    if opts.max_length_finishes and length_finishes >= opts.max_length_finishes:
                        skip_rest(model, todo[i:], f"{length_finishes} replies hit --max-tokens", "skipped",
                                  "budget", model_info)
                        break
                    repeat = numbered[(model, task["name"], task["config"])] + 1
                    label = f"{name}/{model}/{task['name']}" + (f"#{repeat}" if opts.repeat > 1 else "")
                    taskdir = runs_dir / safe_name(model) / task["name"] / f"repeat_{repeat}"
                    result = run_one_task(label, base, model, task, taskdir, opts, stop)
                    model_errors = model_errors + 1 if is_model_error(result["finish_reason"]) else 0
                    length_finishes += result["finish_reason"] == "length"
                    record(model, task, result, model_info)
        except ServerDown as e:
            log(f"{name}: server unreachable ({e}); stopping this endpoint", err=True)
        except Interrupted:
            pass


def summarize(rows):
    """Aggregate rows per (endpoint, model, settings). For each task only the rows with its newest config
    (the last one seen) count; several rows of a task are repeats. Returns (groups, dropped row count)."""
    tasks_by_group = {}
    dropped = 0
    for r in rows:
        group = tasks_by_group.setdefault((r["endpoint"], r["model"], r.get("settings") or ""), {})
        config, task_rows = group.get(r["task"], (None, []))
        if config is not None and config != r.get("config"):
            dropped += len(task_rows)
            task_rows = []
        group[r["task"]] = (r.get("config"), [*task_rows, r])
    groups = []
    for (endpoint, model, settings), tasks in tasks_by_group.items():
        g = {"endpoint": endpoint, "model": model, "settings": settings, "n": len(tasks), "p1": 0.0, "pass": 0.0,
             "var1": 0.0, "var": 0.0, "pt": 0.0, "ct": 0.0, "s": 0.0, "load": 0.0, "langs": defaultdict(lambda: [0.0, 0]),
             "runs": [], "context": "unchecked"}
        for task_rows in (task_rows for _, task_rows in tasks.values()):
            n = len(task_rows)
            p1 = sum(r["passed_on"] == 1 for r in task_rows) / n
            p = sum(r["passed"] for r in task_rows) / n
            g["p1"] += p1
            g["pass"] += p
            # Variance of one run's score: a sum of per-task Bernoulli variables (unbiased estimate).
            correction = n / (n - 1) if n > 1 else 0.0
            g["var1"] += p1 * (1 - p1) * correction
            g["var"] += p * (1 - p) * correction
            g["pt"] += sum(r["prompt_tokens"] for r in task_rows) / n
            g["ct"] += sum(r["completion_tokens"] for r in task_rows) / n
            g["s"] += sum(r["seconds"] for r in task_rows) / n
            g["load"] = max(g["load"], *(r.get("load_seconds") or 0.0 for r in task_rows))
            lang = g["langs"][task_rows[0]["lang"]]
            lang[0] += p
            lang[1] += 1
            g["runs"].append(n)
            if task_rows[-1].get("context"):
                g["context"] = task_rows[-1]["context"]
        groups.append(g)
    return groups, dropped


def print_summary(rows):
    if not rows:
        print("\nno results")
        return
    groups, dropped = summarize(rows)
    repeated = any(n > 1 for g in groups for n in g["runs"])
    show_settings = len({g["settings"] for g in groups}) > 1
    langs = sorted({lang for g in groups for lang in g["langs"]}, key=lambda x: list(LANGS).index(x)
                   if x in LANGS else len(LANGS))

    def score(value, var, n):
        return f"{value:.1f}±{math.sqrt(var):.1f}/{n}" if repeated else f"{round(value)}/{n}"

    def lang_cell(value, n):
        return f"{value:.1f}/{n}" if repeated else f"{round(value)}/{n}"

    ew = max(8, *(len(g["endpoint"]) for g in groups))
    sw = 12 if repeated else 6
    head = f"\n{'endpoint':{ew}} {'model':40} " + (f"{'settings':12} " if show_settings else "")
    head += (f"{'runs':>5} " if repeated else "") + f"{'pass@1':>{sw}} {'passed':>{sw}} "
    print(head + " ".join(f"{lang:>7}" for lang in langs)
          + f" {'prompt_tok':>10} {'compl_tok':>10} {'sec':>8} {'load':>6}")
    for g in sorted(groups, key=lambda g: (-g["pass"], -g["p1"], g["ct"])):
        line = f"{g['endpoint']:{ew}} {g['model'][:40]:40} " + (f"{g['settings']:12} " if show_settings else "")
        if repeated:
            lo, hi = min(g["runs"]), max(g["runs"])
            line += f"{lo if lo == hi else f'{lo}-{hi}':>5} "
        line += f"{score(g['p1'], g['var1'], g['n']):>{sw}} {score(g['pass'], g['var'], g['n']):>{sw}} "
        line += " ".join(f"{lang_cell(*g['langs'][lang]) if lang in g['langs'] else '-':>7}" for lang in langs)
        print(line + f" {g['pt']:>10.0f} {g['ct']:>10.0f} {g['s']:>8.1f} {g['load']:>6.1f}")
    notes = []
    if repeated:
        notes.append("with repeats: mean passes per run ± the standard deviation of one run's score; tokens and "
                     "seconds are means per run")
    if dropped:
        notes.append(f"{dropped} row(s) from older versions of a task or of the benchmark were left out")
    failed = [f"{g['endpoint']}/{g['model']} ({g['context']})" for g in groups
              if g["context"] not in ("ok", "unchecked")]
    if failed:
        notes.append(f"warning: context check failed, results may be cut off: {', '.join(failed)}")
    for note in notes:
        print(f"\n{note}")


def parse_param(spec):
    """KEY=VALUE -> (key, value); VALUE is parsed as JSON if possible (numbers, true/false, lists), else a string."""
    key, sep, value = spec.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {spec!r}")
    try:
        return key, json.loads(value)
    except json.JSONDecodeError:
        return key, value


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
                    help="sampling temperature (default: the server's/model's default); same as --param temperature=T")
    ap.add_argument("--param", action="append", type=parse_param, default=[], metavar="KEY=VALUE",
                    help="extra request parameter, e.g. top_p=0.9 or seed=1 (VALUE is parsed as JSON when "
                         "possible). Repeatable. Recorded in the results")
    ap.add_argument("--repeat", type=positive_int, default=1, metavar="K",
                    help="run every task K times per model, to measure how much results vary (default: 1)")
    ap.add_argument("--resume", action="store_true",
                    help="skip runs that already have a finished row with the same settings and task version in "
                         "the results file; rows that failed on request errors are run again")
    ap.add_argument("--max-length-finishes", type=positive_int, metavar="K",
                    help="skip a model's remaining runs after K of its runs ended with a reply cut off at "
                         "--max-tokens (default: never)")
    ap.add_argument("--summary", nargs="+", type=Path, metavar="CSV",
                    help="print the summary table of existing results files and exit (no endpoint needed)")
    ap.add_argument("--no-context-check", dest="context_check", action="store_false",
                    help="skip checking that each model's context holds a worst-case run (saves one long "
                         "prompt per model)")
    ap.add_argument("-o", "--output-dir", type=Path, default=Path("."), metavar="DIR",
                    help="where results_<endpoint>.csv and runs/ are written (default: current directory)")
    ap.add_argument("-t", "--tag",
                    help="write results_<endpoint>_<TAG>.csv instead of results_<endpoint>.csv")
    args = ap.parse_args()
    if not args.endpoints:
        args.endpoints = os.environ.get("LLM_BENCH_ENDPOINTS", "").split()
    if not args.endpoints and not args.list_tasks and not args.summary:
        ap.error("no endpoint given (e.g. http://localhost:11434/v1 for Ollama, "
                 "http://localhost:1234/v1 for LM Studio)")
    args.api_key = args.api_key or os.environ.get("LLM_BENCH_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if args.tag:
        args.tag = safe_name(args.tag)
    args.params = dict(args.param)
    if args.temperature is not None and args.params.get("temperature", args.temperature) != args.temperature:
        ap.error("--temperature conflicts with --param temperature=...")
    if args.temperature is not None:
        args.params["temperature"] = args.temperature
    reserved = sorted(RESERVED_PARAMS & args.params.keys())
    if reserved:
        ap.error(f"--param can't set {', '.join(reserved)}")
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
    try:
        read_results(path)
    except (ValueError, csv.Error) as e:   # UnicodeDecodeError is a ValueError
        sys.exit(f"cannot read {path}: {e}")


def main():
    args = parse_args()
    if args.summary:
        try:
            rows = [r for path in args.summary for r in read_results(path)]
        except (OSError, ValueError, csv.Error) as e:   # UnicodeDecodeError is a ValueError
            sys.exit(f"cannot read results: {e}")
        print_summary(rows)
        return
    try:
        all_tasks = load_tasks(args.tasks_dir or [DEFAULT_TASKS_DIR])
    except (OSError, ValueError) as e:   # UnicodeDecodeError is a ValueError
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
    args.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    settings = settings_fingerprint(args)
    args.settings_hash = settings_hash(settings)
    tasks = [{**t, "config": config_hash(settings, t)} for t in tasks]

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
    go_tmp = None
    if any(t["lang"] == "go" for t in tasks):
        go_tmp = tempfile.TemporaryDirectory(prefix="llm-bench-go-")
        prepare_go_cache(go_tmp.name)
    try:
        run_all(args, plan, endpoints, tasks, outputs)
    finally:
        if go_tmp is not None:
            go_tmp.cleanup()


def run_all(args, plan, endpoints, tasks, outputs):
    """Run every endpoint in its own thread; print the summary at the end or on Ctrl-C."""
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
        print_summary(list(rows))
        sys.exit(130)
    if args.resume:   # show the complete picture, not just the runs added now
        rows = [r for name, (csv_path, _) in outputs.items() if csv_path.exists()
                for r in read_results(csv_path) if r["endpoint"] == name]
    print_summary(rows)


if __name__ == "__main__":
    main()
