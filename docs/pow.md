# OctetHash — specification v0.3 (DRAFT)

> **v0.3 delta (2026-11-18):** genesis dataset lowered 8 GiB → **4 GiB**
> (2^24 items × 256 B), cache 256 MiB → **128 MiB**; growth schedule
> unchanged (+2 GiB/year): 6 GiB after year 1, 8 GiB after year 2, 10 GiB
> after year 3. **Contract changes declared:** (1) the participation floor
> drops to 6 GB-class GPUs at genesis — maximum launch fleet (P106-100,
> GTX 1066, RTX 2060); (2) the botnet/ASIC floor is at its
> LOWEST at genesis — the accepted price for a broad launch fleet, the
> schedule raises it over time (Ethash-DAG pattern). Math unchanged;
> TEST_PROFILE and the committed vector snapshot are byte-identical.

> **v0.2 delta (2026-11-18):** added §10 — hardware tiers and the dataset
> growth schedule (8 GiB at genesis, +2 GiB/year on a public schedule).
> Math and parameters for the current epoch are unchanged — the committed
> test-vector snapshot stays identical to v0.1.
> **Contract change declared:** the §8 botnet outcome changes from
> «excluded» to «permitted but priced» — see §10.2 for the honest
> arithmetic (the gate is economics, not a protocol ban) and §9.6 for the
> residual threat. Motivation: keep the launch fleet broad (10–24 GB
> GPUs) while making the HBM2 tilt explicit, time-based and surprise-free.

**Status:** draft, open for adversarial review. Parameters marked `T` are
tunables and will change before any testnet. Nothing in this document is a
promise; this is a design document, not a launch.

## 1. Goals

OctetHash is a proof-of-work algorithm whose efficient evaluation requires a
memory subsystem with the profile of **HBM2/HBM2e stacks**:

1. **Capacity** — the working set is 4 GiB at genesis (grows by §10.1);
   SRAM-based ASICs are excluded because GiB-class on-die SRAM does not
   exist at any economic price.
2. **Deep random-access parallelism** — each proof attempt issues thousands
   of independent, uniformly random 256-byte reads. Stacks with many
   independent channels (HBM2: 32 × 128-bit) sustain this pattern better
   than few-channel burst-oriented buses (GDDR6X: 16 narrow channels).
3. **Symmetric read/write + re-keying** — the dataset is XOR-re-keyed from
   the chain every block; every miner rewrites the full dataset each block.
   A precomputed ASIC dataset is worthless; a DRAM-stacked ASIC inherits the
   same write burden as honest miners, so the surviving moat is *power
   efficiency per GB/s*, where HBM2 leads.

Honesty: no PoW makes hardware *impossible*, only *uneconomical*. OctetHash
aims at an economic moat, not a physical one.

## 2. Notation

- `H(x)` — BLAKE2b, 64-byte digest unless stated.
- `H_k(x)` — BLAKE2b with k-byte digest.
- `le64(n)` — little-endian 64-bit encoding of n.
- `⊕` — bytewise XOR.
- Hash inputs are concatenated without separators; all inputs are length-
  prefixed by construction (fixed fields), see §5 for domain separation.

## 3. Full-scale parameters (T)

| Parameter | Value | Note |
|---|---|---|
| `CACHE_BYTES` | 128 MiB at genesis (grows with the dataset: §10.1) | light-verification working set |
| `CACHE_WORDS` | 2²¹ × 64 B | sequential-fill chain |
| `DATASET_ITEMS` | 2²⁴ at genesis (growth schedule: §10.1) | dataset elements |
| `ITEM_BYTES` | 256 B | one dataset element |
| `ITEM_PARENTS` | 32 | cache elements mixed per dataset item |
| `LANES` | 4096 | parallel search lanes per attempt |
| `LANES_PER_BLOCK` | 1024 | CUDA block = 1024 threads |
| `ROUNDS` | 16 | dataset-read rounds per attempt |
| `BLOCK_TIME` | 120 s | per-block dataset re-key budget ≈ 10–20 s |

The reference implementation (`reference/octet_ref.py`) runs on reduced
profiles; all functions are parameterized.

## 4. Cache and dataset

### 4.1 Cache (per epoch)

`epoch = height // EPOCH_BLOCKS`. Seed: `seed_epoch = H(b"octet-epoch" ‖ epoch ‖ epoch_seed_hash)`,
where `epoch_seed_hash` is recorded in the chain at epoch start (no
precomputation beyond one epoch).

```
cache[0] = H(b"octet-cache" ‖ seed_epoch)
cache[i] = H(cache[i-1] ‖ seed_epoch ‖ le64(i))
```

Sequentially dependent: parallel generation requires ~`log(CACHE_WORDS)`
rounds of pairwise mixing; the reference does it sequentially.

