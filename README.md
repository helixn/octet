# Vice City (VC)

> Бывшая Octet (OCT): бренд-ренейм, алгоритм OctetHash и вся математика unchanged. Адреса: `vc1…` (Bech32m HRP сменился).

A memory-bandwidth PoW cryptocurrency designed for **HBM2-class hardware**.

OctetHash — the PoW algorithm — rewards the specific profile of high-bandwidth
memory stacks: **large capacity** (8 GB dataset), **deep random-access
parallelism** across many independent memory channels, and **symmetric
read/write** economics. It is deliberately hostile to SRAM-based ASICs
(dataset does not fit), to botnets on ordinary PCs (capacity + bandwidth per
thread), and to precomputation (the dataset is re-keyed **every block**).

> **Status: Phase 0 — specification + reference implementation.**
> Nothing here is final. The spec is a draft open for review; parameters will
> change. There is no network, no wallet, no token sale, nothing to buy.

## Repository layout

```
docs/pow.md            OctetHash specification v0.1 (draft)
reference/octet_ref.py  Pure-Python reference implementation (stdlib only)
tests/                 pytest suite + determinism/tamper tests
cuda/                  CUDA skeleton of the GPU solver (compiles, kernels TODO)
.github/workflows/     CI: reference tests + CUDA compile check
```

## Quick start

```bash
pip install pytest
pytest tests/ -v                 # reference implementation self-tests
python -m reference.octet_ref selftest
make -C cuda                     # needs nvcc (compile-only, no GPU required)
```

## Design targets (v0.1)

| Property | Value |
|---|---|
| Dataset | 4 GiB at genesis, +2 GiB/year on a public schedule, re-keyed every block |
| Cache (light verification) | 128 MiB |
| Search | 4096 lanes × 16 rounds × 256 B random reads |
| Verification | replay from cache, no dataset needed |
| Sweet-spot hardware | HBM2/HBM2e stacks (V100, A100-class), 16 GB+ |
| Excluded | home PCs/botnets (capacity+bandwidth), SRAM ASICs (capacity) |

See [docs/pow.md](docs/pow.md) for the full OctetHash specification and [docs/crypto.md](docs/crypto.md) for the post-quantum signature and privacy design, rationale and the
honest attack analysis.

## License

MIT — see [LICENSE](LICENSE).
