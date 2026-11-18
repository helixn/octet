#!/usr/bin/env python3
"""
OctetHash reference implementation (spec v0.2 draft; math identical to v0.1) — pure Python, stdlib only.

This is the SPECIFICATION IN CODE: correctness and clarity first, speed last.
It runs on reduced profiles (see PROFILES) so tests stay fast; the full-scale
parameters live in docs/pow.md and are meant for the CUDA solver.

Two evaluation paths exist and MUST agree:
  * light path  — dataset items derived from the 256 MiB cache + keystream
                  (used by nodes to verify, and by this reference everywhere)
  * miner path  — a precomputed effective dataset (cache-derived items XORed
                  with the block keystream, stored in RAM/VRAM)
tests/test_octet_ref.py asserts both paths produce identical results.

Domain separation: every hash input starts with a fixed ASCII tag
("octet-cache", "octet-epoch", "octet-block", "octet-pow", "lane") so that fields
can never collide across roles.
"""

import hashlib
import json
import struct
from pathlib import Path

# ---------------------------------------------------------------------------
# profiles: full scale is documented in docs/pow.md; reference runs small
# ---------------------------------------------------------------------------

FULL_SCALE = {
    "cache_words": 1 << 22,      # 256 MiB / 64 B
    "dataset_items": 1 << 25,    # 8 GiB / 256 B
    "item_parents": 32,
    "lanes": 4096,
    "lanes_per_block": 1024,
    "rounds": 16,
}

TEST_PROFILE = {
    "cache_words": 2048,         # 128 KiB
    "dataset_items": 4096,       # 1 MiB of dataset
    "item_parents": 8,
    "lanes": 256,
    "lanes_per_block": 256,
    "rounds": 8,
}


def le64(n: int) -> bytes:
    return struct.pack("<Q", n)


def _h(*parts: bytes, size: int = 64) -> bytes:
    hh = hashlib.blake2b(digest_size=size)
    for p in parts:
        hh.update(p)
    return hh.digest()


# ---------------------------------------------------------------------------
# cache (per epoch)
# ---------------------------------------------------------------------------

def epoch_seed(epoch: int, epoch_seed_hash: bytes) -> bytes:
    return _h(b"octet-epoch", le64(epoch), epoch_seed_hash)


def gen_cache(seed_epoch: bytes, cache_words: int) -> list:
    """Sequentially dependent fill: parallel generation needs log2 rounds."""
    cache = [b""] * cache_words
    prev = _h(b"octet-cache", seed_epoch)
    cache[0] = prev
    for i in range(1, cache_words):
        prev = _h(prev, seed_epoch, le64(i))
        cache[i] = prev
    return cache


# ---------------------------------------------------------------------------
# dataset items: base form, per-block keystream, effective form
# ---------------------------------------------------------------------------

def dataset_item(j: int, cache, seed_epoch: bytes, item_parents: int) -> bytes:
    """Base dataset item j (256 B): ITEM_PARENTS cache words mixed through a
    BLAKE2b chain. ~ITEM_PARENTS+5 hashes: storing beats deriving per access."""
    acc = _h(seed_epoch, le64(j))
    for k in range(item_parents):
        p = int.from_bytes(
            _h(seed_epoch, le64(j), le64(k), size=8), "big") % len(cache)
        acc = _h(acc, cache[p])
    # 4 × 64 B digest = 256 B item (BLAKE2b caps digest at 64 B)
    return b"".join(_h(acc, le64(c)) for c in range(4))


def keystream_item(j: int, seed_block: bytes) -> bytes:
    """Per-block re-keying stream for item j (256 B)."""
    return b"".join(_h(seed_block, le64(j), le64(c)) for c in range(4))


def effective_item(j: int, cache, seed_epoch: bytes, item_parents: int,
                   seed_block: bytes) -> bytes:
    """item_eff = item_base ⊕ keystream — what a miner's dataset holds."""
    it = dataset_item(j, cache, seed_epoch, item_parents)
    ks = keystream_item(j, seed_block)
    return bytes(a ^ b for a, b in zip(it, ks))


def build_effective_dataset(cache, seed_epoch: bytes, item_parents: int,
                            seed_block: bytes, dataset_items: int) -> dict:
    """The miner path: precompute the effective dataset (test-scale only)."""
    return {j: effective_item(j, cache, seed_epoch, item_parents, seed_block)
            for j in range(dataset_items)}


# ---------------------------------------------------------------------------
# proof of work
# ---------------------------------------------------------------------------

def block_seed(prev_solution_hash: bytes, height: int) -> bytes:
    return _h(b"octet-block", prev_solution_hash, le64(height))


def _solve(header: bytes, nonce: int, cache, seed_epoch: bytes,
           seed_block: bytes, P: dict, dataset: dict = None,
           states_log: list = None):
    """Core search. dataset=None evaluates the light path (derive every item
    from cache+keystream); dataset=dict reads precomputed effective items.
    states_log (optional): appends the initial lane states and the state
    array after every round — used only by vector export, never changes math."""
    lanes = P["lanes"]
    rounds = P["rounds"]
    block_lanes = P["lanes_per_block"]
    dataset_items = P["dataset_items"]
    parents = P["item_parents"]
    stride_bits = block_lanes.bit_length() - 1  # butterfly stays in-block

    seed = _h(b"octet-pow", header, le64(nonce), size=32)
    states = [_h(b"lane", seed, le64(i), size=32) for i in range(lanes)]
    if states_log is not None:
        states_log.append(b"".join(states))

    for r in range(rounds):
        # read phase: one uniformly random 256 B dataset item per lane
        items = []
        for i in range(lanes):
            addr = int.from_bytes(states[i][:4], "big") % dataset_items
            if dataset is not None:
                items.append(dataset[addr])
            else:
                items.append(effective_item(addr, cache, seed_epoch,
                                            parents, seed_block))
        for i in range(lanes):
            states[i] = _h(states[i], items[i], size=32)
        # butterfly exchange (simultaneous: snapshot then XOR)
        b = r % stride_bits
        prev = states
        states = [bytes(a ^ q for a, q in zip(prev[i],
                                              prev[i ^ (1 << b)]))
                  for i in range(lanes)]
        if states_log is not None:
            states_log.append(b"".join(states))

    final = _h(b"".join(states), size=32)
    return final


