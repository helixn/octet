//! Vice City consensus core — OctetHash light-path verification.
//!
//! The reference oracle is `reference/octet_ref.py`; this crate must match it
//! bit-for-bit. The committed vector snapshots (`tests/vectors/`,
//! `tests/fullscale/`) are the acceptance gate — see the tests directory.
pub mod pow;

pub use pow::{epoch_seed, block_seed, gen_cache, solve, verify, Profile,
              FULL_SCALE, TEST_PROFILE};
