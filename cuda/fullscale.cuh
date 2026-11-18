// fullscale.cuh — FULL SCALE (v0.3 genesis): 4 GiB dataset, 128 MiB cache,
// 4096 lanes, 16 rounds. Included by octet.cu AFTER the BLAKE2b core.
// See docs/pow.md §3 and §10.1.
//
// Windows WDDM TDR note: every kernel launch here is chunked to stay well
// under the ~2 s display-driver timeout; the host loops over launches.
#ifndef OCTET_FULLSCALE_CUH
#define OCTET_FULLSCALE_CUH

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <string>
#include <filesystem>

#define F_CACHE_WORDS   (1u << 21)   // 128 MiB / 64 B
#define F_DATASET_ITEMS (1u << 24)   // 4 GiB / 256 B
#define F_ITEM_PARENTS  32u
#define F_LANES         4096u
#define F_LPB           1024u        // threads per block (lane-group)
#define F_ROUNDS        16u
#define OCT_SH_BYTES   (32u * 1024u)  // word-major shared: 8 words x 1024 lanes

// Cache chain chunk: computes cache[start .. start+count) from the previous
// word (or the tag, when start == 0). Serial by definition of the chain.
__global__ void k_cache_chunk(uint8_t* cache, const uint8_t* seed_epoch,
                              uint32_t start, uint32_t count) {
    if (threadIdx.x != 0 || blockIdx.x != 0) return;
    oct_blake2b s;
    uint8_t idx[8];
    if (start == 0) {
        ob_init(&s, 64);
        ob_update(&s, (const uint8_t*)"octet-cache", 11);
        ob_update(&s, seed_epoch, 64);
        ob_final(&s, cache);
        start = 1;
        if (count == 0) return;
        count -= 1;
    }
    for (uint32_t i = 0; i < count; i++) {
        uint32_t w = start + i;
        put_le64(idx, w);
        ob_init(&s, 64);
        ob_update(&s, cache + (uint64_t)(w - 1) * 64, 64);
        ob_update(&s, seed_epoch, 64);
        ob_update(&s, idx, 8);
        ob_final(&s, cache + (uint64_t)w * 64);
    }
}

// Dataset expansion chunk: items [begin, begin+count) — one thread per item;
// effective item = item_base (parent chain over cache) XOR keystream.
__global__ void k_dataset_chunk(uint8_t* dataset, const uint8_t* cache,
                                const uint8_t* seed_epoch,
                                const uint8_t* seed_block, uint32_t begin,
                                uint32_t count, uint32_t parents,
                                uint32_t cache_words) {
    uint32_t j = begin + blockIdx.x * blockDim.x + threadIdx.x;
    if (j >= begin + count) return;
    oct_blake2b s;
    uint8_t acc[64], tmp[8];

    ob_init(&s, 64);
    ob_update(&s, seed_epoch, 64);
    put_le64(tmp, j);
    ob_update(&s, tmp, 8);
    ob_final(&s, acc);

    for (uint32_t k = 0; k < parents; k++) {
        uint8_t pd[8];
        ob_init(&s, 8);
        ob_update(&s, seed_epoch, 64);
        put_le64(tmp, j);
        ob_update(&s, tmp, 8);
        put_le64(tmp, k);
        ob_update(&s, tmp, 8);
        ob_final(&s, pd);
        uint32_t p = (uint32_t)(get_be64(pd) % cache_words);
        ob_init(&s, 64);
        ob_update(&s, acc, 64);
        ob_update(&s, cache + (uint64_t)p * 64, 64);
        ob_final(&s, acc);
    }

    uint8_t item[256], ks[256];
    for (uint32_t c = 0; c < 4; c++) {
        put_le64(tmp, c);
        ob_init(&s, 64);
        ob_update(&s, acc, 64);
        ob_update(&s, tmp, 8);
        ob_final(&s, item + (uint64_t)c * 64);
        ob_init(&s, 64);
        ob_update(&s, seed_block, 64);
        put_le64(tmp, j);
        ob_update(&s, tmp, 8);
        put_le64(tmp, c);
        ob_update(&s, tmp, 8);
        ob_final(&s, ks + (uint64_t)c * 64);
    }
    uint8_t* dst = dataset + (uint64_t)j * 256;
    for (uint32_t i = 0; i < 256; i++) dst[i] = item[i] ^ ks[i];
}

