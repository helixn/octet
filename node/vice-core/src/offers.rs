//! Offers (docs/crypto.md §4 v0.2) — pre-signed shoulder + atomic completion.
//!
//! maker_part is a length-prefixed binary serialization (byte-deterministic,
//! like Transaction::unsigned_payload) — no JSON-canonicalization traps.
//! Validation rules (§4.2): maker_sig over the shoulder, ownership of
//! maker notes by maker_vk via openings, taker per-input sigs over the
//! full txid (offer field included), nullifier freshness + expiry, and
//! rule 5: the ask MUST be paid exactly (commit + amount equality).
use crate::addr::{blake2b_256, vk_from_bytes, verify as dsa_verify};
use crate::notes::{nullifier, verify_opening, NoteOpening};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

pub const OFFER_TAG: &[u8] = b"vice-offer-v1";
pub const MAX_MAKER_INPUTS: usize = 16;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OfferInput {
    /// opening revealed in the completion (ownership by recommit)
    pub opening: NoteOpening,
    pub nullifier: [u8; 32],
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OfferOutput {
    pub commit: [u8; 32],
    pub amount: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OfferAsk {
    pub commit: [u8; 32],
    pub amount: u64,
}

/// What the maker signs — recovered from `maker_part` bytes by the validator.
#[derive(Clone, Debug)]
pub struct MakerPart {
    pub version: u32,
    pub maker_vk: Vec<u8>,
    pub height_expiry: u64,
    pub maker_inputs: Vec<OfferInput>,
    pub maker_outputs: Vec<OfferOutput>,
    pub ask: OfferAsk,
}

/// Serialized canonical shoulder (embedded into the completion transaction).
pub fn maker_part_bytes(m: &MakerPart) -> Vec<u8> {
    let mut b = Vec::new();
    b.extend_from_slice(OFFER_TAG);
    b.extend_from_slice(&m.version.to_le_bytes());
    b.extend_from_slice(&(m.maker_vk.len() as u32).to_le_bytes());
    b.extend_from_slice(&m.maker_vk);
    b.extend_from_slice(&m.height_expiry.to_le_bytes());
    b.extend_from_slice(&(m.maker_inputs.len() as u32).to_le_bytes());
    for inp in &m.maker_inputs {
        b.extend_from_slice(&inp.opening.commit());
        b.extend_from_slice(&inp.opening.amount.to_le_bytes());
        b.extend_from_slice(&inp.opening.rho);
        b.extend_from_slice(&inp.opening.r);
        b.extend_from_slice(&inp.nullifier);
    }
    b.extend_from_slice(&(m.maker_outputs.len() as u32).to_le_bytes());
    for out in &m.maker_outputs {
        b.extend_from_slice(&out.commit);
        b.extend_from_slice(&out.amount.to_le_bytes());
    }
    b.extend_from_slice(&m.ask.commit);
    b.extend_from_slice(&m.ask.amount.to_le_bytes());
    b
}

/// Recover the shoulder from canonical bytes (structural parse).
pub fn parse_maker_part(bytes: &[u8]) -> Result<MakerPart, String> {
    let mut cur = Cursor::new(bytes);
    let mut tag = [0u8; OFFER_TAG.len()];
    cur.read_exact_tag(&mut tag)?;
    if tag != OFFER_TAG {
        return Err("bad offer tag".into());
    }
    let version = cur.read_u32()?;
    let vk_len = cur.read_u32()? as usize;
    let maker_vk = cur.read_bytes(vk_len)?;
    let height_expiry = cur.read_u64()?;
    let n_in = cur.read_u32()? as usize;
    if n_in > MAX_MAKER_INPUTS {
        return Err("too many maker inputs".into());
    }
    let mut maker_inputs = Vec::with_capacity(n_in);
    for _ in 0..n_in {
        let _commit: [u8; 32] = cur.read_arr32()?; // implied by the opening
        let amount = cur.read_u64()?;
        let rho: [u8; 32] = cur.read_arr32()?;
        let r: [u8; 32] = cur.read_arr32()?;
        let nf: [u8; 32] = cur.read_arr32()?;
        maker_inputs.push(OfferInput {
            opening: NoteOpening { vk: maker_vk.clone(), amount, rho, r },
            nullifier: nf,
        });
    }
    let n_out = cur.read_u32()? as usize;
    let mut maker_outputs = Vec::with_capacity(n_out);
    for _ in 0..n_out {
        let commit: [u8; 32] = cur.read_arr32()?;
        let amount = cur.read_u64()?;
        maker_outputs.push(OfferOutput { commit, amount });
    }
    let ask_commit: [u8; 32] = cur.read_arr32()?;
    let ask_amount = cur.read_u64()?;
    cur.expect_end()?;
    if vk_from_bytes(&maker_vk).is_none() {
        return Err("bad maker_vk".into());
    }
    // openings must be internally consistent: commit and nullifier match
    for inp in &maker_inputs {
        if !verify_opening(&inp.opening, &inp.opening.commit(),
                           &inp.nullifier) {
            return Err("maker input opening inconsistent".into());
        }
    }
    Ok(MakerPart {
        version,
        maker_vk,
        height_expiry,
        maker_inputs,
        maker_outputs,
        ask: OfferAsk { commit: ask_commit, amount: ask_amount },
    })
}

struct Cursor<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> Cursor<'a> {
    fn new(d: &'a [u8]) -> Self {
        Cursor { data: d, pos: 0 }
    }

    fn take(&mut self, n: usize) -> Result<&'a [u8], String> {
        if self.pos + n > self.data.len() {
            return Err("truncated maker_part".into());
        }
        let s = &self.data[self.pos..self.pos + n];
        self.pos += n;
        Ok(s)
    }

    fn read_exact_tag(&mut self, out: &mut [u8]) -> Result<(), String> {
        out.copy_from_slice(self.take(out.len())?);
        Ok(())
    }

    fn read_u32(&mut self) -> Result<u32, String> {
        Ok(u32::from_le_bytes(self.take(4)?.try_into().unwrap()))
    }

    fn read_u64(&mut self) -> Result<u64, String> {
        Ok(u64::from_le_bytes(self.take(8)?.try_into().unwrap()))
    }

    fn read_arr32(&mut self) -> Result<[u8; 32], String> {
        Ok(self.take(32)?.try_into().unwrap())
    }

    fn read_bytes(&mut self, n: usize) -> Result<Vec<u8>, String> {
        Ok(self.take(n)?.to_vec())
    }

    fn expect_end(&self) -> Result<(), String> {
        if self.pos != self.data.len() {
            return Err("trailing bytes in maker_part".into());
        }
        Ok(())
    }
}

