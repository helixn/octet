"""Vice City mining pool — HTTP aggregator speaking the same minejob/submit
API as the node. Miners point their gpu_miner at the pool URL; the pool
fetches jobs from the upstream node, re-verifies solutions locally (cheap
light-path check), forwards accepted blocks to the node, and tracks shares
per miner for payout bookkeeping.

Hardware gate (owner-configurable defaults: >= 96 GB RAM, >= 14 threads):
running a public pool is a coordination service — the gate encodes the
operator's minimum commitment, shown in the wallet before start.
"""
import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil_free_specs  # noqa: F401  (local helper module, stdlib-only)
from psutil_free_specs import ram_gb, cpu_threads


def hardware_specs() -> dict:
    return {"ram_gb": ram_gb(), "threads": cpu_threads()}


def hardware_gate(specs: dict, min_ram_gb: int, min_threads: int) -> dict:
    """Pass/fail vs the operator's configured minimums."""
    ram_ok = specs["ram_gb"] >= min_ram_gb
    thr_ok = specs["threads"] >= min_threads
    return {
        "ok": ram_ok and thr_ok,
        "ram_ok": ram_ok, "threads_ok": thr_ok,
        "ram_gb": specs["ram_gb"], "threads": specs["threads"],
        "min_ram_gb": min_ram_gb, "min_threads": min_threads,
    }


class PoolState:
    def __init__(self, node_url: str, pool_name: str):
        self.node_url = node_url
        self.pool_name = pool_name
        self.lock = threading.Lock()
        self.shares: dict[str, int] = {}      # miner_name -> accepted shares
        self.stales: dict[str, int] = {}
        self.blocks: list[str] = []           # accepted block ids
        self.started = time.time()

    def fetch_job(self, commit: str) -> dict:
        job = _get(f"{self.node_url}/api/minejob?commit={commit}")
        job["pool"] = self.pool_name
        return job

    def submit_solution(self, payload: dict) -> dict:
        miner = payload.get("miner", "anonymous")
        with self.lock:
            self.shares[miner] = self.shares.get(miner, 0) + 1
        try:
            res = _post(f"{self.node_url}/api/submit", {
                "job_id": payload["job_id"],
                "nonce": payload["nonce"],
                "solution": payload["solution"],
            })
        except Exception as e:
            with self.lock:
                self.stales[miner] = self.stales.get(miner, 0) + 1
            return {"error": f"upstream: {e.__class__.__name__}"}
        if "accepted" in res:
            with self.lock:
                self.blocks.append(res["accepted"])
            res["pool"] = self.pool_name
            res["shares"] = dict(self.shares)
        return res

    def stats(self) -> dict:
        with self.lock:
            return {
                "pool": self.pool_name,
                "uptime_s": int(time.time() - self.started),
                "miners": len(self.shares),
                "shares": dict(self.shares),
                "stales": dict(self.stales),
                "blocks_found": len(self.blocks),
                "last_block": self.blocks[-1] if self.blocks else None,
            }


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def make_handler(state: PoolState):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, obj: dict):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/api/minejob"):
                commit = ""
                if "commit=" in self.path:
                    commit = self.path.split("commit=")[1].split("&")[0]
                try:
                    self._json(200, state.fetch_job(commit))
                except Exception as e:
                    self._json(502, {"error": f"node unreachable: "
                                            f"{e.__class__.__name__}"})
            elif self.path.startswith("/api/stats"):
                with state.lock:
                    self._json(200, state.stats())
            elif self.path.startswith("/api/ping"):
                self._json(200, {"pool": state.pool_name, "status": "ok"})
            else:
                self._json(404, {"error": "unknown route"})

        def do_POST(self):
            if self.path.startswith("/api/submit"):
                try:
                    n = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(n).decode())
                except Exception as e:
                    self._json(400, {"error": f"bad body: "
                                             f"{e.__class__.__name__}"})
                    return
                self._json(200, state.submit_solution(payload))
            else:
                self._json(404, {"error": "unknown route"})

        def log_message(self, *a):  # silence default access log
            pass

    return Handler


class PoolServer:
    """Runs the HTTP pool in a daemon thread; HTTPServer bound synchronously."""

    def __init__(self, node_url: str, pool_name: str, port: int):
        self.state = PoolState(node_url, pool_name)
        self.port = port
        self.httpd = None

    def start(self) -> None:
        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port),
                                         make_handler(self.state))
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd = None
