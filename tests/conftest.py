import json
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import llm_bench


@dataclass
class Reply:
    """A scripted chat reply other than a plain successful completion."""
    text: str = ""            # normal completion text (after an optional sleep)
    status: int = 200         # with body: raw HTTP status
    body: bytes | None = None  # raw response body instead of a completion
    length: int | None = None  # Content-Length to announce (larger than body = truncated reply)
    close: bool = False       # drop the connection without a response
    sleep: float = 0          # delay before answering


class MockServer:
    """Minimal OpenAI-compatible server. `replies` (str or Reply) is consumed one per chat request."""

    def __init__(self, models=("test/model",), replies=(), api_key=None):
        self.models = list(models)
        self.replies = list(replies)
        self.api_key = api_key
        self.requests = []
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

            def do_GET(self):
                if not self._authorized():
                    return
                if self.path == "/v1/models":
                    self._send(200, {"data": [{"id": m} for m in server.models]})
                else:
                    self._send(404, {})

            def do_POST(self):
                if not self._authorized():
                    return
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests.append(req)
                reply = server.replies.pop(0) if server.replies else ""
                if isinstance(reply, Reply):
                    if reply.sleep:
                        time.sleep(reply.sleep)
                    if reply.close:   # drop the connection without answering
                        self.close_connection = True
                        return
                    if reply.body is not None:
                        self.send_response(reply.status)
                        self.send_header("Content-Length", str(reply.length or len(reply.body)))
                        self.end_headers()
                        self.wfile.write(reply.body)
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