/// Attachment on the completion transaction (A-2: shoulder bytes travel
/// with the transaction and are bound into its txid).
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OfferAttachment {
    pub maker_part: Vec<u8>,
    pub maker_sig: Vec<u8>,
}

pub fn maker_part_hash(maker_part: &[u8]) -> [u8; 32] {
    let mut buf = Vec::with_capacity(OFFER_TAG.len() + maker_part.len());
    buf.extend_from_slice(OFFER_TAG);
    buf.extend_from_slice(maker_part);
    blake2b_256(&buf)
}

pub fn sign_maker_part(sk: &ml_dsa::SigningKey<ml_dsa::MlDsa65>,
                       maker_part: &[u8]) -> Vec<u8> {
    crate::addr::sign(sk, &maker_part_hash(maker_part))
}

#[derive(Debug)]
pub enum OfferError {
    MakerPartMalformed(String),
    MakerSigInvalid,
    MakerNotOwningInput { index: usize },
    AskNotPaid,
    NullifierSpent { index: usize },
    OfferExpired { expiry: u64, height: u64 },
    ShoulderNotFound { index: usize },
    MakerSigPresent { index: usize },
}

/// Rules §4.2 1–5 for an OfferCompletion transaction.
/// `maker_input_count` — how many of tx.inputs are the maker shoulder
/// (they must come first, sig-less, vk == maker_vk).
#[allow(clippy::too_many_arguments)]
pub fn validate_offer_completion(
    tx: &crate::tx::Transaction,
    nullifier_pool: &HashSet<String>,
    height: u64,
) -> Result<(), OfferError> {
    let Some(offer) = &tx.offer else {
        return Err(OfferError::MakerPartMalformed("no offer".into()));
    };
    // rule 1: shoulder integrity + signature
    let part = parse_maker_part(&offer.maker_part)
        .map_err(OfferError::MakerPartMalformed)?;
    let hash = maker_part_hash(&offer.maker_part);
    let Some(vk) = vk_from_bytes(&part.maker_vk) else {
        return Err(OfferError::MakerSigInvalid);
    };
    if !dsa_verify(&vk, &hash, &offer.maker_sig) {
        return Err(OfferError::MakerSigInvalid);
    }
    let n_maker = part.maker_inputs.len();
    if tx.inputs.len() < n_maker {
        return Err(OfferError::ShoulderNotFound { index: 0 });
    }
    // rule 2: ownership — openings consistent, keys belong to maker,
    // per-input sigs REPLACED by maker_sig (must be empty)
    for (i, inp) in part.maker_inputs.iter().enumerate() {
        let tx_in = tx.inputs.get(i).ok_or(OfferError::ShoulderNotFound {
            index: i,
        })?;
        if !verify_opening(&inp.opening, &inp.opening.commit(),
                           &inp.nullifier) {
            return Err(OfferError::MakerNotOwningInput { index: i });
        }
        if tx_in.vk != part.maker_vk || !tx_in.sig.is_empty() {
            return Err(OfferError::MakerSigPresent { index: i });
        }
        if tx_in.prev_txid != hex::encode(inp.nullifier) {
            return Err(OfferError::ShoulderNotFound { index: i });
        }
    }
    // rule 3: taker per-input sigs over the full txid (non-shoulder inputs)
    for (i, tx_in) in tx.inputs.iter().enumerate().skip(n_maker) {
        let Some(vk) = vk_from_bytes(&tx_in.vk) else {
            return Err(OfferError::MakerSigInvalid);
        };
        if !dsa_verify(&vk, &tx.txid(), &tx_in.sig) {
            return Err(OfferError::MakerSigInvalid);
        }
        let _ = i;
    }
    // rule 4: nullifier freshness + expiry
    if height > part.height_expiry {
        return Err(OfferError::OfferExpired {
            expiry: part.height_expiry,
            height,
        });
    }
    for (i, inp) in part.maker_inputs.iter().enumerate() {
        if nullifier_pool.contains(&hex::encode(inp.nullifier)) {
            return Err(OfferError::NullifierSpent { index: i });
        }
    }
    // rule 5 (A-1): the ask must be paid EXACTLY
    let paid = tx.outputs.iter().any(|o| {
        o.commit == hex::encode(part.ask.commit) && o.amount == part.ask.amount
    });
    if !paid {
        return Err(OfferError::AskNotPaid);
    }
    Ok(())
}

