//! Vice City consensus core — OctetHash light-path verification, addresses,
//! transactions, blocks and chain validation.
//!
//! The reference oracle is `reference/octet_ref.py`; this crate must match it
//! bit-for-bit. The committed vector snapshots (`tests/vectors/`,
//! `tests/fullscale/`) are the acceptance gate — see the tests directory.
pub mod addr;
pub mod notes;
pub mod offers;
pub mod params;
pub mod pow;
pub mod tx;

pub use addr::{keygen, vc_address};
pub use notes::{NoteMerkleTree, NoteOpening, nullifier as note_nullifier,
                note_commit as note_commit_pub, verify_merkle_path};
pub use params::{Params, MAINNET, TESTNET};
pub use pow::{block_seed, epoch_seed, gen_cache, solve, verify, Profile,
              FULL_SCALE, TEST_PROFILE};
pub use tx::{coinbase_prev_txid, parse_coinbase_height, validate_block,
             Block, BlockHeader, Transaction, TxIn, TxOut, UtxoSet};
