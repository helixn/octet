//! Gate-review test gap: the window branch (height % retarget_interval == 0)
//! of validate_block — template and validation must agree at the window
//! boundary. Synthetic TipContext, TEST_PROFILE cache (fast).
use vice_core::tx::{validate_block, Block, BlockHeader, TipContext,
                    Transaction, TxIn, TxOut};
use vice_core::{block_seed, epoch_seed, gen_cache, solve, TEST_PROFILE,
                TESTNET};

fn window_block(height: u64, tip_target: [u8; 32], window_start_ts: u64,
                ts: u64, mtp: u64, _node_now: u64, tip_solution: &[u8],
                cache: &[Vec<u8>], seed_epoch: &[u8]) -> Block {
    // the template's own computation (must match the validator):
    let window = ts.saturating_sub(window_start_ts);
    let expected = vice_core::params::next_target(
        &tip_target,
        window / TESTNET.retarget_interval,
        TESTNET.block_time_secs,
    );
    let coinbase = Transaction {
        version: 1,
        inputs: vec![TxIn {
            prev_txid: vice_core::tx::coinbase_prev_txid(height),
            out_index: 0,
            vk: Vec::new(),
            sig: Vec::new(),
            note_spend: None,
        }],
        outputs: vec![TxOut {
            commit: hex::encode([0u8; 32]),
            amount: vice_core::params::subsidy_at(&TESTNET, height),
            note_commit: None,
        }],
        offer: None,
    };
    let seed_block = block_seed(tip_solution, height);
    let mut header = BlockHeader {
        version: 1,
        height,
        prev_hash: hex::encode([0x11u8; 32]), // synthetic tip id
        merkle_root: hex::encode(vice_core::tx::merkle_root(&[coinbase
            .txid()])),
        timestamp: ts,
        target: hex::encode(expected),
        seed_block: hex::encode(&seed_block),
        note_root: hex::encode([0u8; 32]),
        nonce: 0,
        solution: hex::encode([0u8; 32]),
    };
    let mut block = Block { header, txs: vec![coinbase] };
    // search a valid nonce+solution against the target
    let pow_header = block.pow_header();
    let mut nonce = 0u64;
    let solution = loop {
        let s = solve(&pow_header, nonce, &TESTNET.profile, cache, seed_epoch,
                      &seed_block, None);
        if s.as_slice() <= expected.as_slice() {
            break s;
        }
        nonce += 1;
    };
    block.header.nonce = nonce;
    block.header.solution = hex::encode(solution);
    block
}

#[test]
fn window_boundary_template_matches_validator() {
    let seed_epoch = epoch_seed(0, &[0x11u8; 32]);
    let cache = gen_cache(&seed_epoch, TEST_PROFILE.cache_words);
    let tip_solution = [0x22u8; 32];

    // height 10 = window boundary; window elapsed 400 s over 10 blocks =
    // 40 s per block — 3x too fast -> 1 level harder (tip_target >> 1)
    let tip_target = [0xffu8; 32];
    let window_start_ts = 90;
    let ts = window_start_ts + 400; // 1090; mtp=100 < ts; node_now = 1100
    let block = window_block(10, tip_target, window_start_ts, ts, 100, 1100,
                             &tip_solution, &cache, &seed_epoch);
    // template computed 1 level harder: top byte 0x7f
    assert_eq!(&block.header.target[..2], "7f", "1 level = >>1 bit");

    let tip = TipContext {
        height: 10,
        prev_hash: &hex::encode([0x11u8; 32]),
        tip_solution: &tip_solution,
        tip_target,
        mtp: 100,
        node_now: 1100,
        window_start_ts,
        note_root: [0u8; 32],
    };
    let utxo = vice_core::tx::UtxoSet::new();
    let res = validate_block(&block, &TESTNET, &tip, &utxo,
                             &vice_core::notes::NoteMerkleTree::new(),
                             &std::collections::HashSet::new(),
                             &cache, &seed_epoch);
    assert!(res.is_ok(), "window-boundary block must validate: {res:?}");
}

#[test]
fn window_boundary_rejects_wrong_target() {
    let seed_epoch = epoch_seed(0, &[0x11u8; 32]);
    let cache = gen_cache(&seed_epoch, TEST_PROFILE.cache_words);
    let tip_solution = [0x22u8; 32];
    let mut block = window_block(10, [0xffu8; 32], 90, 490, 100, 1100,
                                 &tip_solution, &cache, &seed_epoch);
    // tamper the target: claim genesis max instead of the tightened one
    block.header.target = hex::encode([0xffu8; 32]);
    let tip = TipContext {
        height: 10,
        prev_hash: &hex::encode([0x11u8; 32]),
        tip_solution: &tip_solution,
        tip_target: [0xffu8; 32],
        mtp: 100,
        node_now: 1100,
        window_start_ts: 90,
        note_root: [0u8; 32],
    };
    let res = validate_block(&block, &TESTNET,
                             &tip, &vice_core::tx::UtxoSet::new(),
                             &vice_core::notes::NoteMerkleTree::new(),
                             &std::collections::HashSet::new(),
                             &cache, &seed_epoch);
    // the header-only continuity check fires BEFORE the expensive solve
    assert!(matches!(res, Err(vice_core::tx::ValidationError::TargetMismatch { .. })),
            "tampered target must be rejected by the continuity check");
}
