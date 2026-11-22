//! Transactions, blocks, merkle root, chain state and validation (2b).
//! Tier 0 transparent model: outputs locked to `commit = BLAKE2b-256(vk)`.
//! Note pool (Tier 2) structures are reserved by the genesis design —
//! see docs/crypto.md §3; nothing ECC ever enters consensus.
use crate::addr::{blake2b_256, commit_of_vk, verify as dsa_verify};
use crate::params::{subsidy_at, Params};
use serde::{Deserialize, Serialize};

/// BIP-34-style height commitment: the coinbase input references
/// "coinbase:<le64(height) hex>" so every block's coinbase txid is unique
/// (gate review K2 — prevents coinbase outpoint resurrection).
pub fn coinbase_prev_txid(height: u64) -> String {
    format!("coinbase:{}", hex::encode(height.to_le_bytes()))
}

pub fn parse_coinbase_height(prev_txid: &str) -> Option<u64> {
    let raw = hex::decode(prev_txid.strip_prefix("coinbase:")?).ok()?;
    if raw.len() != 8 {
        return None;
    }
    Some(u64::from_le_bytes(raw.try_into().ok()?))
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TxIn {
    pub prev_txid: String, // hex; COINBASE_INPUT for coinbase
    pub out_index: u32,
    /// ML-DSA-65 verification key of the spender (revealed at spend — crypto.md §2)
    pub vk: Vec<u8>,
    /// ML-DSA-65 signature over the txid of this transaction
    pub sig: Vec<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TxOut {
    pub commit: String, // hex of BLAKE2b-256(vk)
    pub amount: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Transaction {
    pub version: u32,
    pub inputs: Vec<TxIn>,
    pub outputs: Vec<TxOut>,
}

impl Transaction {
    /// Canonical unsigned payload — what the signature commits to.
    fn unsigned_payload(&self) -> Vec<u8> {
        let shadow: Vec<_> = self
            .inputs
            .iter()
            .map(|i| (i.prev_txid.clone(), i.out_index))
            .collect();
        serde_json::to_vec(&(&self.version, &shadow, &self.outputs))
            .expect("serialize")
    }

    pub fn txid(&self) -> [u8; 32] {
        blake2b_256(&self.unsigned_payload())
    }

    pub fn txid_hex(&self) -> String {
        hex::encode(self.txid())
    }

    pub fn is_coinbase(&self) -> bool {
        self.inputs.len() == 1 && self.inputs[0].prev_txid.starts_with("coinbase:")
    }

    pub fn sign_inputs(&mut self, sk: &ml_dsa::SigningKey<ml_dsa::MlDsa65>,
                       vk_bytes: &[u8]) {
        let txid = self.txid();
        for input in &mut self.inputs {
            input.vk = vk_bytes.to_vec();
            input.sig = crate::addr::sign(sk, &txid);
        }
    }
}

pub fn merkle_root(txids: &[[u8; 32]]) -> [u8; 32] {
    if txids.is_empty() {
        return [0u8; 32];
    }
    let mut level: Vec<[u8; 32]> = txids.to_vec();
    while level.len() > 1 {
        if level.len() % 2 == 1 {
            level.push(level[level.len() - 1]); // duplicate-last (BIP-141 style)
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

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BlockHeader {
    pub version: u32,
    pub height: u64,
    pub prev_hash: String,      // hex blake2b-256 of the parent header payload
    pub merkle_root: String,
    pub timestamp: u64,
    pub target: String,         // hex, big-endian compare against `solution`
    pub seed_block: String,     // hex, 64 B — binds the PoW dataset re-key
    pub nonce: u64,
    pub solution: String,       // hex 32 B — final hash of the OctetHash attempt
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Block {
    pub header: BlockHeader,
    pub txs: Vec<Transaction>,
}

impl Block {
    /// The bytes fed to OctetHash: header payload without nonce/solution.
    pub fn pow_header(&self) -> [u8; 32] {
        let shadow = (
            self.header.version,
            self.header.height,
            &self.header.prev_hash,
            &self.header.merkle_root,
            self.header.timestamp,
            &self.header.target,
            &self.header.seed_block,
        );
        blake2b_256(&serde_json::to_vec(&shadow).expect("serialize"))
    }

    /// Header identity (includes nonce + solution).
    pub fn block_id(&self) -> [u8; 32] {
        blake2b_256(&serde_json::to_vec(&self.header).expect("serialize"))
    }

    pub fn block_id_hex(&self) -> String {
        hex::encode(self.block_id())
    }
}

/// UTXO set: (txid, out_index) -> (commit_hex, amount).
pub type UtxoSet = std::collections::HashMap<(String, u32), (String, u64)>;

#[derive(Debug)]
pub enum ValidationError {
    PrevHashMismatch { expected: String, got: String },
    HeightMismatch { expected: u64, got: u64 },
    MerkleMismatch,
    PowMismatch,
    TargetNotMet,
    CoinbaseMissing,
    CoinbaseWrongSubsidy { expected: u64, got: u64 },
    CoinbaseHeightMismatch { expected: u64 },
    SeedBlockMismatch { expected: String, got: String },
    TargetMismatch { expected: String, got: String },
    TimestampNotMonotonic { mtp: u64, got: u64 },
    TimestampTooFarFuture { max: u64, got: u64 },
    DoubleSpend,
    UnknownOutpoint,
    BadSignature { input_index: usize },
    Overspend { in_total: u64, out_total: u64 },
    EmptyOutputs,
    BlockTooLarge,
}

/// Validate a block against the current tip (p.chain is the tip header hash).
/// Recomputes balances implied by the block's txs.
/// Everything the validator needs about the current tip — all on-chain data,
/// so every node computes identical expectations for the same block.
pub struct TipContext<'a> {
    pub height: u64,
    pub prev_hash: &'a str,
    pub tip_solution: &'a [u8],
    pub tip_target: [u8; 32],
    /// Median of the last 11 block timestamps (chain data, Bitcoin-style):
    /// the base for the declared timestamp (lower bound + retarget input).
    pub mtp: u64,
    /// Node-local clock (Bitcoin-style MAX_FUTURE check): the upper bound is
    /// node-local because a purely chain-derived bound would make mining
    /// impossible after any chain idle longer than the bound. Nondeterminism
    /// is bounded by clock drift (seconds); future-timestamp attacks beyond
    /// the bound are rejected by every honest node (documented trade-off).
    pub node_now: u64,
    /// Timestamp of the retarget-window start block (height−interval) —
    /// the elapsed time of the window is measured from it.
    pub window_start_ts: u64,
}

pub fn validate_block(
    block: &Block,
    params: &Params,
    tip: &TipContext,
    utxo: &UtxoSet,
    cache: &[Vec<u8>],
    seed_epoch: &[u8],
) -> Result<UtxoSet, ValidationError> {
    let height = tip.height;
    let prev_hash = tip.prev_hash;
    let size = serde_json::to_vec(block).map(|v| v.len()).unwrap_or(usize::MAX);
    if size > params.max_block_bytes {
        return Err(ValidationError::BlockTooLarge);
    }
    if block.header.height != height {
        return Err(ValidationError::HeightMismatch {
            expected: height,
            got: block.header.height,
        });
    }
    if block.header.prev_hash != prev_hash {
        return Err(ValidationError::PrevHashMismatch {
            expected: prev_hash.to_string(),
            got: block.header.prev_hash.clone(),
        });
    }
    // merkle
    let txids: Vec<[u8; 32]> = block.txs.iter().map(|t| t.txid()).collect();
    let root = merkle_root(&txids);
    if hex::encode(root) != block.header.merkle_root {
        return Err(ValidationError::MerkleMismatch);
    }
    // coinbase
    let coinbase = block.txs.first().ok_or(ValidationError::CoinbaseMissing)?;
    if !coinbase.is_coinbase() {
        return Err(ValidationError::CoinbaseMissing);
    }
    // BIP-34 analog: coinbase commits to its own height (gate K2)
    if parse_coinbase_height(&coinbase.inputs[0].prev_txid) != Some(height) {
        return Err(ValidationError::CoinbaseHeightMismatch { expected: height });
    }
    // timestamp rules (gate C1/C2):
    // lower bound (chain data, deterministic): ts > MTP(11)
    // upper bound (Bitcoin-style, node-local): ts <= now + 12 * block_time —
    // stops future-timestamp difficulty attacks; a purely chain-derived
    // upper bound would brick mining after any chain idle > bound
    if block.header.timestamp <= tip.mtp {
        return Err(ValidationError::TimestampNotMonotonic {
            mtp: tip.mtp,
            got: block.header.timestamp,
        });
    }
    let max_ts = tip.node_now + 12 * params.block_time_secs;
    if block.header.timestamp > max_ts {
        return Err(ValidationError::TimestampTooFarFuture {
            max: max_ts,
            got: block.header.timestamp,
        });
    }
    // header-only retarget continuity BEFORE the expensive light-path solve:
    // windowed (every retarget_interval blocks), input derived ONLY from
    // chain data: window elapsed = block ts − window-start ts
    let expected_target: [u8; 32] = if params.retarget_interval > 0
        && height.is_multiple_of(params.retarget_interval)
    {
        let window = block.header.timestamp.saturating_sub(tip.window_start_ts);
        crate::params::next_target(&tip.tip_target,
                                   window / params.retarget_interval.max(1),
                                   params.block_time_secs)
    } else {
        tip.tip_target
    };
    if hex::encode(expected_target) != block.header.target {
        return Err(ValidationError::TargetMismatch {
            expected: hex::encode(expected_target),
            got: block.header.target.clone(),
        });
    }
    // per-block re-key binding (gate K1): the dataset keystream seed is
    // derived from the parent solution and the new height — a miner cannot
    // pin one dataset across blocks (pow.md §4.3)
    let expected_seed = crate::pow::block_seed(tip.tip_solution, height);
    if hex::encode(&expected_seed) != block.header.seed_block {
        return Err(ValidationError::SeedBlockMismatch {
            expected: hex::encode(&expected_seed),
            got: block.header.seed_block.clone(),
        });
    }
    let expected_subsidy = subsidy_at(params, height);
    let cb_out: u64 = coinbase.outputs.iter().map(|o| o.amount).sum();
    if cb_out != expected_subsidy {
        return Err(ValidationError::CoinbaseWrongSubsidy {
            expected: expected_subsidy,
            got: cb_out,
        });
    }
    let cb_txid_hex = hex::encode(coinbase.txid());
    let mut next: UtxoSet = utxo.clone();
    for (out_idx, out) in coinbase.outputs.iter().enumerate() {
        next.insert((cb_txid_hex.clone(), out_idx as u32),
                    (out.commit.clone(), out.amount));
    }
    // PoW: light-path recompute from cache (the oracle-consistent check)
    let pow_header = block.pow_header();
    let nonce = block.header.nonce;
    // the enforced seed (== header.seed_block, checked above) drives the PoW
    let solution = crate::pow::solve(&pow_header, nonce, &params.profile,
                                     cache, seed_epoch, &expected_seed, None);
    if hex::encode(&solution) != block.header.solution {
        return Err(ValidationError::PowMismatch);
    }
    // PoW must meet the (already validated) target
    if solution.as_slice() > expected_target.as_slice() {
        return Err(ValidationError::TargetNotMet);
    }
    // transactions
    for (idx, tx) in block.txs.iter().enumerate().skip(1) {
        if tx.outputs.is_empty() {
            return Err(ValidationError::EmptyOutputs);
        }
        let txid = tx.txid();
        let mut in_total = 0u64;
        for input in &tx.inputs {
            let key = (input.prev_txid.clone(), input.out_index);
            let Some((commit, amount)) = next.get(&key) else {
                return Err(ValidationError::UnknownOutpoint);
            };
            // signature over this tx's txid, by the key that owns the outpoint
            if hex::encode(commit_of_vk(&input.vk)) != *commit
                || !dsa_verify(
                    &crate::addr::vk_from_bytes(&input.vk)
                        .ok_or(ValidationError::BadSignature { input_index: idx })?,
                    &txid,
                    &input.sig,
                )
            {
                return Err(ValidationError::BadSignature { input_index: idx });
            }
            in_total += amount;
            next.remove(&key);
        }
        let out_total: u64 = tx.outputs.iter().map(|o| o.amount).sum();
        if out_total > in_total {
            return Err(ValidationError::Overspend { in_total, out_total });
        }
        for (out_idx, out) in tx.outputs.iter().enumerate() {
            next.insert((hex::encode(txid), out_idx as u32),
                        (out.commit.clone(), out.amount));
        }
    }
    Ok(next)
}

/// Insert outputs with proper indices (called inside apply above — kept as a
/// helper for tests that build custom flows).
pub fn insert_outputs(utxo: &mut UtxoSet, txid_hex: &str, tx: &Transaction) {
    for (idx, out) in tx.outputs.iter().enumerate() {
        utxo.insert((txid_hex.to_string(), idx as u32),
                    (out.commit.clone(), out.amount));
    }
}
