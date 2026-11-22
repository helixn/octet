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
    /// Retarget window: difficulty updates every N blocks (deterministic,
    /// chain-derived). MUST be >= 1 (1 = per-block retarget; 0 is invalid —
    /// template and validation disagree at 0).
    pub retarget_interval: u64,
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
    retarget_interval: 10,
    max_block_bytes: 1_048_576,
};

/// Testnet: fast profile, everything allowed — this is a playground.
pub const TESTNET: Params = Params {
    profile: TEST_PROFILE,
    target: [0xffu8; 32],
    subsidy: 10,
    halving_interval: 262_800,
    block_time_secs: 120,
    retarget_interval: 10,
    max_block_bytes: 1_048_576,
};

/// Subsidy at a given height (halving, pow.md §7 follow-up).
pub fn subsidy_at(p: &Params, height: u64) -> u64 {
    let halvings = height / p.halving_interval;
    p.subsidy.saturating_sub(halvings.min(63))
}

/// Difficulty retarget (Phase 2d, §9): per-block adjustment clamped to ±4x.
/// Target is a 32-byte big-endian integer; "harder" = numerically smaller.
/// The ratio actual/expected is quantized to {4x, 2x, 1x} via exact bit
/// shifts on the 256-bit value — no big-num dependency, no rounding drift.
pub fn next_target(prev_target: &[u8; 32], actual_secs: u64,
                   expected_secs: u64) -> [u8; 32] {
    let mut out = *prev_target;
    if expected_secs == 0 || actual_secs == 0 {
        return out;
    }
    let levels: u32 = if actual_secs > expected_secs {
        match actual_secs / expected_secs {
            1 => 0,
            2..=3 => 1,
            _ => 2, // 4x+ — clamp at 2 levels (=4x)
        }
    } else if expected_secs > actual_secs {
        match expected_secs / actual_secs {
            1 => 0,
            2..=3 => 1,
            _ => 2,
        }
    } else {
        0
    };
    if levels == 0 {
        return out;
    }
    let bits = levels; // 1 level = 1 bit = 2x; 2 levels = 2 bits = 4x
    // bit array, MSB first: bit[i] has weight 2^(255-i)
    let bit = |v: &[u8; 32], i: usize| (v[i / 8] >> (7 - i % 8)) & 1 == 1;
    let mut next = [0u8; 32];
    if actual_secs > expected_secs {
        // easier = multiply by 2^bits: bit moves toward MSB, top bits drop
        // (natural saturation: an already-max target stays ~max)
        for i in 0..256 - bits as usize {
            if bit(prev_target, i + bits as usize) {
                next[i / 8] |= 1 << (7 - i % 8);
            }
        }
    } else {
        // harder = divide by 2^bits: zeros enter from the MSB side
        for i in bits as usize..256 {
            if bit(prev_target, i - bits as usize) {
                next[i / 8] |= 1 << (7 - i % 8);
            }
        }
        // difficulty floor: never divide the target to zero — the smallest
        // valid target is 0x0000…0001 (a chain at target 0 can never mine)
        if next == [0u8; 32] {
            let mut floor = [0u8; 32];
            floor[31] = 1;
            return floor;
        }
    }
    out = next;
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fast_blocks_tighten_target() {
        let mut start = [0xffu8; 32];
        start[0] = 0xff;
        start[1] = 0xff; // ~max target
        let next = next_target(&start, 30, 120); // 4x too fast -> harder (>>2)
        assert!(next < start, "target must shrink (harder)");
        assert_eq!(next[0], 0x3f, "4x = top byte >>2");
        assert_eq!(next[1], 0xff, "carry fills the second byte");
    }

    #[test]
    fn slow_blocks_loosen_target() {
        let mut start = [0xffu8; 32];
        start[0] = 0x3f; // far below max
        let next = next_target(&start, 480, 120); // 4x too slow -> easier
        assert!(next > start, "target must grow (easier)");
        assert_eq!(next[0], 0xff, "<<2 saturates the top byte toward max");
    }

    #[test]
    fn on_time_blocks_keep_target() {
        let start = [0xaau8; 32];
        assert_eq!(next_target(&start, 120, 120), start);
        assert_eq!(next_target(&start, 121, 120), start);
        assert_eq!(next_target(&start, 119, 120), start);
    }

    #[test]
    fn difficulty_floor_never_zero_target() {
        let mut start = [0u8; 32];
        start[31] = 1; // smallest valid target
        let next = next_target(&start, 1, 120); // way too fast -> harder
        assert_eq!(next, start, "floor: smallest target must not divide to 0");
    }

    #[test]
    fn clamp_at_max_difficulty_floor() {
        // target already tiny: harder request must not underflow
        let mut start = [0xffu8; 32];
        start[0] = 0x00;
        start[1] = 0x01;
        let next = next_target(&start, 1, 120);
        assert!(next <= start);
    }
}