/// Convenience: nullifier hex for a spend entry in the pool.
pub fn nullifier_hex(rho: &[u8; 32], commit: &[u8; 32]) -> String {
    hex::encode(nullifier(rho, commit))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maker_part_roundtrip() {
        use crate::addr::keygen;
        let kp = keygen();
        let mut opening = NoteOpening::new(crate::addr::vk_bytes(&kp.vk), 42);
        opening.rho = blake2b_256(b"rho");
        opening.r = blake2b_256(b"r");
        let m = MakerPart {
            version: 1,
            maker_vk: crate::addr::vk_bytes(&kp.vk),
            height_expiry: 1000,
            maker_inputs: vec![OfferInput {
                opening: opening.clone(),
                nullifier: opening.nullifier(),
            }],
            maker_outputs: vec![OfferOutput {
                commit: blake2b_256(b"change"),
                amount: 7,
            }],
            ask: OfferAsk { commit: blake2b_256(b"taker"), amount: 35 },
        };
        let bytes = maker_part_bytes(&m);
        let parsed = parse_maker_part(&bytes)
            .unwrap_or_else(|e| panic!("parse failed: {e}"));
        assert_eq!(parsed.maker_vk, m.maker_vk);
        assert_eq!(parsed.maker_inputs[0].opening.amount, 42);
        assert_eq!(parsed.ask.amount, 35);
        assert_eq!(maker_part_bytes(&parsed), bytes, "canonical bytes stable");
    }
}
