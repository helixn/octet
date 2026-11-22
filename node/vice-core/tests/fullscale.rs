//! Full-scale end-to-end: recompute the genesis-parameter attempt (4 GiB
//! dataset parameters, light path from the 128 MiB cache) and compare with
//! the GPU dump the Python oracle already verified
//! (tests/fullscale/full_final.bin). ~10 s in release mode.
use vice_core::{block_seed, epoch_seed, gen_cache, solve, FULL_SCALE};

#[test]
fn fullscale_final_matches_gpu_dump() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(2)
        .expect("repo root")
        .to_path_buf();
    let gpu_final = std::fs::read(root.join("tests/fullscale/full_final.bin"))
        .expect("tests/fullscale/full_final.bin");

    let seed_epoch = epoch_seed(0, &[0x11u8; 32]);
    let seed_block = block_seed(&[0x22u8; 32], 1);
    let cache = gen_cache(&seed_epoch, FULL_SCALE.cache_words);
    let final_hash = solve(b"h0", 777, &FULL_SCALE, &cache,
                           &seed_epoch, &seed_block, None);
    assert_eq!(final_hash, gpu_final,
               "Rust light path diverges from the GPU full-scale pipeline");
}
