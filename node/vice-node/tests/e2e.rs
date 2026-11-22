//! Phase 2e end-to-end: genesis -> mine block 1 (coinbase) -> fund wallet ->
//! mempool tx -> mine block 2 -> balances; then a second node syncs from the
//! first over real TCP p2p. Testnet params (fast profile) — CPU search finds
//! the target instantly.
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use vice_core::tx::Transaction;
use vice_core::addr::vc_address;
use vice_core::{keygen, TESTNET};
fn commit_of(vk: &[u8]) -> String {
    hex::encode(vice_core::addr::commit_of_vk(vk))
}

fn vk_of(kp: &vice_core::addr::KeyPair) -> Vec<u8> {
    vice_core::addr::vk_bytes(&kp.vk)
}

fn mine_and_submit(state: &Arc<Mutex<vice_node::NodeState>>,
                   commit: &str) -> String {
    let block = state.lock().unwrap().template(commit);
    // CPU search on the fast profile against the template's (retargeted)
    // target — block 1 passes instantly, later blocks may tighten
    let pow_header = block.pow_header();
    let seed_epoch = state.lock().unwrap().seed_epoch();
    let seed_block_bytes =
        hex::decode(&block.header.seed_block).expect("seed");
    let cache = state.lock().unwrap().cache();
    let target: [u8; 32] = hex::decode(&block.header.target)
        .expect("hex target")
        .try_into()
        .expect("32 B");
    let mut nonce = 0u64;
    let solution = loop {
        let s = vice_core::solve(&pow_header, nonce, &TESTNET.profile, &cache,
                                 &seed_epoch, &seed_block_bytes, None);
        if s.as_slice() <= target.as_slice() {
            break s;
        }
        nonce += 1;
    };
    let mut block = block;
    block.header.nonce = nonce;
    block.header.solution = hex::encode(solution);
    state.lock().unwrap().accept_block(block).expect("accept")
}

#[test]
fn e2e_chain_mine_tx_sync() {
    let dir1 = std::env::temp_dir().join("vice_e2e_node1");
    let _ = std::fs::remove_dir_all(&dir1);
    let miner_kp = keygen();
    let miner_commit = commit_of(&vk_of(&miner_kp));
    let node1 = Arc::new(Mutex::new(vice_node::NodeState::new(
        TESTNET, dir1, miner_commit.clone(), vec![],
    )));

    // block 1: coinbase pays the subsidy to the miner commit
    let id1 = mine_and_submit(&node1, &miner_commit);
    assert_eq!(node1.lock().unwrap().height(), 1);
    assert_eq!(
        node1.lock().unwrap().balance(&miner_commit),
        TESTNET.subsidy,
        "coinbase credit missing"
    );

    // fund a fresh wallet from the coinbase, tx into the mempool
    let payer_kp = miner_kp;
    let recv_kp = keygen();
    let recv_commit = commit_of(&vk_of(&recv_kp));
    let _addr = vc_address(&vk_of(&recv_kp));
    let cb_txid = node1.lock().unwrap().coinbase_txid(1);
    let mut tx = Transaction {
        version: 1,
        inputs: vec![vice_core::tx::TxIn {
            prev_txid: cb_txid,
            out_index: 0,
            vk: Vec::new(),
            sig: Vec::new(),
        }],
        outputs: vec![vice_core::tx::TxOut {
            commit: recv_commit.clone(),
            amount: TESTNET.subsidy - 1, // keep 1 VC as "fee"
        }],
    };
    tx.sign_inputs(&payer_kp.sk, &vk_of(&payer_kp));
    let txid = node1.lock().unwrap().accept_tx(tx).expect("mempool");
    assert_eq!(node1.lock().unwrap().mempool_len(), 1);

    // block 2 includes the tx; receiver credited, payer spent
    let pre_window_target = node1.lock().unwrap().tip_target();
    let id2 = mine_and_submit(&node1, &miner_commit);
    assert_eq!(node1.lock().unwrap().height(), 2);
    // windowed retarget (§9): inside a window the target is unchanged —
    // it updates only every retarget_interval blocks (live at height 10)
    assert_eq!(
        node1.lock().unwrap().tip_target(),
        pre_window_target,
        "target must stay flat inside the retarget window"
    );
    assert_eq!(node1.lock().unwrap().balance(&recv_commit),
               TESTNET.subsidy - 1);
    assert_eq!(node1.lock().unwrap().mempool_len(), 0);
    assert_ne!(id1, id2);

    // second node syncs over real TCP p2p
    let dir2 = std::env::temp_dir().join("vice_e2e_node2");
    let _ = std::fs::remove_dir_all(&dir2);
    let node2 = Arc::new(Mutex::new(vice_node::NodeState::new(
        TESTNET, PathBuf::from(&dir2), miner_commit.clone(), vec![],
    )));
    assert_eq!(node2.lock().unwrap().height(), 0, "fresh node");
    vice_node::NodeState::start_p2p(Arc::clone(&node1), 19393);
    vice_node::NodeState::start_p2p(Arc::clone(&node2), 19394);
    node2.lock().unwrap().add_peer("127.0.0.1:19393".to_string());
    node2.lock().unwrap().sync_once();
    std::thread::sleep(Duration::from_millis(300));
    assert_eq!(node2.lock().unwrap().height(), 2, "synced from peer");
    assert_eq!(node2.lock().unwrap().balance(&recv_commit),
               TESTNET.subsidy - 1, "utxo synced");
}
