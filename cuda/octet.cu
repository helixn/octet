// octet.cu — CUDA solver skeleton for OctetHash v0.1 (DRAFT).
//
// Status: compile-checked skeleton. The kernels are stubs; the real Wagner-
// style memory pipeline (cache fill, dataset expansion, keystream re-key,
// 4096-lane search) lands in Phase 1. See docs/pow.md for the spec.
//
// Build:  make -C cuda          (sm_70 + sm_86; add your arch via ARCH=)

#include <cuda_runtime.h>
#include <cstdio>
#include <cstdint>
#include <cstring>

// ---------------------------------------------------------------------------
// full-scale parameters (docs/pow.md §3) — the reference uses reduced ones
// ---------------------------------------------------------------------------
#define CACHE_WORDS    (1u << 22)   // 256 MiB / 64 B
#define DATASET_ITEMS  (1u << 25)   // 8 GiB / 256 B
#define ITEM_BYTES     256
#define ITEM_PARENTS   32
#define LANES          4096
#define LANES_PER_BLOCK 1024
#define ROUNDS         16

// ---------------------------------------------------------------------------
// BLAKE2b device core — TODO Phase 1: full RFC 7693 implementation with the
// same domain-separation tags as reference/octet_ref.py ("octet-cache",
// "octet-epoch", "octet-block", "octet-pow", "lane").
// ---------------------------------------------------------------------------
__device__ __forceinline__ void octet_blake2b_64(uint64_t* out, const void* in,
                                                size_t len) {
    // TODO Phase 1
    (void)out; (void)in; (void)len;
}

// ---------------------------------------------------------------------------
// kernels (stubs)
// ---------------------------------------------------------------------------

// Sequential cache fill: cache[i] depends on cache[i-1] — on GPU this is a
// multi-round pairwise mixing schedule (log2 rounds), not a serial loop.
__global__ void k_cache_fill(uint64_t* cache, const uint8_t* seed_epoch,
                             uint32_t words) {
    // TODO Phase 1
    (void)cache; (void)seed_epoch; (void)words;
}

// Dataset item expansion: 256 B item from ITEM_PARENTS cache words.
__global__ void k_dataset_expand(uint8_t* dataset, const uint64_t* cache,
                                 const uint8_t* seed_epoch,
                                 uint32_t items) {
    // TODO Phase 1
    (void)dataset; (void)cache; (void)seed_epoch; (void)items;
}

// Per-block re-key: dataset ^= keystream(seed_block). One full 8 GiB write
// sweep per block — the anti-precomputation core of the design.
__global__ void k_rekey(uint8_t* dataset, const uint8_t* seed_block,
                        uint32_t items) {
    // TODO Phase 1
    (void)dataset; (void)seed_block; (void)items;
}

// Search: LANES_PER_BLOCK threads per block, states in shared memory,
// butterfly exchange via __syncthreads, random 256 B reads from dataset.
__global__ void k_search(const uint8_t* dataset, const uint8_t* header,
                         uint64_t nonce, uint32_t* out_result) {
    // TODO Phase 1
    (void)dataset; (void)header; (void)nonce; (void)out_result;
}

// ---------------------------------------------------------------------------
// minimal host API so the skeleton links and CI can compile it
// ---------------------------------------------------------------------------

extern "C" {

int octet_device_count(void) {
    int n = 0;
    if (cudaGetDeviceCount(&n) != cudaSuccess) return 0;
    return n;
}

const char* octet_status(void) {
    return "OctetHash CUDA solver skeleton v0.1 — kernels are stubs (Phase 1)";
}

int octet_selftest(void) {
    int dev = 0;
    cudaDeviceProp prop;
    if (cudaGetDeviceCount(&dev) != cudaSuccess || dev == 0) {
        printf("no CUDA device — compile-only selftest\n");
        return 0;  // not an error in CI
    }
    cudaGetDeviceProperties(&prop, 0);
    printf("device 0: %s, sm_%d%d, %d MB, %d SMs\n",
           prop.name, prop.major, prop.minor,
           (int)(prop.totalGlobalMem >> 20), prop.multiProcessorCount);
    printf("kernels: STUBS — real pipeline lands in Phase 1\n");
    return 0;
}

}  // extern "C"
