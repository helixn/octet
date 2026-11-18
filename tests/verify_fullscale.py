"""Full-scale end-to-end verification: the GPU computed a full OctetHash
attempt at genesis parameters (4 GiB dataset / 128 MiB cache / 4096 lanes /
16 rounds, nonce from meta_full.json). This script recomputes the final hash
with the pure-Python reference (light path: 256... 128 MiB cache, no dataset)
and compares — bit-exact or the GPU implementation is broken.

Runtime: ~1-3 minutes (the cache chain alone is 2^21 sequential hashes in
Python). Run AFTER `octet_test.exe full` has written tests/fullscale/."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reference.octet_ref import (  # noqa: E402
    FULL_SCALE as P,
    block_seed,
    epoch_seed,
    gen_cache,
    solve,
)

DUMP = Path(__file__).resolve().parent / "fullscale"


def main() -> int:
    meta = json.loads((DUMP / "meta_full.json").read_text(encoding="utf-8"))
    assert meta["dataset_items"] == P["dataset_items"], "profile mismatch"
    assert meta["cache_words"] == P["cache_words"], "profile mismatch"
    header = bytes.fromhex(meta["header_hex"])
    nonce = meta["nonce"]

    t0 = time.time()
    seed_epoch = epoch_seed(0, b"\x11" * 32)
    seed_block = block_seed(b"\x22" * 32, 1)
    print(f"[1/3] building cache: {P['cache_words']} words ...", flush=True)
    cache = gen_cache(seed_epoch, P["cache_words"])
    print(f"      done in {time.time() - t0:.1f} s", flush=True)

    print("[2/3] light-path solve (derives every item from cache) ...",
          flush=True)
    t1 = time.time()
    final = solve(header, nonce, cache, seed_epoch, seed_block, P)
    print(f"      done in {time.time() - t1:.1f} s  final={final.hex()}",
          flush=True)

    gpu_final = (DUMP / "full_final.bin").read_bytes()
    gpu_hex = meta["final_hex"]
    print(f"[3/3] GPU final  = {gpu_final.hex()}")
    if final == gpu_final and final.hex() == gpu_hex:
        print("VERIFY: PASS — GPU full-scale pipeline is bit-exact with the "
              "reference oracle")
        return 0
    print("VERIFY: FAIL — GPU and reference disagree")
    return 1


if __name__ == "__main__":
    sys.exit(main())
