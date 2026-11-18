// octet.cu — CUDA solver for OctetHash v0.1 (DRAFT), test profile.
//
// Stage A (this file): device BLAKE2b core + cache-fill kernel + host
// vector cross-check against tests/vectors/ (the protective snapshot taken
// from reference/octet_ref.py). Bit-exact or BLOCKED — see cuda-kernel-dev.
//
// Later stages (same file, following commits): dataset expand, search.
//
// Build:  make -C cuda            (octet_test binary, needs GPU to run checks)
//         make -C cuda compile-only

#include <cuda_runtime.h>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <string>

// ---------------------------------------------------------------------------
// test profile (matches reference TEST_PROFILE and tests/vectors/meta.json)
// ---------------------------------------------------------------------------
#define CACHE_WORDS    2048u
#define DATASET_ITEMS  4096u
#define ITEM_PARENTS   8u
#define LANES          256u
#define LANES_PER_BLOCK 256u
#define ROUNDS         8u

// ---------------------------------------------------------------------------
// device BLAKE2b (RFC 7693), streaming, no key. Little-endian digests —
// identical semantics to Python hashlib.blake2b(digest_size=N).
// ---------------------------------------------------------------------------
__device__ __constant__ uint64_t B2B_IV[8] = {
    0x6a09e667f3bcc908ull, 0xbb67ae8584caa73bull, 0x3c6ef372fe94f82bull,
    0xa54ff53a5f1d36f1ull, 0x510e527fade682d1ull, 0x9b05688c2b3e6c1full,
    0x1f83d9abfb41bd6bull, 0x5be0cd19137e2179ull
};

__device__ __constant__ uint8_t B2B_SIGMA[12][16] = {
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
    {14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3},
    {11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4},
    {7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8},
    {9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13},
    {2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9},
    {12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11},
    {13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10},
    {6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5},
    {10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0},
    {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
    {14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3}
};

__device__ __forceinline__ uint64_t rotr64(uint64_t x, int n) {
    return (x >> n) | (x << (64 - n));
}

__device__ void b2b_compress(uint64_t h[8], const uint8_t* block, uint64_t t,
                             int last) {
    uint64_t m[16], v[16];
#pragma unroll
    for (int i = 0; i < 16; i++)
        m[i] = (uint64_t)block[8*i] | ((uint64_t)block[8*i+1] << 8) |
               ((uint64_t)block[8*i+2] << 16) | ((uint64_t)block[8*i+3] << 24) |
               ((uint64_t)block[8*i+4] << 32) | ((uint64_t)block[8*i+5] << 40) |
               ((uint64_t)block[8*i+6] << 48) | ((uint64_t)block[8*i+7] << 56);
#pragma unroll
    for (int i = 0; i < 8; i++) v[i] = h[i];
    v[8]  = B2B_IV[0]; v[9]  = B2B_IV[1]; v[10] = B2B_IV[2]; v[11] = B2B_IV[3];
    v[12] = B2B_IV[4] ^ t; v[13] = B2B_IV[5];
    v[14] = last ? ~B2B_IV[6] : B2B_IV[6]; v[15] = B2B_IV[7];

#define B2B_G(a, b, c, d, x, y) do {                       \
        a = a + b + (x); d = rotr64(d ^ a, 32);            \
        c = c + d;          b = rotr64(b ^ c, 24);         \
        a = a + b + (y); d = rotr64(d ^ a, 16);            \
        c = c + d;          b = rotr64(b ^ c, 63);         \
    } while (0)

    for (int r = 0; r < 12; r++) {
        const uint8_t* s = B2B_SIGMA[r];
        B2B_G(v[0],v[4],v[8], v[12], m[s[ 0]], m[s[ 1]]);
        B2B_G(v[1],v[5],v[9], v[13], m[s[ 2]], m[s[ 3]]);
        B2B_G(v[2],v[6],v[10],v[14], m[s[ 4]], m[s[ 5]]);
        B2B_G(v[3],v[7],v[11],v[15], m[s[ 6]], m[s[ 7]]);
        B2B_G(v[0],v[5],v[10],v[15], m[s[ 8]], m[s[ 9]]);
        B2B_G(v[1],v[6],v[11],v[12], m[s[10]], m[s[11]]);
        B2B_G(v[2],v[7],v[8], v[13], m[s[12]], m[s[13]]);
        B2B_G(v[3],v[4],v[9], v[14], m[s[14]], m[s[15]]);
    }
#undef B2B_G
#pragma unroll
    for (int i = 0; i < 8; i++) h[i] ^= v[i] ^ v[i + 8];
}

