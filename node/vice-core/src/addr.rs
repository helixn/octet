//! vc1 addresses and ML-DSA-65 signing (docs/crypto.md §2).
//! Address: vc1 + Bech32m(BLAKE2b-256(ML-DSA-65 vk)) — identical to the
//! Python desktop wallet (dilithium-py encodes vk to the same 1952-byte
//! FIPS 204 format as RustCrypto ml-dsa, so addresses are portable).
use blake2::digest::{Update, VariableOutput};
use blake2::Blake2bVar;
use ml_dsa::{Generate, KeyExport, Keypair, MlDsa65, Signer, SigningKey,
             Verifier, VerifyingKey};

pub const VK_LEN: usize = 1952;
pub const SEED_LEN: usize = 32; // signing key serializes as its 32-byte seed
pub const SIG_LEN: usize = 3309;

pub struct KeyPair {
    pub sk: SigningKey<MlDsa65>,
    pub vk: VerifyingKey<MlDsa65>,
}

pub fn keygen() -> KeyPair {
    let sk = SigningKey::<MlDsa65>::generate();
    KeyPair { vk: sk.verifying_key(), sk }
}

pub fn vk_bytes(vk: &VerifyingKey<MlDsa65>) -> Vec<u8> {
    vk.to_bytes().to_vec()
}

pub fn sk_bytes(sk: &SigningKey<MlDsa65>) -> Vec<u8> {
    sk.to_bytes().to_vec()
}

pub fn vk_from_bytes(bytes: &[u8]) -> Option<VerifyingKey<MlDsa65>> {
    if bytes.len() != VK_LEN {
        return None;
    }
    let key = ml_dsa::common::Key::<VerifyingKey<MlDsa65>>::try_from(bytes)
        .ok()?;
    Some(VerifyingKey::decode(&key))
}

pub fn sk_from_bytes(bytes: &[u8]) -> Option<SigningKey<MlDsa65>> {
    if bytes.len() != SEED_LEN {
        return None;
    }
    let seed = ml_dsa::common::Key::<SigningKey<MlDsa65>>::try_from(bytes)
        .ok()?;
    Some(SigningKey::from_seed(&seed))
}

pub fn sign(sk: &SigningKey<MlDsa65>, msg: &[u8]) -> Vec<u8> {
    sk.sign(msg).encode().to_vec()
}

pub fn verify(vk: &VerifyingKey<MlDsa65>, msg: &[u8], sig: &[u8]) -> bool {
    match Signature::try_from(sig) {
        Ok(s) => vk.verify(msg, &s).is_ok(),
        Err(_) => false,
    }
}

use ml_dsa::Signature;

pub fn blake2b_256(data: &[u8]) -> [u8; 32] {
    let mut hasher = Blake2bVar::new(32).expect("32 <= 64");
    hasher.update(data);
    let mut out = [0u8; 32];
    hasher.finalize_variable(&mut out).expect("exact buffer");
    out
}

/// commit = BLAKE2b-256(vk) — the output lock key (Tier 0 transparent;
/// note pool / stealth = Tier 1-2, reserved by the genesis design).
pub fn commit_of_vk(vk: &[u8]) -> [u8; 32] {
    blake2b_256(vk)
}

// --- bech32m (BIP-350) — implemented here because the bech32 0.11 crate's
// --- `encode::<Bech32m>` produced a diverging checksum for our payload
// --- (caught by the Python/JS golden cross-check, gate review K3).

const CHARSET: &[u8; 32] = b"qpzry9x8gf2tvdw0s3jn54khce6mua7l";
const BECH32M_CONST: u64 = 0x2bc830a3999204f1;

fn polymod(values: &[u8]) -> u64 {
    const GEN: [u64; 5] = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
    let mut chk: u64 = 1;
    for &v in values {
        let top = chk >> 25;
        chk = ((chk & 0x1ffffff) << 5) ^ u64::from(v);
        for (i, g) in GEN.iter().enumerate() {
            if (top >> i) & 1 == 1 {
                chk ^= g;
            }
        }
    }
    chk
}

