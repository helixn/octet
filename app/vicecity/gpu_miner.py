"""Vice City GPU miner — connects to a vicd node, mines minejobs with the
CUDA solver, submits solutions. Testnet profile (fast). The wallet commit
comes from %APPDATA%/ViceCity/wallet.json (or --commit hex).

Usage: python -m app.vicecity.gpu_miner [--node http://127.0.0.1:9332]
                                        [--batch 50000] [--gpu N]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

MINER_EXE = Path(__file__).resolve().parents[2] / "cuda" / "octet_test.exe"
WALLET_FILE = Path(os.environ.get("APPDATA", str(Path.home()))) / "ViceCity" / "wallet.json"


def http_json(url: str, payload: dict | None = None, timeout: int = 10):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def wallet_commit() -> str:
    w = json.loads(WALLET_FILE.read_text(encoding="utf-8"))
    vk = bytes.fromhex(w["vk_hex"])
    return hashlib.blake2b(vk, digest_size=32).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default="http://127.0.0.1:9332")
    ap.add_argument("--batch", type=int, default=200_000)
    ap.add_argument("--commit", default=None, help="mining commit (hex)")
    args = ap.parse_args()

    commit = args.commit or wallet_commit()
    print(f"Vice City GPU miner | node {args.node} | commit {commit[:16]}…")
    print(f"wallet: {WALLET_FILE} | miner: {MINER_EXE}")
    if not MINER_EXE.exists():
        print("miner binary missing — build cuda first")
        return 2

    blocks_mined = 0
    while True:
        try:
            info = http_json(f"{args.node}/api/info")
            job = http_json(f"{args.node}/api/minejob?commit={commit}")
        except Exception as e:
            print(f"[node unreachable: {e}] retrying in 3 s")
            time.sleep(3)
            continue

        height = job["height"]
        print(f"job {job['job_id']} height {height} target {job['target'][:12]}…",
              flush=True)
        t0 = time.time()
        r = subprocess.run(
            [str(MINER_EXE), "mine", job["pow_header"], job["seed_block"],
             job["target"], "0", str(args.batch)],
            capture_output=True, text=True, timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = r.stdout.strip()
        if not out.startswith("FOUND"):
            print(f"  no solution in {args.batch} attempts "
                  f"({time.time() - t0:.1f} s) — new job")
            continue
        _, nonce, solution = out.split()
        dt = time.time() - t0
        try:
            res = http_json(f"{args.node}/api/submit",
                            {"job_id": job["job_id"], "nonce": int(nonce),
                             "solution": solution}, timeout=30)
        except Exception as e:
            print(f"  submit failed: {e}")
            continue
        if "accepted" in res:
            blocks_mined += 1
            rate = int(nonce) / dt if dt > 0 else 0
            print(f"  ★ BLOCK ACCEPTED {res['accepted'][:16]}… "
                  f"nonce {nonce} in {dt:.1f} s ({rate:.0f} att/s) "
                  f"— total {blocks_mined}")
        else:
            print(f"  rejected: {res.get('error')}")


if __name__ == "__main__":
    sys.exit(main())