typedef struct {
    uint64_t h[8];
    uint64_t t;        // bytes compressed so far
    uint8_t  buf[128]; // buffered tail (the last block is never compressed early)
    uint32_t buflen;
    uint32_t outlen;
} oct_blake2b;

__device__ void ob_init(oct_blake2b* s, uint32_t outlen) {
#pragma unroll
    for (int i = 0; i < 8; i++) s->h[i] = B2B_IV[i];
    s->h[0] ^= 0x01010000u ^ outlen;   // no key, no salt
    s->t = 0;
    s->buflen = 0;
    s->outlen = outlen;
}

__device__ void ob_update(oct_blake2b* s, const uint8_t* in, uint32_t len) {
    if (len == 0) return;
    uint32_t fill = 128 - s->buflen;
    if (len > fill) {
        for (uint32_t i = 0; i < fill; i++) s->buf[s->buflen + i] = in[i];
        s->t += 128;
        b2b_compress(s->h, s->buf, s->t, 0);
        s->buflen = 0;
        in += fill; len -= fill;
        while (len > 128) {                 // keep the last block for final()
            s->t += 128;
            b2b_compress(s->h, in, s->t, 0);
            in += 128; len -= 128;
        }
    }
    for (uint32_t i = 0; i < len; i++) s->buf[s->buflen + i] = in[i];
    s->buflen += len;
}

__device__ void ob_final(oct_blake2b* s, uint8_t* out) {
    if (s->buflen > 0 || s->t > 0) {
        for (uint32_t i = s->buflen; i < 128; i++) s->buf[i] = 0;
        s->t += s->buflen;
        b2b_compress(s->h, s->buf, s->t, 1);
        s->buflen = 0;
    }
    // empty message: digest = parameter-block state (no compression)
    for (uint32_t i = 0; i < s->outlen; i++)
        out[i] = (uint8_t)(s->h[i >> 3] >> (8 * (i & 7)));
}

__device__ __forceinline__ void put_le64(uint8_t* out, uint64_t v) {
    for (int i = 0; i < 8; i++) out[i] = (uint8_t)(v >> (8 * i));
}

__device__ __forceinline__ uint64_t get_be64(const uint8_t* in) {
    uint64_t v = 0;
    for (int i = 0; i < 8; i++) v = (v << 8) | in[i];
    return v;
}

// ---------------------------------------------------------------------------
// kernels — stage A: cache fill (sequential chain; single thread suffices
// for the test profile; full-scale parallel schedule lands with the node)
// ---------------------------------------------------------------------------
__global__ void k_cache_fill(uint8_t* cache, const uint8_t* seed_epoch) {
    if (threadIdx.x != 0 || blockIdx.x != 0) return;
    oct_blake2b s;
    ob_init(&s, 64);
    ob_update(&s, (const uint8_t*)"octet-cache", 11);
    ob_update(&s, seed_epoch, 64);
    ob_final(&s, cache);
    for (uint32_t i = 1; i < CACHE_WORDS; i++) {
        uint8_t idx[8];
        put_le64(idx, i);
        ob_init(&s, 64);
        ob_update(&s, cache + (uint64_t)(i - 1) * 64, 64);
        ob_update(&s, seed_epoch, 64);
        ob_update(&s, idx, 8);
        ob_final(&s, cache + (uint64_t)i * 64);
    }
}

