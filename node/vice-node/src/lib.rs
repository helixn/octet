//! Vice City node library: chain state, mempool, RPC, P2P (Phase 2c+2d).
pub mod node;
pub use node::{NodeState, rpc_loop};