### 4.2 Dataset items (base form)

Dataset item `j` (256 B) mixes `ITEM_PARENTS` cache words selected by an
index stream keyed to `j`:

```
acc = H(seed_epoch ‖ le64(j))
for k in 0..ITEM_PARENTS-1:
    p_k = int(H_8(seed_epoch ‖ le64(j) ‖ le64(k)))  mod CACHE_WORDS
    acc = H(acc ‖ cache[p_k])
item_base(j) = H_64(acc ‖ le64(0)) ‖ H_64(acc ‖ le64(1)) ‖ H_64(acc ‖ le64(2)) ‖ H_64(acc ‖ le64(3))
```

Deriving one item costs ~`(ITEM_PARENTS + 5)` BLAKE2b calls: ~50× cheaper to
*store and read* than to *derive per access* at full scale — this is what
makes the 4 GiB dataset pay for itself. Light verification (§6) derives only
the few items it needs.

### 4.3 Per-block re-keying

`seed_block = H(b"octet-block" ‖ prev_solution_hash ‖ height)`.

```
keystream(j)   = H_64(seed_block ‖ le64(j) ‖ le64(0)) ‖ … ‖ H_64(seed_block ‖ le64(j) ‖ le64(3))
item_eff(j)    = item_base(j) ⊕ keystream(j)
```

Consequence: between blocks the entire dataset changes. A miner rewrites
4 GiB per block (~5–10 s at HBM2 bandwidth); datasets from previous blocks
are worthless. An ASIC cannot bake in data; it must buy the same capacity and
write bandwidth as an honest HBM2 stack.

## 5. Proof of work (search)

Per attempt (nonce):

```
seed        = H_32(b"octet-pow" ‖ header ‖ le64(nonce))
states[i]   = H_32(b"lane" ‖ seed ‖ le64(i))            for i in 0..LANES-1
for r in 0..ROUNDS-1:
    for i in 0..LANES-1:
        addr_i  = int(states[i][0:4])  mod DATASET_ITEMS
        item_i  = item_eff(addr_i)                        # 256 B random read
        states[i] = H_32(states[i] ‖ item_i)
    b = r mod (LANES_PER_BLOCK in bits)                   # butterfly exchange
    for i in 0..LANES-1 (simultaneously):
        states[i] ⊕= states[(i ⊕ (1 << b))]
result = H_32(concat(states[0..LANES-1]))
```

Traffic per attempt at full scale: `LANES × ROUNDS × 256 B = 16 MiB` of
uniformly random reads, `4096` requests concurrently in flight. This access
pattern is the HBM2 discriminator: 32 independent channels absorb it with
near-linear bandwidth scaling; narrow-channel buses pay bank-group conflicts.

`partner = i ⊕ (1 << b)` always stays inside a `LANES_PER_BLOCK` lane group,
so a CUDA block (1024 threads, shared-memory states, `__syncthreads`) can
implement the round without global synchronization.

The proof is `(nonce)`; everything else is replayed from the header.

## 6. Verification (light path)

A node holds only the 128 MiB cache. To verify a claimed solution:

1. Derive `item_eff(addr)` for every access the search made
   (`LANES × ROUNDS` items: 65 536 × ~37 BLAKE2b calls at full scale ≈
   single-digit seconds in C/Rust), including the keystream — both are cheap
   because only a few thousand items are needed.
2. Replay the rounds and butterfly exactly as §5.
3. Check `result ≤ target`.

Verification needs no dataset, no large RAM, no GPU.

## 7. Difficulty and economics

`target` adjusts each block (standard retarget). Because the per-attempt
traffic is large (16 MiB), the attempt rate per card is in the tens of
kH/s at HBM2 bandwidth — difficulty granularity is fine-grained enough for
solo-style reward variance control.

## 8. Attack analysis (honest)

| Adversary | Outcome |
|---|---|
| SRAM ASIC | excluded by capacity: GiB-class on-die SRAM per solver is not a product |
| DRAM-stacked ASIC (Linzhi-style) | possible; forced to re-key the full dataset per block like everyone; competing on J/GB/s where HBM2 stacks lead by ~2–3× |
| Botnet / home PCs | RAM mining permitted. Honest CPU mining is ~3–4×
  worse energy-per-attempt than a mid-range GPU (random-read throughput,
  §10.2), but free-electricity botnets remain a real residual threat for
  a small network — mitigated by launch finality/checkpointing (§9.6),
  same as the rented-HBM2 threat |
| Dataset growth as an ASIC bet | the +2 GiB/year public schedule raises
  the capacity floor over time — but note the Ethash/Linzhi precedent
  (§9.6): a known schedule does not stop ASIC vendors, the real cost
  driver is the growing re-key and capacity floor |