def solve(header: bytes, nonce: int, cache, seed_epoch: bytes,
          seed_block: bytes, P: dict, states_log: list = None) -> bytes:
    """Light path: no precomputed dataset (node-verify evaluation)."""
    return _solve(header, nonce, cache, seed_epoch, seed_block, P,
                  states_log=states_log)


def solve_with_dataset(header: bytes, nonce: int, dataset: dict,
                       P: dict, states_log: list = None) -> bytes:
    """Miner path: precomputed effective dataset (must equal solve())."""
    return _solve(header, nonce, None, b"", b"", P, dataset=dataset,
                  states_log=states_log)


def verify(header: bytes, nonce: int, target: bytes, cache,
           seed_epoch: bytes, seed_block: bytes, P: dict) -> bool:
    """Light verification: replay from cache, check the target. No dataset."""
    final = solve(header, nonce, cache, seed_epoch, seed_block, P)
    return int.from_bytes(final, "big") <= int.from_bytes(target, "big")


def mine(header: bytes, target: bytes, cache, seed_epoch: bytes,
         seed_block: bytes, P: dict, start_nonce: int = 0,
         max_nonce: int = 1 << 20):
    """Brute force until result <= target. Returns (nonce, final) or None."""
    for nonce in range(start_nonce, max_nonce):
        final = solve(header, nonce, cache, seed_epoch, seed_block, P)
        if int.from_bytes(final, "big") <= int.from_bytes(target, "big"):
            return nonce, final
    return None


# ---------------------------------------------------------------------------
# CLI: selftest + test-vector generation
# ---------------------------------------------------------------------------

def export_vectors(outdir: str, header: bytes = b"h0", nonce: int = 7) -> dict:
    """Phase 2 of cuda-kernel-dev: the protective vector snapshot.

    Exports everything a GPU implementation needs for bit-exact cross-checks,
    WITHOUT touching the math: cache, effective dataset, lane states (initial
    + after every round) and the final hash, as flat .bin files + meta.json.
    Deterministic given (header, nonce) — a committed snapshot must always
    regenerate byte-identical."""
    from pathlib import Path
    P = TEST_PROFILE
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    seed_epoch = epoch_seed(0, b"\x11" * 32)
    seed_block = block_seed(b"\x22" * 32, 1)
    cache = gen_cache(seed_epoch, P["cache_words"])

    ds = build_effective_dataset(cache, seed_epoch, P["item_parents"],
                                 seed_block, P["dataset_items"])

    log = []
    final = solve(header, nonce, cache, seed_epoch, seed_block, P,
                  states_log=log)
    # sanity: miner path must reproduce the same states and final
    log2 = []
    final2 = solve_with_dataset(header, nonce, ds, P, states_log=log2)
    assert final == final2 and log == log2, "paths disagree on vector export"

    (out / "cache.bin").write_bytes(b"".join(cache))
    (out / "dataset_eff.bin").write_bytes(
        b"".join(ds[j] for j in range(P["dataset_items"])))
    (out / "states.bin").write_bytes(b"".join(log))
    (out / "final.bin").write_bytes(final)
    (out / "seed_epoch.bin").write_bytes(seed_epoch)
    (out / "seed_block.bin").write_bytes(seed_block)
    (out / "header.bin").write_bytes(header)
    (out / "nonce.bin").write_bytes(le64(nonce))
    meta = {
        "profile": P,
        "header_hex": header.hex(),
        "nonce": nonce,
        "states_layout": "[init][after round 0]...[after round R-1], "
                         f"{P['lanes']} lanes x 32 B each",
        "final_hex": final.hex(),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"final": final.hex(), "rounds_logged": len(log),
            "files": sorted(p.name for p in out.iterdir())}


def selftest() -> None:
    P = TEST_PROFILE
    seed_epoch = epoch_seed(0, b"\x11" * 32)
    seed_block = block_seed(b"\x22" * 32, 1)
    cache = gen_cache(seed_epoch, P["cache_words"])

    # light path vs miner path must agree bit-for-bit
    ds = build_effective_dataset(cache, seed_epoch, P["item_parents"],
                                 seed_block, P["dataset_items"])
    a = solve(b"header0", 7, cache, seed_epoch, seed_block, P)
    b = solve_with_dataset(b"header0", 7, ds, P)
    assert a == b, "light path and miner path disagree"
    print(f"light == miner OK   final={a.hex()}")

    nonce, final = mine(b"header1", b"\x0f" + b"\xff" * 31, cache,
                        seed_epoch, seed_block, P)
    assert verify(b"header1", nonce, b"\x0f" + b"\xff" * 31, cache,
                  seed_epoch, seed_block, P)
    print(f"mine+verify OK      nonce={nonce} final={final.hex()}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "export-vectors":
        print(json.dumps(export_vectors(sys.argv[2]), indent=2))
    else:
        selftest()
