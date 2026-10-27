"""The Council in your browser: python -m council --web

A tiny local web app (standard library only). It listens on 127.0.0.1, so only
this PC can open it. Ask a question, watch each member answer, read the verdict.
"""

import json
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .clients import make_client, pick_roster
from .config import load_config, load_raw
from .council import Council, validate_question

PAGE = Path(__file__).with_name("web.html")
MAX_BODY = 64 * 1024

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _seat(o) -> dict:
    return {"name": o.seat.name, "model": o.seat.model, "answer": o.answer, "error": o.error}


def _run(job_id: str, question: str, roster: str) -> None:
    job = _jobs[job_id]

    def update(**fields):
        with _lock:
            job.update(fields)

    def on_opinion(o):
        with _lock:
            job["opinions"].append(_seat(o))

    try:
        config = load_config(roster)
        update(seats=[s.name for s in config.members], status="preparing")
        client = make_client(config)  # may start Ollama / download models the first time
        update(status="asking")
        result = Council(config, client).convene(question, on_opinion=on_opinion)
        update(status="done", verdict=result.verdict)
    except Exception as e:  # shown on the page instead of a silent hang
        update(status="error", error=str(e))


def start_job(question: str, roster: str) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "status": "starting",
            "roster": roster,
            "question": question,
            "seats": [],
            "opinions": [],
            "verdict": None,
            "error": None,
        }
    threading.Thread(target=_run, args=(job_id, question, roster), daemon=True).start()
    return job_id


class Handler(BaseHTTPRequestHandler):
    server_version = "Council"

    def log_message(self, *args):  # keep the terminal quiet
        pass

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding: a web page on another site can't pose as localhost.
        port = self.server.server_address[1]
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, code: int, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        if self.path == "/":
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/info":
            rosters = list(load_raw()["rosters"])
            return self._send(200, {"rosters": rosters, "default": self.server.default_roster})
        if self.path.startswith("/api/job/"):
            with _lock:
                job = _jobs.get(self.path.rsplit("/", 1)[-1])
                snapshot = json.loads(json.dumps(job)) if job else None
            return self._send(200 if snapshot else 404, snapshot or {"error": "no such job"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # JSON-only: browsers can't send this cross-site without a preflight we never answer.
        if not self._host_ok() or self.headers.get("Content-Type") != "application/json":
            return self._send(403, {"error": "forbidden"})
        if self.path != "/api/ask":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": "question too long"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            roster = body.get("roster") or self.server.default_roster
            if roster not in load_raw()["rosters"]:
                raise ValueError(f"Unknown roster '{roster}'.")
            question = validate_question(
                str(body.get("question", "")), load_config(roster).max_prompt_chars
            )
        except (ValueError, json.JSONDecodeError) as e:
            return self._send(400, {"error": str(e)})
        self._send(200, {"id": start_job(question, roster)})


def serve(roster: str | None = None, port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.default_roster = pick_roster(roster)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"AI Universal Council is open at {url}  (close this window to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
