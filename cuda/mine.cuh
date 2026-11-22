// mine.cuh — testnet GPU mining mode: search nonces for a minejob.
// Usage: octet_test.exe mine <pow_header_hex> <seed_block_hex>
//                            <target_hex> <start_nonce> <count>
// Prints "FOUND <nonce> <solution_hex>" on success, "NONE" otherwise.
// Testnet convention: epoch 0, epoch seed hash = 0x11*32 (matches vicd).
#ifndef OCTET_MINE_CUH
#define OCTET_MINE_CUH

#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include <chrono>
#include <cstdlib>

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static std::vector<uint8_t> hex_bytes(const std::string& s) {
    std::vector<uint8_t> out;
    out.reserve(s.size() / 2);
    for (size_t i = 0; i + 1 < s.size(); i += 2) {
        int hi = hex_nibble(s[i]), lo = hex_nibble(s[i + 1]);
        if (hi < 0 || lo < 0) return {};
        out.push_back(uint8_t(hi * 16 + lo));
    }
    return out;
}

static int run_mine(const std::string& pow_header_hex,
                    const std::string& seed_block_hex,
                    const std::string& target_hex, uint64_t start_nonce,
                    uint64_t count) {
    auto header = hex_bytes(pow_header_hex);
    auto seed_block = hex_bytes(seed_block_hex);
    auto target = hex_bytes(target_hex);
    if (header.size() != 32 || seed_block.size() != 64 || target.size() != 32) {
        fprintf(stderr, "bad hex args\n");
        return 2;
    }
    int ndev = 0;
    if (cudaGetDeviceCount(&ndev) != cudaSuccess || ndev == 0) {
        fprintf(stderr, "no CUDA device\n");
        return 2;
    }

    // testnet epoch 0 cache + dataset (per-job re-key via seed_block)
    uint8_t esh[32];
    for (int i = 0; i < 32; i++) esh[i] = 0x11;
    oct_blake2b hs;
    uint8_t seed_epoch[64];
    ob_init(&hs, 64);
    ob_update(&hs, (const uint8_t*)"octet-epoch", 11);
    uint8_t zero8[8] = {0, 0, 0, 0, 0, 0, 0, 0};
    ob_update(&hs, zero8, 8);
    ob_update(&hs, esh, 32);
    ob_final(&hs, seed_epoch);

    uint8_t *d_cache = nullptr, *d_dataset = nullptr, *d_seed_epoch = nullptr,
            *d_seed_block = nullptr, *d_header = nullptr, *d_final = nullptr;
    if (cudaMalloc(&d_cache, CACHE_WORDS * 64) != cudaSuccess ||
        cudaMalloc(&d_dataset, DATASET_ITEMS * 256) != cudaSuccess ||
        cudaMalloc(&d_seed_epoch, 64) != cudaSuccess ||
        cudaMalloc(&d_seed_block, 64) != cudaSuccess ||
        cudaMalloc(&d_header, header.size()) != cudaSuccess ||
        cudaMalloc(&d_final, 32) != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed\n");
        return 2;
    }
    cudaMemcpy(d_seed_epoch, seed_epoch, 64, cudaMemcpyHostToDevice);
    cudaMemcpy(d_seed_block, seed_block.data(), 64, cudaMemcpyHostToDevice);
    cudaMemcpy(d_header, header.data(), header.size(), cudaMemcpyHostToDevice);

    k_cache_fill<<<1, 1>>>(d_cache, d_seed_epoch, CACHE_WORDS);
    cudaDeviceSynchronize();
    k_dataset_expand<<<(DATASET_ITEMS + 255) / 256, 256>>>(
        d_dataset, d_cache, d_seed_epoch, d_seed_block, DATASET_ITEMS,
        ITEM_PARENTS);
    if (cudaDeviceSynchronize() != cudaSuccess) {
        fprintf(stderr, "expand failed: %s\n",
                cudaGetErrorString(cudaGetLastError()));
        return 1;
    }

    uint8_t final_host[32];
    bool found = false;
    uint64_t found_nonce = 0;
    auto t0 = std::chrono::steady_clock::now();
    for (uint64_t n = start_nonce; n < start_nonce + count && !found; n++) {
        k_search<<<1, LANES>>>(d_dataset, d_header,
                               (uint32_t)header.size(), n, nullptr, d_final);
        if (cudaDeviceSynchronize() != cudaSuccess) {
            fprintf(stderr, "search failed: %s\n",
                    cudaGetErrorString(cudaGetLastError()));
            return 1;
        }
        cudaMemcpy(final_host, d_final, 32, cudaMemcpyDeviceToHost);
        bool ok = true;
        for (int i = 0; i < 32; i++) {
            if (final_host[i] != target[i]) {
                ok = (final_host[i] < target[i]);  // big-endian compare
                break;
            }
        }
        if (ok) {
            found = true;
            found_nonce = n;
        }
        if ((n - start_nonce) % 4096 == 4095) {
            double secs = std::chrono::duration<double>(
                              std::chrono::steady_clock::now() - t0).count();
            fprintf(stderr, "  %llu attempts, %.0f att/s\n",
                    (unsigned long long)(n - start_nonce + 1),
                    (n - start_nonce + 1) / (secs > 0 ? secs : 1e-9));
        }
    }

    if (found) {
        printf("FOUND %llu ", (unsigned long long)found_nonce);
        for (int i = 0; i < 32; i++) printf("%02x", final_host[i]);
        printf("\n");
    } else {
        printf("NONE\n");
    }
    cudaFree(d_final);
    cudaFree(d_header);
    cudaFree(d_seed_block);
    cudaFree(d_seed_epoch);
    cudaFree(d_dataset);
    cudaFree(d_cache);
    return found ? 0 : 1;
}

#endif  // OCTET_MINE_CUH
