"""The committed vector snapshot (tests/vectors/) must always regenerate
byte-identical. This is the protective snapshot for the CUDA cross-check
(cuda-kernel-dev, phase 2) — if this test fails, someone changed the math
without going through pow-spec-review."""

import tempfile
from pathlib import Path

from reference.octet_ref import TEST_PROFILE as P, export_vectors

VECTORS_DIR = Path(__file__).resolve().parent / "vectors"
BIN_FILES = ["cache.bin", "dataset_eff.bin", "states.bin", "final.bin"]


def test_vector_snapshot_is_reproducible():
    assert (VECTORS_DIR / "meta.json").exists(), "vector snapshot missing"
    with tempfile.TemporaryDirectory() as tmp:
        info = export_vectors(tmp)  # same fixed header/nonce as the snapshot
        assert info["final"] == "617463de72d46987e333f40d65215ccfe2eabfad97ae829190ef99f64e65c65a"
        for name in BIN_FILES:
            committed = (VECTORS_DIR / name).read_bytes()
            fresh = (Path(tmp) / name).read_bytes()
            assert committed == fresh, f"{name} diverged from the committed snapshot"


def test_snapshot_layout_matches_profile():
    meta_cache_words = P["cache_words"]
    assert (VECTORS_DIR / "cache.bin").stat().st_size == meta_cache_words * 64
    assert (VECTORS_DIR / "dataset_eff.bin").stat().st_size == P["dataset_items"] * 256
    # [init] + ROUNDS snapshots, LANES * 32 B each
    assert (VECTORS_DIR / "states.bin").stat().st_size == (P["rounds"] + 1) * P["lanes"] * 32
    assert (VECTORS_DIR / "final.bin").stat().st_size == 32
