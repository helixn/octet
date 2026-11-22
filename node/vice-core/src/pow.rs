//! OctetHash v0.3 (docs/pow.md) — the light path: derive every dataset item
//! from the 128 MiB cache + per-block keystream. Used by nodes to verify
//! claimed solutions without storing any dataset.
//!
//! Bit-exactness contract: `reference/octet_ref.py` is the oracle; any
//! divergence here is a bug in this crate (AGENTS.md §2.1).
use blake2::digest::{Update, VariableOutput};
use blake2::Blake2bVar;

/// One parameter set. Test profile mirrors `reference.TEST_PROFILE`
/// (drives the committed vector snapshot); full scale is the v0.3 genesis
/// (docs/pow.md §3, growth schedule §10.1 applies from the node later).
#[derive(Clone, Copy, Debug)]
pub struct Profile {
    pub cache_words: usize,
    pub dataset_items: usize,
    pub item_parents: usize,
    pub lanes: usize,
    pub lanes_per_block: usize,
    pub rounds: usize,
}

pub const TEST_PROFILE: Profile = Profile {
    cache_words: 2048,
    dataset_items: 4096,
    item_parents: 8,
    lanes: 256,
    lanes_per_block: 256,
    rounds: 8,
};

pub const FULL_SCALE: Profile = Profile {
    cache_words: 1 << 21,   // 128 MiB / 64 B
    dataset_items: 1 << 24, // 4 GiB / 256 B (genesis)
    item_parents: 32,
    lanes: 4096,
    lanes_per_block: 1024,
    rounds: 16,
};

/// Streaming BLAKE2b over concatenated parts, variable digest size —
/// identical semantics to Python hashlib.blake2b(digest_size=N).
fn h(parts: &[&[u8]], size: usize) -> Vec<u8> {
    let mut hasher = Blake2bVar::new(size).expect("digest size <= 64");
    for p in parts {
        hasher.update(p);
    }
    let mut out = vec![0u8; size];
    hasher.finalize_variable(&mut out).expect("exact buffer");
    out
}

fn le64(v: u64) -> [u8; 8] {
    v.to_le_bytes()
}

/// `seed_epoch = H(b"octet-epoch" ‖ le64(epoch) ‖ epoch_seed_hash)` (64 B).
pub fn epoch_seed(epoch: u64, seed_hash: &[u8; 32]) -> Vec<u8> {
    h(&[b"octet-epoch", &le64(epoch), seed_hash], 64)
}

/// `seed_block = H(b"octet-block" ‖ prev_solution_hash ‖ le64(height))` (64 B).
pub fn block_seed(prev_solution_hash: &[u8], height: u64) -> Vec<u8> {
    h(&[b"octet-block", prev_solution_hash, &le64(height)], 64)
}

/// Cache of the epoch: `cache[0] = H(b"octet-cache" ‖ seed)`;
/// `cache[i] = H(cache[i-1] ‖ seed ‖ le64(i))`. Sequential chain (pow.md §4.1).
pub fn gen_cache(seed_epoch: &[u8], cache_words: usize) -> Vec<Vec<u8>> {
    let mut cache = Vec::with_capacity(cache_words);
    cache.push(h(&[b"octet-cache", seed_epoch], 64));
    for i in 1..cache_words {
        let prev = cache[i - 1].clone();
        cache.push(h(&[&prev, seed_epoch, &le64(i as u64)], 64));
    }
    cache
}

/// Dataset item (pow.md §4.2): acc chain over 32 parents, 4×64 B.
fn dataset_item(j: usize, cache: &[Vec<u8>], seed_epoch: &[u8],
                parents: usize) -> Vec<u8> {
    let mut acc = h(&[seed_epoch, &le64(j as u64)], 64);
    for k in 0..parents {
        let pd = h(&[seed_epoch, &le64(j as u64), &le64(k as u64)], 8);
        let be = u64::from_be_bytes(pd.try_into().expect("8 bytes"));
        let p = (be % cache.len() as u64) as usize;
        acc = h(&[&acc, &cache[p]], 64);
    }
    let mut item = Vec::with_capacity(256);
    for c in 0u64..4 {
        item.extend_from_slice(&h(&[&acc, &le64(c)], 64));
    }
    item
}

/// Keystream (pow.md §4.3): 4× H(seed_block ‖ le64(j) ‖ le64(c)).
fn keystream_item(j: usize, seed_block: &[u8]) -> Vec<u8> {
    let mut ks = Vec::with_capacity(256);
    for c in 0u64..4 {
        ks.extend_from_slice(&h(&[seed_block, &le64(j as u64), &le64(c)], 64));
    }
    ks
}

/// Effective item = base ⊕ keystream (light path derives it on the fly).
fn effective_item(j: usize, cache: &[Vec<u8>], seed_epoch: &[u8],
                  parents: usize, seed_block: &[u8]) -> Vec<u8> {
    let base = dataset_item(j, cache, seed_epoch, parents);
    let ks = keystream_item(j, seed_block);
    base.iter().zip(ks.iter()).map(|(a, b)| a ^ b).collect()
}

/// One full attempt, light path. Returns the 32 B final hash.
pub fn solve(header: &[u8], nonce: u64, p: &Profile, cache: &[Vec<u8>],
             seed_epoch: &[u8], seed_block: &[u8], mut states_log: Option<&mut Vec<Vec<u8>>>) -> Vec<u8> {
    let stride_bits = p.lanes_per_block.trailing_zeros() as usize;
    let seed = h(&[b"octet-pow", header, &le64(nonce)], 32);
    let mut states: Vec<Vec<u8>> = (0..p.lanes)
        .map(|i| h(&[b"lane", &seed, &le64(i as u64)], 32))
        .collect();
    if let Some(log) = states_log.as_deref_mut() {
        log.push(states.concat());
    }
    for r in 0..p.rounds {
        for state in states.iter_mut() {
            let addr = u32::from_be_bytes(
                state[..4].try_into().expect("4 bytes"))
                as usize % p.dataset_items;
            let item = effective_item(addr, cache, seed_epoch,
                                      p.item_parents, seed_block);
            *state = h(&[state.as_slice(), &item], 32);
        }
        let b = r % stride_bits;
        let prev = states.clone();
        for (i, state) in states.iter_mut().enumerate() {
            let partner = i ^ (1usize << b);
            for k in 0..32 {
                state[k] ^= prev[partner][k];
            }
        }
        if let Some(log) = states_log.as_deref_mut() {
            log.push(states.concat());
        }
    }
    h(&[&states.concat()], 32)
}

/// Node-side verification: recompute the attempt from the cache, compare
/// against the difficulty target (big-endian compare, pow.md §6).
pub fn verify(header: &[u8], nonce: u64, target: &[u8], p: &Profile,
              cache: &[Vec<u8>], seed_epoch: &[u8], seed_block: &[u8]) -> bool {
    let final_hash = solve(header, nonce, p, cache, seed_epoch, seed_block, None);
    let f = be_bytes(&final_hash);
    let t = be_bytes(target);
    f <= t
}

fn be_bytes(v: &[u8]) -> Vec<u8> {
    v.iter().rev().cloned().collect()
}
