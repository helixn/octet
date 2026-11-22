//! Bit-exact acceptance against the committed vector snapshot taken from the
//! Python oracle (tests/vectors/, cuda-kernel-dev phase 2). If these tests
//! fail, the Rust consensus core is wrong — never "fix" the vectors.
use vice_core::{block_seed, epoch_seed, gen_cache, solve, TEST_PROFILE};

fn repo_root() -> std::path::PathBuf {
    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("repo root")
        .to_path_buf()
}

fn read_bin(rel: &str) -> Vec<u8> {
    std::fs::read(repo_root().join(rel)).expect(rel)
}

/// Reference seeds used by export_vectors(): epoch_seed(0, 0x11*32) and
/// block_seed(0x22*32, height=1).
fn oracle_seeds() -> (Vec<u8>, Vec<u8>) {
    let esh = [0x11u8; 32];
    let seed_epoch = epoch_seed(0, &esh);
    let seed_block = block_seed(&[0x22u8; 32], 1);
    (seed_epoch, seed_block)
}

#[test]
fn cache_matches_oracle_snapshot() {
    let (seed_epoch, _) = oracle_seeds();
    let cache = gen_cache(&seed_epoch, TEST_PROFILE.cache_words);
    let want = read_bin("tests/vectors/cache.bin");
    let mut got = Vec::with_capacity(want.len());
    for word in &cache {
        got.extend_from_slice(word);
    }
    assert_eq!(got.len(), want.len());
    assert_eq!(got, want, "cache diverged from the committed snapshot");
}

#[test]
fn final_hash_matches_oracle_snapshot() {
    let (seed_epoch, seed_block) = oracle_seeds();
    let cache = gen_cache(&seed_epoch, TEST_PROFILE.cache_words);
    let header = read_bin("tests/vectors/header.bin"); // b"h0"
    let nonce_bytes = read_bin("tests/vectors/nonce.bin"); // le64(7)
    let nonce = u64::from_le_bytes(nonce_bytes.try_into().unwrap());
    let final_hash = solve(&header, nonce, &TEST_PROFILE, &cache,
                           &seed_epoch, &seed_block, None);
    assert_eq!(final_hash, read_bin("tests/vectors/final.bin"),
               "final hash diverged from the committed snapshot");
}

#[test]
fn per_round_states_match_oracle_snapshot() {
    let (seed_epoch, seed_block) = oracle_seeds();
    let cache = gen_cache(&seed_epoch, TEST_PROFILE.cache_words);
    let header = read_bin("tests/vectors/header.bin");
    let nonce = u64::from_le_bytes(
        read_bin("tests/vectors/nonce.bin").try_into().unwrap());
    let mut log = Vec::new();
    let _ = solve(&header, nonce, &TEST_PROFILE, &cache,
                  &seed_epoch, &seed_block, Some(&mut log));
    let want = read_bin("tests/vectors/states.bin");
    let mut got = Vec::new();
    for snap in &log {
        got.extend_from_slice(snap);
    }
    assert_eq!(got.len(), want.len());
    assert_eq!(got, want, "per-round states diverged from the snapshot");
}

#[test]
fn verify_gate_accepts_and_rejects_target() {
    let (seed_epoch, seed_block) = oracle_seeds();
    let cache = gen_cache(&seed_epoch, TEST_PROFILE.cache_words);
    let header = b"h0";
    // final from the snapshot, as big-endian integer — target slightly above
    let fin = read_bin("tests/vectors/final.bin");
    let mut loose = fin.clone();
    loose[0] = loose[0].saturating_add(1); // +1 to the MSB (BE layout)
    assert!(vice_core::verify(header, 7, &loose, &TEST_PROFILE, &cache,
                              &seed_epoch, &seed_block));
    let mut tight = fin.clone();
    tight[0] = 0; // definitely below the final hash unless final == 0
    if fin[0] > 0 {
        assert!(!vice_core::verify(header, 7, &tight, &TEST_PROFILE, &cache,
                                   &seed_epoch, &seed_block));
    }
}
