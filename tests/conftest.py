import json
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import llm_bench

# Transcript directory of MockServer's default model "test/model" ("/" isn't safe, so the name is hashed).
MODEL_DIR = llm_bench.model_dirs(["test/model"])["test/model"]


@dataclass
class Reply:
    """A scripted chat reply other than a plain successful completion."""
    text: str = ""            # normal completion text (after an optional sleep)
    status: int = 200         # with body: raw HTTP status
    body: bytes | None = None  # raw response body instead of a completion
    length: int | None = None  # Content-Length to announce (larger than body = truncated reply)
    close: bool = False       # drop the connection without a response
    sleep: float = 0          # delay before answering
    headers: dict | None = None  # with body: extra response headers (e.g. Location for a redirect)
    hold: float = 0           # with body: keep the connection open this long after the body (a stalled reply)


class MockServer:
    """Minimal OpenAI-compatible server. `replies` (str or Reply) is consumed one per chat request.

    Probe requests (max_tokens=1: the warm-up and context check) don't consume replies and are kept in
    `probes`. They report one prompt token per word plus 10; `context` caps the reported count (a server
    that truncates prompts), `reject_over` answers HTTP 400 above that many tokens, and `probe_reply`
    (a Reply) replaces the answer to every probe (e.g. a model that fails to load); a list of Replies answers
    the probes in order, the last one repeating. `models_reply` (a Reply) replaces the answer to GET /models.
    The paths of GET requests are kept in `gets`."""

    def __init__(self, models=("test/model",), replies=(), api_key=None, context=None, reject_over=None,
                 probe_reply=None, models_reply=None):
        self.models = list(models)
        self.replies = list(replies)
        self.api_key = api_key
        self.context = context
        self.reject_over = reject_over
        self.probe_reply = list(probe_reply) if isinstance(probe_reply, list) else probe_reply
        self.models_reply = models_reply
        self.gets = []
        self.requests = []
        self.probes = []
        self.stopping = threading.Event()   # ends held replies
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002 -- keep the base signature
                pass

            def _send(self, status, obj):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self):
                if server.api_key and self.headers.get("Authorization") != f"Bearer {server.api_key}":
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def _send_reply(self, reply):
                """Answer with a scripted Reply; False if it's a plain completion text the caller must send."""
                if reply.sleep:
                    time.sleep(reply.sleep)
                if reply.close:   # drop the connection without answering
                    self.close_connection = True
                    return True
                if reply.body is None:
                    return False
                self.send_response(reply.status)
                for name, value in (reply.headers or {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(reply.length or len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)
                if reply.hold:
                    self.wfile.flush()
                    server.stopping.wait(reply.hold)
                return True

            def do_GET(self):
                server.gets.append(self.path)
                if not self._authorized():
                    return
                if server.models_reply is not None:
                    self._send_reply(server.models_reply)
                elif self.path == "/v1/models":
                    self._send(200, {"data": [{"id": m} for m in server.models]})
                else:
                    self._send(404, {})

            def do_POST(self):
                if not self._authorized():
                    return
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if req.get("max_tokens") == 1:
                    server.probes.append(req)
                    if server.probe_reply is None:
                        tokens = 10 + sum(len(m["content"].split()) for m in req["messages"])
                        if server.reject_over and tokens > server.reject_over:
                            self._send(400, {"error": "prompt exceeds context length"})
                            return
                        if server.context:
                            tokens = min(tokens, server.context)
                        self._send(200, {"choices": [{"message": {"content": "OK"}, "finish_reason": "length"}],
                                         "usage": {"prompt_tokens": tokens, "completion_tokens": 1}})
                        return
                    reply = server.probe_reply
                    if isinstance(reply, list):
                        reply = reply.pop(0) if len(reply) > 1 else reply[0]
                else:
                    server.requests.append(req)
                    reply = server.replies.pop(0) if server.replies else ""
                if isinstance(reply, Reply):
                    if self._send_reply(reply):
                        return
                    reply = reply.text
                self._send(200, {"choices": [{"message": {"content": reply}, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stopping.set()
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def mock_server():
    servers = []

    def start(**kwargs):
        s = MockServer(**kwargs).__enter__()
        servers.append(s)
        return s

    yield start
    for s in servers:
        s.__exit__(None, None, None)


def _sandbox_available():
    with tempfile.TemporaryDirectory() as d:
        return llm_bench.run_cmd(["/usr/bin/true"], Path(d)).rc == 0


SANDBOX_OK = _sandbox_available()


def pytest_collection_modifyitems(config, items):
    if SANDBOX_OK:
        return
    skip = pytest.mark.skip(reason="bwrap + systemd user sandbox not available")
    for item in items:
        if "sandbox" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def go_cache():
    """Warm the Go build cache once, like a real run does, so Go tasks stay under the time limit."""
    try:
        tasks = llm_bench.load_tasks([llm_bench.DEFAULT_TASKS_DIR])
        llm_bench.check_toolchains([t for t in tasks if t["lang"] == "go"])
    except SystemExit as exc:
        pytest.skip(str(exc))
    with tempfile.TemporaryDirectory(prefix="llm-bench-test-go-") as d:
        llm_bench.prepare_go_cache(d)
        if llm_bench.GO_CACHE is None:
            pytest.fail("warming the Go build cache failed (see the warning above); without it Go tasks "
                        "compile the standard library each time and hit the time limit")
        yield
        llm_bench.GO_CACHE = None