// Search at full scale, v2: 256 threads/block, 4 lanes per thread — lane
// states live in REGISTERS (32 regs), the block covers all 1024 lanes of its
// lane-group. Butterfly (partner = lane ^ (1 << (r%10)), always inside the
// group) runs through a single word-major shared buffer (32 KB, no bank
// conflicts) in three phases: write updated -> read own+partner -> write XOR.
// No __syncthreads-reachable global state traffic per round.
__global__ void __launch_bounds__(256, 2)
k_search_full(const uint8_t* dataset, const uint8_t* header,
              uint32_t header_len, uint64_t nonce_base, uint32_t concurrent,
              uint32_t att_begin, uint32_t att_end, uint8_t* states_buf) {
    extern __shared__ uint32_t sh[];      // word-major: sh[k*1024 + lane]
    uint32_t g    = blockIdx.x & 3u;
    uint32_t slot = blockIdx.x >> 2;
    uint32_t t    = threadIdx.x;          // 0..255
    oct_blake2b s;
    uint8_t seed[32], tmp[8];
    uint32_t rst[4][8];                   // register states of the 4 lanes

    for (uint64_t att = att_begin + slot; att < att_end; att += concurrent) {
        uint64_t nonce = nonce_base + att;
        ob_init(&s, 32);
        ob_update(&s, (const uint8_t*)"octet-pow", 9);
        ob_update(&s, header, header_len);
        put_le64(tmp, nonce);
        ob_update(&s, tmp, 8);
        ob_final(&s, seed);

        // init: 4 lane states into registers and shared
        for (uint32_t j = 0; j < 4; j++) {
            uint32_t lane = (g << 10) + t * 4u + j;
            uint8_t sb[32];
            ob_init(&s, 32);
            ob_update(&s, (const uint8_t*)"lane", 4);
            ob_update(&s, seed, 32);
            put_le64(tmp, lane);
            ob_update(&s, tmp, 8);
            ob_final(&s, sb);
#pragma unroll
            for (uint32_t k = 0; k < 8; k++) {
                rst[j][k] = (uint32_t)sb[4*k] | ((uint32_t)sb[4*k+1] << 8) |
                            ((uint32_t)sb[4*k+2] << 16) |
                            ((uint32_t)sb[4*k+3] << 24);
                sh[k * 1024u + t * 4u + j] = rst[j][k];
            }
        }
        if (states_buf)   // [init] snapshot, coalesced (128 B per thread)
            for (uint32_t j = 0; j < 4; j++) {
                uint8_t rec[32];
#pragma unroll
                for (uint32_t k = 0; k < 8; k++) {
                    rec[4*k]   = (uint8_t)(rst[j][k] & 0xffu);
                    rec[4*k+1] = (uint8_t)((rst[j][k] >> 8) & 0xffu);
                    rec[4*k+2] = (uint8_t)((rst[j][k] >> 16) & 0xffu);
                    rec[4*k+3] = (uint8_t)((rst[j][k] >> 24) & 0xffu);
                }
                uint64_t lane = (uint64_t)(g << 10) + t * 4u + j;
                memcpy(states_buf + lane * 32, rec, 32);
            }
        __syncthreads();

        for (uint32_t r = 0; r < F_ROUNDS; r++) {
            // per-lane: H32(state || item[addr]) — item streamed from global
            uint32_t nw[4][8];
            for (uint32_t j = 0; j < 4; j++) {
                uint32_t be = ((rst[j][0] & 0xffu) << 24) |
                              ((rst[j][0] & 0xff00u) << 8) |
                              ((rst[j][0] & 0xff0000u) >> 8) |
                              ((rst[j][0] >> 24) & 0xffu);
                uint32_t addr = be % F_DATASET_ITEMS;
                uint8_t sb2[32];
#pragma unroll
                for (uint32_t k = 0; k < 8; k++) {
                    sb2[4*k]   = (uint8_t)(rst[j][k] & 0xffu);
                    sb2[4*k+1] = (uint8_t)((rst[j][k] >> 8) & 0xffu);
                    sb2[4*k+2] = (uint8_t)((rst[j][k] >> 16) & 0xffu);
                    sb2[4*k+3] = (uint8_t)((rst[j][k] >> 24) & 0xffu);
                }
                ob_init(&s, 32);
                ob_update(&s, sb2, 32);
                ob_update(&s, dataset + (uint64_t)addr * 256, 256);
                ob_final(&s, sb2);
#pragma unroll
                for (uint32_t k = 0; k < 8; k++)
                    nw[j][k] = (uint32_t)sb2[4*k] | ((uint32_t)sb2[4*k+1] << 8) |
                               ((uint32_t)sb2[4*k+2] << 16) |
                               ((uint32_t)sb2[4*k+3] << 24);
            }

            // butterfly phase 1: publish updated states (word-major)
            uint32_t b = r % 10u;
            for (uint32_t j = 0; j < 4; j++)
#pragma unroll
                for (uint32_t k = 0; k < 8; k++)
                    sh[k * 1024u + t * 4u + j] = nw[j][k];
            __syncthreads();

            // butterfly phase 2: read own + partner, XOR into registers
            for (uint32_t j = 0; j < 4; j++) {
                uint32_t lane = t * 4u + j;
                uint32_t partner = lane ^ (1u << b);
#pragma unroll
                for (uint32_t k = 0; k < 8; k++)
                    rst[j][k] = nw[j][k] ^ sh[k * 1024u + partner];
            }
            __syncthreads();

            // butterfly phase 3: publish the XOR result (overwrite is safe now)
            for (uint32_t j = 0; j < 4; j++)
#pragma unroll
                for (uint32_t k = 0; k < 8; k++)
                    sh[k * 1024u + t * 4u + j] = rst[j][k];
            __syncthreads();
        }

        // final states of the attempt: registers -> global (coalesced)
        for (uint32_t j = 0; j < 4; j++) {
            uint8_t rec[32];
#pragma unroll
            for (uint32_t k = 0; k < 8; k++) {
                rec[4*k]   = (uint8_t)(rst[j][k] & 0xffu);
                rec[4*k+1] = (uint8_t)((rst[j][k] >> 8) & 0xffu);
                rec[4*k+2] = (uint8_t)((rst[j][k] >> 16) & 0xffu);
                rec[4*k+3] = (uint8_t)((rst[j][k] >> 24) & 0xffu);
            }
            uint64_t lane = (uint64_t)(g << 10) + t * 4u + j;
            memcpy(states_buf + lane * 32, rec, 32);
        }
        __syncthreads();
    }
}

