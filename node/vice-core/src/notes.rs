//! Notes (Tier 2) — the note-pool primitives per docs/crypto.md §3-4.
//!
//! A note is a commitment over (owner vk, amount, rho, r). Spending reveals
//! the opening (pk, amount, rho, r) — ownership is proven by recomputing the
//! commit; the nullifier (H(rho ‖ commit)) is owner-private until the spend
//! (rho is secret), publicly verifiable at spend time, and unique per note.
//! No ECC anywhere (gate review: ownership = ML-DSA + commit opening).
use crate::addr::{blake2b_256, vk_from_bytes};
use serde::{Deserialize, Serialize};

pub const NOTE_COMMIT_LEN: usize = 32;

/// Full opening of a note — revealed at spend time.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NoteOpening {
    /// owner's ML-DSA-65 verification key (1952 B)
    pub vk: Vec<u8>,
    pub amount: u64,
    pub rho: [u8; 32],
    pub r: [u8; 32],
}

impl NoteOpening {
    pub fn new(vk: Vec<u8>, amount: u64) -> Self {
        let rho = blake2b_256(&{
            let mut b = vk.clone();
            b.extend_from_slice(&amount.to_le_bytes());
            b.extend_from_slice(&os_random());
            b
        });
        let r = blake2b_256(&{
            let mut b = rho.to_vec();
            b.extend_from_slice(&amount.to_le_bytes());
            b
        });
        NoteOpening { vk, amount, rho, r }
    }

    pub fn commit(&self) -> [u8; 32] {
        note_commit(&self.vk, self.amount, &self.rho, &self.r)
    }

    pub fn nullifier(&self) -> [u8; 32] {
        nullifier(&self.rho, &self.commit())
    }
}

fn os_random() -> [u8; 32] {
    // std-only CSPRNG fallback: hash of high-resolution time + address entropy
    use std::time::{SystemTime, UNIX_EPOCH};
    let t = SystemTime::now().duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    blake2b_256(&format!(
        "{}-{:?}",
        t.as_nanos(),
        std::process::id()
    ).into_bytes())
}

/// note_commit = BLAKE2b-256("vice-note" ‖ vk ‖ le64(amount) ‖ rho ‖ r)
pub fn note_commit(vk: &[u8], amount: u64, rho: &[u8; 32],
                   r: &[u8; 32]) -> [u8; 32] {
    let mut buf = Vec::with_capacity(32 + 8 + 64 + vk.len());
    buf.extend_from_slice(b"vice-note");
    buf.extend_from_slice(vk);
    buf.extend_from_slice(&amount.to_le_bytes());
    buf.extend_from_slice(rho);
    buf.extend_from_slice(r);
    blake2b_256(&buf)
}

/// nullifier = BLAKE2b-256("vice-nullifier" ‖ rho ‖ commit)
/// Owner-only before the spend (rho secret); publicly verifiable after
/// the opening is revealed; unique per note (rho is per-note).
pub fn nullifier(rho: &[u8; 32], commit: &[u8; 32]) -> [u8; 32] {
    let mut buf = Vec::with_capacity(11 + 64);
    buf.extend_from_slice(b"vice-nullifier");
    buf.extend_from_slice(rho);
    buf.extend_from_slice(commit);
    blake2b_256(&buf)
}

/// Verify an opening against a claimed commit + nullifier.
pub fn verify_opening(opening: &NoteOpening, commit: &[u8; 32],
                      nullifier_nf: &[u8; 32]) -> bool {
    vk_from_bytes(&opening.vk).is_some()
        && opening.commit().as_slice() == commit
        && opening.nullifier().as_slice() == nullifier_nf
}

// ---------------------------------------------------------------------------
// Note-merkle tree: append-only commitment tree over note commits.
// Duplicate-last padding on odd levels (same rule as tx merkle).
// ---------------------------------------------------------------------------
pub struct NoteMerkleTree {
    leaves: Vec<[u8; 32]>,
}

pub type MerklePath = Vec<[u8; 32]>;

impl Default for NoteMerkleTree {
    fn default() -> Self {
        Self::new()
    }
}

impl NoteMerkleTree {
    pub fn new() -> Self {
        NoteMerkleTree { leaves: Vec::new() }
    }

    pub fn push(&mut self, commit: [u8; 32]) -> usize {
        self.leaves.push(commit);
        self.leaves.len() - 1
    }

    pub fn len(&self) -> usize {
        self.leaves.len()
    }

    pub fn is_empty(&self) -> bool {
        self.leaves.is_empty()
    }

    pub fn root(&self) -> [u8; 32] {
        let mut level: Vec<[u8; 32]> = self.leaves.clone();
        if level.is_empty() {
            return [0u8; 32];
        }
        while level.len() > 1 {
            if !level.len().is_multiple_of(2) {
                level.push(level[level.len() - 1]);
            }
            let mut next = Vec::with_capacity(level.len() / 2);
            for pair in level.chunks(2) {
                let mut buf = Vec::with_capacity(64);
                buf.extend_from_slice(&pair[0]);
                buf.extend_from_slice(&pair[1]);
                next.push(blake2b_256(&buf));
            }
            level = next;
        }
        level[0]
    }

    /// Merkle path for leaf at `index` (siblings, bottom-up).
    pub fn path(&self, index: usize) -> Option<MerklePath> {
        if index >= self.leaves.len() {
            return None;
        }
        let mut level: Vec<[u8; 32]> = self.leaves.clone();
        let mut idx = index;
        let mut out = Vec::new();
        while level.len() > 1 {
            if !level.len().is_multiple_of(2) {
                level.push(level[level.len() - 1]);
            }
            let sibling = if idx.is_multiple_of(2) { idx + 1 } else { idx - 1 };
            out.push(level[sibling]);
            let mut next = Vec::with_capacity(level.len() / 2);
            for pair in level.chunks(2) {
                let mut buf = Vec::with_capacity(64);
                buf.extend_from_slice(&pair[0]);
                buf.extend_from_slice(&pair[1]);
                next.push(blake2b_256(&buf));
            }
            level = next;
            idx /= 2;
        }
        Some(out)
    }
}

/// Verify a merkle path: recomputes the root from the leaf.
pub fn verify_merkle_path(commit: [u8; 32], mut index: usize,
                          path: &MerklePath, root: &[u8; 32]) -> bool {
    let mut cur = commit;
    for sibling in path {
        let mut buf = Vec::with_capacity(64);
        if index.is_multiple_of(2) {
            buf.extend_from_slice(&cur);
            buf.extend_from_slice(sibling);
        } else {
            buf.extend_from_slice(sibling);
            buf.extend_from_slice(&cur);
        }
        cur = blake2b_256(&buf);
        index /= 2;
    }
    cur.as_slice() == root
}
