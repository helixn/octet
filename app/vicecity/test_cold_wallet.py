"""Cold wallet tests: BIP-39 (24 words) -> ML-DSA seed -> keys -> address.

The same words on any machine must reproduce the same keys and the same
vc1 address (that's the whole point of a mnemonic cold wallet)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wallet_core import (  # noqa: E402
    create_cold_wallet, mnemonic_to_entropy, keygen_from_entropy,
    restore_from_mnemonic, vc_address, save_cold_wallet,
    load_or_create_wallet, mnemonic_to_entropy as _mte,
)
from mnemonic import Mnemonic  # noqa: E402
import pytest  # noqa: E402


def test_cold_wallet_roundtrip_same_words_same_address():
    w = create_cold_wallet()
    addr1 = vc_address(w["vk"])
    w2 = restore_from_mnemonic(w["words"])
    addr2 = vc_address(w2["vk"])
    assert addr1 == addr2, "same words must reproduce the same address"
    assert w["sk"] == w2["sk"], "signing key must be seed-deterministic"


def test_mnemonic_is_24_bip39_words_with_checksum():
    w = create_cold_wallet()
    assert len(w["words"]) == 24
    assert Mnemonic(language="english").check(" ".join(w["words"]))


def test_passphrase_changes_the_wallet():
    w1 = create_cold_wallet()
    ent_p = mnemonic_to_entropy(w1["words"], "secret25")
    ent_no = mnemonic_to_entropy(w1["words"])
    assert ent_p != ent_no, "passphrase must harden the seed"
    vk_p, _ = keygen_from_entropy(ent_p)
    assert vc_address(vk_p) != vc_address(w1["vk"])


def test_bad_checksum_rejected():
    w = create_cold_wallet()
    bad = w["words"].copy()
    bad[7] = "abandon" if bad[7] != "abandon" else "zoo"
    with pytest.raises(ValueError):
        mnemonic_to_entropy(bad)


def test_save_cold_and_load_roundtrip(tmp_path, monkeypatch):
    import wallet_core
    w = create_cold_wallet()
    addr = vc_address(w["vk"])
    monkeypatch.setattr(wallet_core, "WALLET_FILE",
                        tmp_path / "wallet.json")
    wallet_core.save_cold_wallet(w, store_seed=True)
    loaded = wallet_core.load_or_create_wallet()
    assert vc_address(loaded["vk"]) == addr
    assert loaded["vk"] == w["vk"] and loaded["sk"] == w["sk"]