// Final hash of one attempt slot: H32(concat(states)) — serial 128 KB.
__global__ void k_final_full(const uint8_t* states_buf, uint32_t slot,
                             uint8_t* final_out) {
    if (threadIdx.x != 0 || blockIdx.x != 0) return;
    oct_blake2b fs;
    ob_init(&fs, 32);
    ob_update(&fs, states_buf + (uint64_t)slot * F_LANES * 32, F_LANES * 32);
    ob_final(&fs, final_out);
}

// ---------------------------------------------------------------------------
// host: FULL SCALE mode — expand (timed), sample dump, search benchmark,
// end-to-end dump for Python light-path verification. All launches are
// chunked under the WDDM TDR timeout.
// ---------------------------------------------------------------------------
static int run_full(const std::string& outdir) {
    int ndev = 0;
    if (cudaGetDeviceCount(&ndev) != cudaSuccess || ndev == 0) {
        printf("no CUDA device\n");
        return 2;
    }
    std::filesystem::create_directories(outdir);
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, 0);
    printf("full scale on: %s, %d MB VRAM, %d SMs\n", prop.name,
           (int)(prop.totalGlobalMem >> 20), prop.multiProcessorCount);
    fflush(stdout);

    // seeds — same formulas as reference (epoch 0, synthetic epoch seed)
    uint8_t esh[32], psh[32], tmp[8];
    for (int i = 0; i < 32; i++) esh[i] = 0x11, psh[i] = 0x22;
    oct_blake2b s;
    uint8_t seed_epoch[64], seed_block[64];
    ob_init(&s, 64);
    ob_update(&s, (const uint8_t*)"octet-epoch", 11);
    put_le64(tmp, 0);
    ob_update(&s, tmp, 8);
    ob_update(&s, esh, 32);
    ob_final(&s, seed_epoch);
    ob_init(&s, 64);
    ob_update(&s, (const uint8_t*)"octet-block", 11);
    ob_update(&s, psh, 32);
    put_le64(tmp, 1);
    ob_update(&s, tmp, 8);
    ob_final(&s, seed_block);
    const uint8_t* header = (const uint8_t*)"h0";
    uint32_t header_len = 2;
    uint64_t nonce_base = 777;

    uint8_t *d_cache = nullptr, *d_dataset = nullptr, *d_seed_epoch = nullptr,
            *d_seed_block = nullptr, *d_header = nullptr;
    if (cudaMalloc(&d_cache, (size_t)F_CACHE_WORDS * 64) != cudaSuccess ||
        cudaMalloc(&d_dataset, (size_t)F_DATASET_ITEMS * 256) != cudaSuccess ||
        cudaMalloc(&d_seed_epoch, 64) != cudaSuccess ||
        cudaMalloc(&d_seed_block, 64) != cudaSuccess ||
        cudaMalloc(&d_header, header_len) != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed (full)\n");
        return 2;
    }
    cudaMemcpy(d_seed_epoch, seed_epoch, 64, cudaMemcpyHostToDevice);
    cudaMemcpy(d_seed_block, seed_block, 64, cudaMemcpyHostToDevice);
    cudaMemcpy(d_header, header, header_len, cudaMemcpyHostToDevice);

    cudaEvent_t ev0, ev1;
    cudaEventCreate(&ev0); cudaEventCreate(&ev1);
    float ms = 0;

    // 1. cache fill — serial chain, chunked launches under TDR
    const uint32_t CACHE_CHUNK = 1024;
    cudaEventRecord(ev0);
    for (uint32_t begin = 0; begin < F_CACHE_WORDS; begin += CACHE_CHUNK) {
        uint32_t cnt = (F_CACHE_WORDS - begin < CACHE_CHUNK)
                           ? F_CACHE_WORDS - begin : CACHE_CHUNK;
        k_cache_chunk<<<1, 1>>>(d_cache, d_seed_epoch, begin, cnt);
        cudaDeviceSynchronize();
    }
    cudaEventRecord(ev1);
    cudaDeviceSynchronize();
    cudaEventElapsedTime(&ms, ev0, ev1);
    printf("cache fill: %.2f s (%u words, chunked)\n", ms / 1000.0,
           F_CACHE_WORDS);
    fflush(stdout);

    // 2. dataset expansion (timed) — the per-block re-key cost
    const uint32_t DS_CHUNK = 1u << 20;   // 1M items per launch (~0.5 s)
    cudaEventRecord(ev0);
    for (uint32_t begin = 0; begin < F_DATASET_ITEMS; begin += DS_CHUNK) {
        uint32_t cnt = (F_DATASET_ITEMS - begin < DS_CHUNK)
                           ? F_DATASET_ITEMS - begin : DS_CHUNK;
        k_dataset_chunk<<<(cnt + 255) / 256, 256>>>(
            d_dataset, d_cache, d_seed_epoch, d_seed_block, begin, cnt,
            F_ITEM_PARENTS, F_CACHE_WORDS);
        cudaDeviceSynchronize();
    }
    cudaEventRecord(ev1);
    cudaDeviceSynchronize();
    cudaEventElapsedTime(&ms, ev0, ev1);
    double exp_s = ms / 1000.0;
    printf("dataset expand: %.2f s  (%.1f GB/s of writes, %.1f%% of the 120 s block)\n",
           exp_s, (double)F_DATASET_ITEMS * 256 / exp_s / 1e9,
           exp_s / 120.0 * 100.0);
    fflush(stdout);

    // 3. sample dump for the Python bit-exact cross-check
    uint32_t sample_js[34];
    for (uint32_t i = 0; i < 32; i++) sample_js[i] = i;
    sample_js[32] = 1u << 20; sample_js[33] = F_DATASET_ITEMS - 1;
    FILE* f = fopen((outdir + "/samples.bin").c_str(), "wb");
    for (uint32_t i = 0; i < 34; i++) {
        fwrite(&sample_js[i], 4, 1, f);
        std::vector<uint8_t> item(256);
        cudaMemcpy(item.data(), d_dataset + (uint64_t)sample_js[i] * 256, 256,
                   cudaMemcpyDeviceToHost);
        fwrite(item.data(), 1, 256, f);
    }
    fclose(f);

    // 4. search benchmark: concurrent attempts, timed, chunked under TDR
    const uint32_t CONC = 34;
    cudaFuncSetAttribute(k_search_full,
                         cudaFuncAttributeMaxDynamicSharedMemorySize,
                         OCT_SH_BYTES);
    uint8_t* d_states = nullptr;
    if (cudaMalloc(&d_states, (size_t)CONC * F_LANES * 32) != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed (states)\n");
        return 2;
    }
    const uint64_t bench_attempts = 8192;
    const uint32_t BENCH_CHUNK = 1000;    // ~0.5 s per launch
    cudaGetLastError();                    // clear sticky state
    cudaEventRecord(ev0);
    for (uint32_t begin = 0; (uint64_t)begin < bench_attempts;
         begin += BENCH_CHUNK) {
        uint32_t end = (bench_attempts - begin < BENCH_CHUNK)
                           ? (uint32_t)bench_attempts : begin + BENCH_CHUNK;
        k_search_full<<<CONC * 4, 256, OCT_SH_BYTES>>>(
            d_dataset, d_header, header_len, nonce_base, CONC, begin,
            end, d_states);
        cudaError_t le = cudaGetLastError();
        if (le != cudaSuccess) {
            fprintf(stderr, "bench launch %u failed: %s\n", begin,
                    cudaGetErrorString(le));
            return 1;
        }
        cudaError_t se = cudaDeviceSynchronize();
        if (se != cudaSuccess) {
            fprintf(stderr, "bench sync at %u failed: %s\n", begin,
                    cudaGetErrorString(se));
            return 1;
        }
    }
    cudaEventRecord(ev1);
    cudaDeviceSynchronize();
    cudaEventElapsedTime(&ms, ev0, ev1);
    std::vector<uint8_t> probe(32);
    cudaMemcpy(probe.data(), d_states, 32, cudaMemcpyDeviceToHost);
    printf("states[0] first bytes: %02x %02x %02x %02x\n", probe[0],
           probe[1], probe[2], probe[3]);
    double bs = ms / 1000.0;
    double aps = bench_attempts / bs;
    printf("search bench: %llu attempts in %.2f s  =>  %.0f attempts/s  "
           "(~%.1f Sol/s at ~2 solutions/attempt)\n",
           (unsigned long long)bench_attempts, bs, aps, aps * 2.0);
    printf("effective read bandwidth: %.0f GB/s\n",
           aps * (double)F_LANES * F_ROUNDS * 256 / 1e9);
    fflush(stdout);

    // 5. end-to-end dump: one nonce, states + final, for Python verify
    uint64_t e2e_nonce = 777;
    k_search_full<<<CONC * 4, 256, OCT_SH_BYTES>>>(d_dataset, d_header,
        header_len, e2e_nonce, CONC, 0, 1, d_states);
    cudaDeviceSynchronize();
    uint8_t* d_final = nullptr;
    cudaMalloc(&d_final, 32);
    k_final_full<<<1, 1>>>(d_states, 0, d_final);
    cudaDeviceSynchronize();
    std::vector<uint8_t> final_got(32);
    cudaMemcpy(final_got.data(), d_final, 32, cudaMemcpyDeviceToHost);
    f = fopen((outdir + "/full_final.bin").c_str(), "wb");
    fwrite(final_got.data(), 1, 32, f);
    fclose(f);
    {
        FILE* m = fopen((outdir + "/meta_full.json").c_str(), "w");
        fprintf(m, "{\"header_hex\": \"%02x%02x\", \"nonce\": %llu, "
                   "\"dataset_items\": %u, \"cache_words\": %u, "
                   "\"final_hex\": \"",
                header[0], header[1], (unsigned long long)e2e_nonce,
                F_DATASET_ITEMS, F_CACHE_WORDS);
        for (int i = 0; i < 32; i++) fprintf(m, "%02x", final_got[i]);
        fprintf(m, "\"}\n");
        fclose(m);
    }
    printf("end-to-end dump written: full_final.bin / meta_full.json "
           "(verify with tests/verify_fullscale.py)\n");
    fflush(stdout);

    cudaFree(d_states);
    cudaFree(d_final);
    cudaFree(d_header);
    cudaFree(d_seed_block);
    cudaFree(d_seed_epoch);
    cudaFree(d_dataset);
    cudaFree(d_cache);
    return 0;
}

#endif  // OCTET_FULLSCALE_CUH