fn hrp_expand(hrp: &str) -> Vec<u8> {
    let high: Vec<u8> = hrp.bytes().map(|b| b >> 5).collect();
    let low: Vec<u8> = hrp.bytes().map(|b| b & 31).collect();
    let mut v = high;
    v.push(0);
    v.extend(low);
    v
}

fn bech32m_checksum(hrp: &str, data: &[u8]) -> [u8; 6] {
    let mut values = hrp_expand(hrp);
    values.extend_from_slice(data);
    values.extend_from_slice(&[0u8; 6]);
    let mod_res = polymod(&values) ^ BECH32M_CONST;
    let mut out = [0u8; 6];
    for (i, item) in out.iter_mut().enumerate() {
        *item = ((mod_res >> (5 * (5 - i))) & 31) as u8;
    }
    out
}

/// vc1… = Bech32m(HRP "vc", BLAKE2b-256(vk)) — identical to the Python
/// wallet (pinned by the golden test below) and the spec-compliant JS
/// arbiter; all three share the same polymod.
pub fn vc_address(vk: &[u8]) -> String {
    let digest = commit_of_vk(vk);
    let data5 = convertbits(&digest, 8, 5);
    let mut s = String::from("vc1");
    for &g in &data5 {
        s.push(CHARSET[g as usize] as char);
    }
    for &c in &bech32m_checksum("vc", &data5) {
        s.push(CHARSET[c as usize] as char);
    }
    s
}

fn convertbits(data: &[u8], from: u32, to: u32) -> Vec<u8> {
    let mut acc: u32 = 0;
    let mut bits: u32 = 0;
    let mut ret = Vec::new();
    let maxv = (1u32 << to) - 1;
    for &value in data {
        acc = (acc << from) | u32::from(value);
        bits += from;
        while bits >= to {
            bits -= to;
            ret.push(((acc >> bits) & maxv) as u8);
        }
    }
    if bits > 0 {
        ret.push(((acc << (to - bits)) & maxv) as u8);
    }
    ret
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keygen_sign_verify_roundtrip() {
        let kp = keygen();
        let msg = b"vice city testnet";
        let sig = sign(&kp.sk, msg);
        assert!(verify(&kp.vk, msg, &sig));
        assert!(!verify(&kp.vk, b"tampered", &sig));
        assert_eq!(vk_bytes(&kp.vk).len(), VK_LEN);
        assert_eq!(sk_bytes(&kp.sk).len(), SEED_LEN);
    }

    #[test]
    fn address_is_vc1_and_stable() {
        let kp = keygen();
        let a1 = vc_address(&vk_bytes(&kp.vk));
        let a2 = vc_address(&vk_bytes(&kp.vk));
        assert_eq!(a1, a2);
        assert!(a1.starts_with("vc1"));
        assert!(a1.len() > 50);
    }

    #[test]
    fn keys_survive_encoding_roundtrip() {
        let kp = keygen();
        let sk2 = sk_from_bytes(&sk_bytes(&kp.sk)).expect("decode sk");
        let vk2 = vk_from_bytes(&vk_bytes(&kp.vk)).expect("decode vk");
        let msg = b"roundtrip";
        assert!(verify(&vk2, msg, &sign(&sk2, msg)));
    }
}

#[test]
fn address_matches_python_wallet_golden() {
    // golden generated by app/vicecity/wallet_core.py vc_address()
    let vk_pattern: Vec<u8> = (0..1952usize).map(|i| ((i * 7) % 256) as u8).collect();
    assert_eq!(
        vc_address(&vk_pattern),
        "vc1jdd87mjx62rs8v6mmatuy73tkjveh9v0kgxhcjdth6fgvx0ws6yqvv7y6n",
        "Rust vc1 diverged from the Python wallet oracle"
    );
}