// ---------------------------------------------------------------------------
// stage B: dataset expansion — one thread per item; effective item =
// item_base (parent chain over cache) XOR keystream(seed_block). Matches
// reference dataset_item() + keystream_item() + effective_item().
// ---------------------------------------------------------------------------
__global__ void k_dataset_expand(uint8_t* dataset, const uint8_t* cache,
                                 const uint8_t* seed_epoch,
                                 const uint8_t* seed_block) {
    uint32_t j = blockIdx.x * blockDim.x + threadIdx.x;
    if (j >= DATASET_ITEMS) return;
    oct_blake2b s;
    uint8_t acc[64], tmp[8];

    ob_init(&s, 64);
    ob_update(&s, seed_epoch, 64);
    put_le64(tmp, j);
    ob_update(&s, tmp, 8);
    ob_final(&s, acc);

    for (uint32_t k = 0; k < ITEM_PARENTS; k++) {
        uint8_t pd[8];
        ob_init(&s, 8);
        ob_update(&s, seed_epoch, 64);
        put_le64(tmp, j);
        ob_update(&s, tmp, 8);
        put_le64(tmp, k);
        ob_update(&s, tmp, 8);
        ob_final(&s, pd);
        uint32_t p = (uint32_t)(get_be64(pd) % CACHE_WORDS);
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

// ---------------------------------------------------------------------------
// stage C: search — LANES threads in one block; states in shared memory;
// butterfly partner i ^ (1 << (r % stride_bits)) stays inside the block.
// Matches reference _solve(): init states, per-round reads (BE addr from the
// first 4 state bytes), H32(state ‖ item), butterfly XOR, final H32.
// ---------------------------------------------------------------------------
__global__ void k_search(const uint8_t* dataset, const uint8_t* header,
                         uint32_t header_len, uint64_t nonce,
                         uint8_t* states_out, uint8_t* final_out) {
    __shared__ uint32_t st[LANES][8];
    __shared__ uint32_t st2[LANES][8];
    __shared__ uint8_t seed[32];
    uint32_t i = threadIdx.x;
    oct_blake2b s;
    uint8_t sb[32], tmp[8];

    if (i == 0) {
        ob_init(&s, 32);
        ob_update(&s, (const uint8_t*)"octet-pow", 9);
        ob_update(&s, header, header_len);
        put_le64(tmp, nonce);
        ob_update(&s, tmp, 8);
        ob_final(&s, seed);
    }
    __syncthreads();

    ob_init(&s, 32);
    ob_update(&s, (const uint8_t*)"lane", 4);
    ob_update(&s, seed, 32);
    put_le64(tmp, i);
    ob_update(&s, tmp, 8);
    ob_final(&s, sb);
#pragma unroll
    for (uint32_t k = 0; k < 8; k++)
        st[i][k] = (uint32_t)sb[4*k] | ((uint32_t)sb[4*k+1] << 8) |
                   ((uint32_t)sb[4*k+2] << 16) | ((uint32_t)sb[4*k+3] << 24);
    if (states_out)
        memcpy(states_out + (uint64_t)i * 32, sb, 32);   // [init]
    __syncthreads();

    for (uint32_t r = 0; r < ROUNDS; r++) {
        // read phase: BE integer of the first 4 state bytes mod dataset size
        uint32_t w0 = st[i][0];
        uint32_t be = ((w0 & 0xffu) << 24) | ((w0 & 0xff00u) << 8) |
                      ((w0 & 0xff0000u) >> 8) | ((w0 >> 24) & 0xffu);
        uint32_t addr = be % DATASET_ITEMS;
        uint8_t item[256];
        for (uint32_t t2 = 0; t2 < 256; t2++)
            item[t2] = dataset[(uint64_t)addr * 256 + t2];
#pragma unroll
        for (uint32_t k = 0; k < 8; k++) {
            sb[4*k]   = (uint8_t)(st[i][k] & 0xffu);
            sb[4*k+1] = (uint8_t)((st[i][k] >> 8) & 0xffu);
            sb[4*k+2] = (uint8_t)((st[i][k] >> 16) & 0xffu);
            sb[4*k+3] = (uint8_t)((st[i][k] >> 24) & 0xffu);
        }
        ob_init(&s, 32);
        ob_update(&s, sb, 32);
        ob_update(&s, item, 256);
        ob_final(&s, sb);
#pragma unroll
        for (uint32_t k = 0; k < 8; k++)
            st2[i][k] = (uint32_t)sb[4*k] | ((uint32_t)sb[4*k+1] << 8) |
                        ((uint32_t)sb[4*k+2] << 16) | ((uint32_t)sb[4*k+3] << 24);
        __syncthreads();
        // butterfly (simultaneous: read snapshot st2, write st)
        uint32_t partner = i ^ (1u << (r % 8));
#pragma unroll
        for (uint32_t k = 0; k < 8; k++) st[i][k] = st2[i][k] ^ st2[partner][k];
        __syncthreads();
        if (states_out) {
            uint8_t rec[32];
#pragma unroll
            for (uint32_t k = 0; k < 8; k++) {
                rec[4*k]   = (uint8_t)(st[i][k] & 0xffu);
                rec[4*k+1] = (uint8_t)((st[i][k] >> 8) & 0xffu);
                rec[4*k+2] = (uint8_t)((st[i][k] >> 16) & 0xffu);
                rec[4*k+3] = (uint8_t)((st[i][k] >> 24) & 0xffu);
            }
            memcpy(states_out + (uint64_t)(r + 1) * LANES * 32
                       + (uint64_t)i * 32, rec, 32);
        }
    }

    if (i == 0) {
        // final = H32(concat(states)); shared uint32 LE words == raw bytes
        oct_blake2b fs;
        ob_init(&fs, 32);
        ob_update(&fs, (const uint8_t*)st, LANES * 32);
        ob_final(&fs, final_out);
    }
}

// ---------------------------------------------------------------------------
// host: vector cross-check
// ---------------------------------------------------------------------------
static std::vector<uint8_t> read_bin(const std::string& path) {
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path.c_str()); exit(2); }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    std::vector<uint8_t> v((size_t)n);
    if (n && fread(v.data(), 1, (size_t)n, f) != (size_t)n) exit(2);
    fclose(f);
    return v;
}

