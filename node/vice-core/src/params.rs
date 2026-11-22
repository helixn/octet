//! Consensus parameters. Testnet runs the fast TEST_PROFILE so CPU mining is
//! viable for proof-of-life; mainnet uses the v0.3 genesis (FULL_SCALE 4 GiB,
//! docs/pow.md §10.1). Economics are TESTNET-only values — mainnet emission
//! goes through pow-spec-review before genesis.
use crate::pow::{Profile, FULL_SCALE, TEST_PROFILE};

#[derive(Clone, Copy, Debug)]
pub struct Params {
    pub profile: Profile,
    /// Difficulty target: solution (32 B, big-endian) must be <= target.
    pub target: [u8; 32],
    pub subsidy: u64,
    pub halving_interval: u64,
    pub block_time_secs: u64,
    pub max_block_bytes: usize,
}

/// Mainnet v0.3 genesis: 4 GiB profile, subsidy 10 VC, halving ~1 year.
/// ⚠ KNOWN PHASE-2 GAP (gate review K5): the target below is zero-difficulty.
/// DO NOT LAUNCH MAINNET until the retarget (Phase 2d+) replaces it.
pub const MAINNET: Params = Params {
    profile: FULL_SCALE,
    target: [0xffu8; 32], // ⚠ zero difficulty — retarget required before launch
    subsidy: 10,
    halving_interval: 262_800,
    block_time_secs: 120,
    max_block_bytes: 1_048_576,
};

/// Testnet: fast profile, everything allowed — this is a playground.
pub const TESTNET: Params = Params {
    profile: TEST_PROFILE,
    target: [0xffu8; 32],
    subsidy: 10,
    halving_interval: 262_800,
    block_time_secs: 120,
    max_block_bytes: 1_048_576,
};

/// Subsidy at a given height (halving, pow.md §7 follow-up).
pub fn subsidy_at(p: &Params, height: u64) -> u64 {
    let halvings = height / p.halving_interval;
    p.subsidy.saturating_sub(halvings.min(63))
}