| Rentable cloud HBM2 (V100/A100 fleet) | **the real threat** for a small network; requires strong finality/checkpointing at launch and a conservative emission ramp |
| Precomputation | bounded by per-block re-keying: work past one block is worthless |
| Light-miner abuse | dataset item derivation is ~50× the cost of a read at full scale; deriving everything per access is strictly worse |
| Unreviewed-design bugs | the primary risk; hence draft status and mandatory public review before any testnet |

## 9. Open questions (T, for review)

1. `EPOCH_BLOCKS` and whether epoch seeds should commit to the full prior
   epoch's solution hashes (slower re-key, stronger precomputation defense).
2. Keystream cost: per-block rewrite is 4 GiB of writes at genesis (grows by schedule: §10.1) — acceptable at
   HBM2 bandwidth, hostile to ≤ 8 GB cards from year 2 on (by design; at genesis 8 GB cards are full participants).
3. Butterfly stride schedule (XOR-stride vs rotation) — candidate for
   custom-silicon cache-latency attacks; needs simulation.
4. `ROUNDS`×`LANES` trade-off: attempt size vs verification cost.
5. GRINDO: whether to add a second, latency-bound stage (pointer chasing in
   dataset) to further punish non-HBM2 buses — costs verification time.
6. RAM-mining and botnets (v0.2 review finding; v0.3 lowers the floor):
   the algorithm prices CPU mining ~3–4× worse per attempt than a GPU,
   and v0.3 puts the botnet/ASIC floor at its lowest at genesis (4 GiB
   fits an 8 GB-RAM PC; 4 GiB-class DRAM is inside existing mining-ASIC
   memory). The growth schedule raises the floor yearly. Candidate
   mitigations: launch-time finality/checkpointing, emission ramp, or a
   future latency-bound stage (see 5). Ethash/Linzhi precedent: a public
   growth schedule alone does not deter ASIC vendors.

## 10. Hardware tiers and the dataset growth schedule (v0.2)

### 10.1 Growth schedule (public from genesis)

```
DATASET_ITEMS(height) = 2^24 + 2^23 * floor(height / GROWTH_PERIOD_BLOCKS)
CACHE_BYTES(height)   = DATASET_ITEMS(height) * 256 B / 32   # keeps the ratio
GROWTH_PERIOD_BLOCKS  = 262_800        # ≈ 1 year at BLOCK_TIME = 120 s
```

Genesis dataset: 4 GiB (2^24 items × 256 B), cache 128 MiB. Every
GROWTH_PERIOD_BLOCKS the dataset grows by 2 GiB (+2^23 items) and the cache
by 64 MiB, preserving the store-vs-derive ratio. Non-power-of-two item
counts are legal — addressing is modulo (`%`), exactly as the reference and
CUDA implementations already do. The schedule is fixed at genesis: no
surprise forks, old cards phase out gradually, HBM2 economics strengthen
over time.

### 10.2 Hardware tiers (who may mine, what it costs)

Mining is permissionless: any hardware that can compute the hashes may
mine. The algorithm prices memory bandwidth and capacity:

| Hardware | At genesis (4 GiB) | Verdict |
|---|---|---|
| HBM2/HBM2e stacks (V100/A100-class, 16 GB+) | 900 GB/s at ~250 W | the efficiency ceiling (best J/GB); dataset+re-key fit trivially at any schedule point |
| GDDR6X 12–24 GB | 760 GB/s at ~350 W | full participant, ~70–85% of HBM2 efficiency |
| GDDR6/6X 10–12 GB | comfortable fit at genesis (tight from year 2) | full participant |
| Cards ≤ 4–5 GB | dataset + cache + runtime overshoot | excluded at genesis (6 GB-class is the floor); the schedule narrows the fleet yearly |
| GDDR5/6 6 GB (P106-100, GTX 1066, RTX 2060) | 4 GiB fits with headroom | full participants at genesis — the broad launch fleet |
| Server/desktop CPU + DDR5 | ~80 GB/s | permitted: re-key sweep costs seconds, the real price is search throughput ≈ 4.8k attempts/s per machine (80 GB/s) vs ≈ 45.3k for a mid-range GPU (760 GB/s) — ≈ 9.4× slower, ≈ 3–4× worse J/attempt at a typical desktop/server TDP of 110–150 W vs 350 W |
| SRAM ASIC | GiB-class on-die SRAM per solver | not a product |
| DRAM-stacked ASIC | possible | must re-key the full dataset per block like everyone; competes on J/GB where HBM2 leads |

### 10.3 Verification is not affected by tiers

Nodes verify from the 128 MiB cache (light path, §6) — no dataset,
no GPU, no tier requirement. Holding, sending and validating OCT requires
only ordinary RAM. The tier system prices *mining*, not participation.