static bool check(const char* name, const uint8_t* got,
                  const std::vector<uint8_t>& want) {
    bool ok = (memcmp(got, want.data(), want.size()) == 0);
    printf("  [%s] %s\n", ok ? "PASS" : "FAIL", name);
    if (!ok) {
        for (size_t i = 0; i < want.size(); i++)
            if (got[i] != want[i]) {
                printf("    first diff at byte %zu (slice %zu): "
                       "got %02x want %02x\n",
                       i, i / (LANES * 32), got[i], want[i]);
                break;
            }
    }
    return ok;
}

static int run_vector_check(const std::string& dir) {
    int ndev = 0;
    if (cudaGetDeviceCount(&ndev) != cudaSuccess || ndev == 0) {
        printf("no CUDA device — vector cross-check requires a GPU\n");
        return 2;
    }
    auto cache_want = read_bin(dir + "/cache.bin");
    auto seed_epoch = read_bin(dir + "/seed_epoch.bin");
    if (cache_want.size() != CACHE_WORDS * 64) {
        fprintf(stderr, "cache.bin size mismatch\n");
        return 2;
    }

    uint8_t *d_cache = nullptr, *d_seed = nullptr;
    if (cudaMalloc(&d_cache, CACHE_WORDS * 64) != cudaSuccess ||
        cudaMalloc(&d_seed, seed_epoch.size()) != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed\n");
        return 2;
    }
    cudaMemcpy(d_seed, seed_epoch.data(), seed_epoch.size(),
               cudaMemcpyHostToDevice);

    bool all_ok = true;

    // stage A: cache fill
    k_cache_fill<<<1, 1>>>(d_cache, d_seed);
    cudaError_t e = cudaDeviceSynchronize();
    if (e != cudaSuccess) {
        fprintf(stderr, "k_cache_fill failed: %s\n", cudaGetErrorString(e));
        return 1;
    }
    std::vector<uint8_t> cache_got(CACHE_WORDS * 64);
    cudaMemcpy(cache_got.data(), d_cache, cache_got.size(),
               cudaMemcpyDeviceToHost);
    all_ok &= check("cache fill (k_cache_fill)", cache_got.data(), cache_want);

    // stage B: dataset expansion (from the GPU-filled cache, not the file)
    auto dataset_want = read_bin(dir + "/dataset_eff.bin");
    auto seed_block   = read_bin(dir + "/seed_block.bin");
    uint8_t *d_dataset = nullptr, *d_seed_block = nullptr;
    if (cudaMalloc(&d_dataset, DATASET_ITEMS * 256) != cudaSuccess ||
        cudaMalloc(&d_seed_block, seed_block.size()) != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed (stage B)\n");
        return 2;
    }
    cudaMemcpy(d_seed_block, seed_block.data(), seed_block.size(),
               cudaMemcpyHostToDevice);
    k_dataset_expand<<<(DATASET_ITEMS + 255) / 256, 256>>>(
        d_dataset, d_cache, d_seed, d_seed_block);
    e = cudaDeviceSynchronize();
    if (e != cudaSuccess) {
        fprintf(stderr, "k_dataset_expand failed: %s\n", cudaGetErrorString(e));
        return 1;
    }
    std::vector<uint8_t> dataset_got(DATASET_ITEMS * 256);
    cudaMemcpy(dataset_got.data(), d_dataset, dataset_got.size(),
               cudaMemcpyDeviceToHost);
    all_ok &= check("dataset expand (k_dataset_expand)", dataset_got.data(),
                    dataset_want);

    // stage C: search — full pipeline integration (reads the GPU-generated
    // dataset, not the file), states snapshot after every round + final
    auto states_want = read_bin(dir + "/states.bin");
    auto final_want  = read_bin(dir + "/final.bin");
    auto header      = read_bin(dir + "/header.bin");
    auto nonce_bytes = read_bin(dir + "/nonce.bin");
    if (states_want.size() != (ROUNDS + 1) * LANES * 32 ||
        final_want.size() != 32 || nonce_bytes.size() != 8) {
        fprintf(stderr, "states/final/nonce size mismatch\n");
        return 2;
    }
    uint64_t nonce = 0;
    for (int b = 7; b >= 0; b--)
        nonce = (nonce << 8) | nonce_bytes[b];   // le64 decode
    uint8_t *d_header = nullptr, *d_states = nullptr, *d_final = nullptr;
    if (cudaMalloc(&d_header, header.size()) != cudaSuccess ||
        cudaMalloc(&d_states, states_want.size()) != cudaSuccess ||
        cudaMalloc(&d_final, 32) != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed (stage C)\n");
        return 2;
    }
    cudaMemcpy(d_header, header.data(), header.size(), cudaMemcpyHostToDevice);
    k_search<<<1, LANES>>>(d_dataset, d_header, (uint32_t)header.size(),
                           nonce, d_states, d_final);
    e = cudaDeviceSynchronize();
    if (e != cudaSuccess) {
        fprintf(stderr, "k_search failed: %s\n", cudaGetErrorString(e));
        return 1;
    }
    std::vector<uint8_t> states_got(states_want.size());
    std::vector<uint8_t> final_got(32);
    cudaMemcpy(states_got.data(), d_states, states_got.size(),
               cudaMemcpyDeviceToHost);
    cudaMemcpy(final_got.data(), d_final, 32, cudaMemcpyDeviceToHost);
    all_ok &= check("search states (k_search, init+8 rounds)",
                    states_got.data(), states_want);
    all_ok &= check("search final hash", final_got.data(), final_want);

    cudaFree(d_header);
    cudaFree(d_states);
    cudaFree(d_final);
    cudaFree(d_dataset);
    cudaFree(d_seed_block);
    cudaFree(d_cache);
    cudaFree(d_seed);
    printf("stage A+B+C: %s\n", all_ok ? "PASS" : "FAIL");
    return all_ok ? 0 : 1;
}

