"""Vice City wallet core: ML-DSA-65 (FIPS 204) keypairs and vc1 addresses.

Address format (docs/crypto.md §2): <hrp>1 + Bech32m(BLAKE2b-256(vk)).
Brand rename Octet->Vice City changes only the HRP: oct1 -> vc1.
"""
import hashlib
import json
import os
import time
from pathlib import Path

from mnemonic import Mnemonic
from dilithium_py.ml_dsa import ML_DSA_65

# --- cold wallet: BIP-39 (24 words) -> 256-bit entropy -> ML-DSA seed -------
# FIPS 204 signs keys are derived from a 32-byte seed (xi); 24 BIP-39 words
# encode exactly 256 bits, so the words ARE the seed material. The same
# words anywhere reproduce the same keys and the same vc1 address.
_mn = Mnemonic(language="english")
_seed_ctx = {"bytes": None}


def _seeded_random(n: int) -> bytes:
    """Keygen randomness hook: deterministic when a seed is staged."""
    e = _seed_ctx["bytes"]
    if e is None:
        return os.urandom(n)
    return (e * 2)[:n]


ML_DSA_65.random_bytes = _seeded_random


def generate_mnemonic(strength: int = 256) -> list[str]:
    return _mn.generate(strength=strength).split()


def mnemonic_to_entropy(words: list[str], passphrase: str = "") -> bytes:
    w = " ".join(words).strip()
    if not _mn.check(w):
        raise ValueError(
            "Сид-фраза неверна: опечатка в слове или контрольная сумма")
    entropy = _mn.to_entropy(w)
    if passphrase:
        # passphrase-hardened seed (25th word, BIP-39 style stretching)
        entropy = hashlib.pbkdf2_hmac(
            "sha512", " ".join(words).strip().encode("utf-8"),
            ("mnemonic" + passphrase).encode("utf-8"), 2048)[:32]
    return entropy


def keygen_from_entropy(entropy: bytes) -> tuple[bytes, bytes]:
    if len(entropy) != 32:
        raise ValueError("seed must be 32 bytes")
    _seed_ctx["bytes"] = bytes(entropy)
    try:
        return ML_DSA_65.keygen()
    finally:
        _seed_ctx["bytes"] = None


def create_cold_wallet(passphrase: str = "") -> dict:
    """24 слова + опц. пассфраза -> ключи. Слова НЕ сохраняются в файл —
    единственная копия у владельца."""
    words = generate_mnemonic()
    entropy = mnemonic_to_entropy(words, passphrase)
    vk, sk = keygen_from_entropy(entropy)
    return {"words": words, "vk": vk, "sk": sk, "entropy": bytes(entropy)}


def restore_from_mnemonic(words: list[str], passphrase: str = "") -> dict:
    entropy = mnemonic_to_entropy(words, passphrase)
    vk, sk = keygen_from_entropy(entropy)
    return {"vk": vk, "sk": sk, "entropy": bytes(entropy)}


def save_cold_wallet(w: dict, store_seed: bool = True) -> None:
    d = {"vk_hex": w["vk"].hex(), "sk_hex": w["sk"].hex(),
         "created": time.time(), "kind": "cold"}
    if store_seed and "entropy" in w:
        d["seed_hex"] = w["entropy"].hex()
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    WALLET_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    try:
        os.chmod(WALLET_FILE, 0o600)
    except OSError:
        pass

HRP = "vc"
WALLET_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ViceCity"
WALLET_FILE = WALLET_DIR / "wallet.json"

# --- bech32m (BIP-350), encoder only --------------------------------------
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
BECH32M_CONST = 0x2BC830A3999204F1


def _polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _checksum(hrp, data):
    values = _hrp_expand(hrp) + data
    mod = _polymod(values + [0] * 6) ^ BECH32M_CONST
    return [(mod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data, frombits, tobits, pad=True):
    acc = bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def vc_address(vk: bytes) -> str:
    """vc1… = Bech32m(BLAKE2b-256(ML-DSA vk))."""
    digest = hashlib.blake2b(vk, digest_size=32).digest()
    data = _convertbits(digest, 8, 5)
    return HRP + "1" + "".join(CHARSET[d] for d in data + _checksum(HRP, data))


# --- wallet storage ---------------------------------------------------------

def load_or_create_wallet() -> dict:
    """Returns {"vk": bytes, "sk": bytes, "address": str, "created": float,
    "fresh": bool}. Creates the wallet file on first run."""
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    if WALLET_FILE.exists():
        w = json.loads(WALLET_FILE.read_text(encoding="utf-8"))
        w["vk"] = bytes.fromhex(w["vk_hex"])
        w["sk"] = bytes.fromhex(w["sk_hex"])
        w["fresh"] = False
    else:
        vk, sk = ML_DSA_65.keygen()
        w = {"vk": vk, "sk": sk, "created": time.time(), "fresh": True}
        save_wallet(w)
    w["address"] = vc_address(w["vk"])
    return w


def save_wallet(w: dict) -> None:
    WALLET_FILE.write_text(json.dumps({
        "vk_hex": w["vk"].hex(),
        "sk_hex": w["sk"].hex(),
        "created": w["created"],
    }, indent=2), encoding="utf-8")
    try:  # keep prying eyes off the seed file where the OS supports it
        os.chmod(WALLET_FILE, 0o600)
    except OSError:
        pass


def selftest() -> int:
    w = load_or_create_wallet()
    msg = b"vice-city-wallet-selftest"
    sig = ML_DSA_65.sign(w["sk"], msg)
    ok = ML_DSA_65.verify(w["vk"], msg, sig)
    bad = ML_DSA_65.verify(w["vk"], b"tampered", sig)
    print("wallet file :", WALLET_FILE)
    print("address     :", w["address"])
    print("sig/verify  :", ok, "(tamper rejected:", not bad, ")")
    print("vk/sk bytes :", len(w["vk"]), "/", len(w["sk"]))
    return 0 if (ok and not bad) else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
