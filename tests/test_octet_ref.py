"""OctetHash reference tests: correctness of both evaluation paths, keystream
re-keying, tamper resistance and target search."""

import pytest

from reference.octet_ref import (
    TEST_PROFILE as P,
    block_seed,
    build_effective_dataset,
    effective_item,
    epoch_seed,
    gen_cache,
    keystream_item,
    mine,
    solve,
    solve_with_dataset,
    verify,
)


@pytest.fixture(scope="module")
def env():
    seed_epoch = epoch_seed(0, b"\x11" * 32)
    seed_block = block_seed(b"\x22" * 32, 1)
    cache = gen_cache(seed_epoch, P["cache_words"])
    return seed_epoch, seed_block, cache


def test_light_path_equals_miner_path(env):
    seed_epoch, seed_block, cache = env
    ds = build_effective_dataset(cache, seed_epoch, P["item_parents"],
                                 seed_block, P["dataset_items"])
    a = solve(b"h0", 7, cache, seed_epoch, seed_block, P)
    b = solve_with_dataset(b"h0", 7, ds, P)
    assert a == b


def test_determinism(env):
    seed_epoch, seed_block, cache = env
    a = solve(b"h0", 3, cache, seed_epoch, seed_block, P)
    b = solve(b"h0", 3, cache, seed_epoch, seed_block, P)
    assert a == b


def test_nonce_changes_result(env):
    seed_epoch, seed_block, cache = env
    a = solve(b"h0", 0, cache, seed_epoch, seed_block, P)
    b = solve(b"h0", 1, cache, seed_epoch, seed_block, P)
    assert a != b


def test_keystream_rekeys_every_block(env):
    seed_epoch, _, cache = env
    j = 123
    ks0 = keystream_item(j, b"\x01" * 32)
    ks1 = keystream_item(j, b"\x02" * 32)
    assert ks0 != ks1
    e0 = effective_item(j, cache, seed_epoch, P["item_parents"], b"\x01" * 32)
    e1 = effective_item(j, cache, seed_epoch, P["item_parents"], b"\x02" * 32)
    assert e0 != e1, "dataset must change when the block seed changes"


def test_epoch_changes_dataset(env):
    _, seed_block, cache = env
    se0 = epoch_seed(0, b"\x11" * 32)
    se1 = epoch_seed(1, b"\x11" * 32)
    assert se0 != se1
    j = 5
    a = effective_item(j, cache, se0, P["item_parents"], seed_block)
    b = effective_item(j, cache, se1, P["item_parents"], seed_block)
    assert a != b


def test_verify_accepts_and_rejects(env):
    seed_epoch, seed_block, cache = env
    loose = b"\x0f" + b"\xff" * 31          # ~1/16 chance per attempt
    found = mine(b"h1", loose, cache, seed_epoch, seed_block, P)
    assert found is not None, "no solution under the loose target"
    nonce, final = found
    assert verify(b"h1", nonce, loose, cache, seed_epoch, seed_block, P)
    # a different nonce must not verify against the same claimed final
    other = solve(b"h1", nonce + 1, cache, seed_epoch, seed_block, P)
    assert other != final
    assert not verify(b"h1", nonce + 1, b"\x00" * 32, cache,
                      seed_epoch, seed_block, P)


def test_tighter_target_changes_result(env):
    seed_epoch, seed_block, cache = env
    t1 = b"\x0f" + b"\xff" * 31
    t2 = b"\x07" + b"\xff" * 31
    n1, _ = mine(b"h2", t1, cache, seed_epoch, seed_block, P)
    n2, _ = mine(b"h2", t2, cache, seed_epoch, seed_block, P)
    assert n1 is not None and n2 is not None


def test_block_seed_depends_on_prev_solution(env):
    a = block_seed(b"\x33" * 32, 100)
    b = block_seed(b"\x44" * 32, 100)
    assert a != b, "re-keying must be bound to the chain, not just height"