// ---------------------------------------------------------------------------
// public API (kept from the skeleton) + CLI
// ---------------------------------------------------------------------------
extern "C" {

int octet_device_count(void) {
    int n = 0;
    if (cudaGetDeviceCount(&n) != cudaSuccess) return 0;
    return n;
}

const char* octet_status(void) {
    return "OctetHash CUDA solver v0.1: BLAKE2b core, cache fill, dataset expand, search (vector-checked)";
}

int octet_selftest(void) {
    int dev = 0;
    cudaDeviceProp prop;
    if (cudaGetDeviceCount(&dev) != cudaSuccess || dev == 0) {
        printf("no CUDA device — compile-only selftest\n");
        return 0;
    }
    cudaGetDeviceProperties(&prop, 0);
    printf("device 0: %s, sm_%d%d, %d MB, %d SMs\n",
           prop.name, prop.major, prop.minor,
           (int)(prop.totalGlobalMem >> 20), prop.multiProcessorCount);
    return run_vector_check("tests/vectors");
}

}  // extern "C"

int main(int argc, char** argv) {
    std::string dir = (argc > 2 && std::string(argv[1]) == "vectors")
                          ? argv[2] : "tests/vectors";
    printf("OctetHash CUDA cross-check, vectors: %s\n", dir.c_str());
    int rc = octet_selftest();
    if (rc == 0) printf("stage A+B+C: ALL CHECKS PASSED\n");
    return rc;
}
