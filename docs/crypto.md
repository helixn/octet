# Octet — cryptography plan: post-quantum signatures & transaction privacy

**Status:** design decisions for v1 (Phase 1/2), recorded before any network
exists. Crypto is cheap to choose now and brutal to change later.

## 1. Threat model

| Component | Quantum threat | Action |
|---|---|---|
| Signatures (ECDSA/EdDSA) | broken (Shor) | **replace with ML-DSA** |
| Addresses derived from public keys | exposed after first spend | hashed addresses; pk revealed only at spend |
| OctetHash (PoW) | Grover = quadratic speedup only; memory-hardness unaffected | none; difficulty retargets |
| BLAKE2b primitives | quadratic speedup at most | sufficient output sizes |

## 2. Signatures (decided)

- **Primary: ML-DSA-65** (FIPS 204, module-lattice). Signature ≈ 2.4 KB,
  public key ≈ 1.3 KB. Transaction size ≈ 4–5 KB — accepted as the price of
  quantum resistance, budgeted into block size from day one.
- **Cold-storage option: SLH-DSA-128s** (FIPS 205, stateless hash-based) for
  wallets that prefer the most conservative assumptions; larger signatures.
- **Rejected:** Falcon (floating-point signing → side-channel hazard),
  stateful XMSS/LMS (state-reuse footgun for end users).
- **Address format:** `vc1…` = Bech32m-style encoding of
  `BLAKE2b-256(ML-DSA public key)`. Public keys are revealed only when spent,
  minimizing the quantum-exposure window of every address.

## 3. Transaction privacy — three tiers

| Tier | Privacy | Quantum-safe? | Complexity |
|---|---|---|---|
| 1 — PQ transparent (launch) | receiver hidden (one-time addresses), sender/amount visible | ✅ | low |
| 2 — note pool without zk | amount + owner hidden, sender-receiver graph broken; tree position visible | ✅ (hashes + ML-DSA only) | medium |
| 3 — full shielded (zk) | Zcash-grade | needs hash-based SNARKs (Ligero/Brakedown-class) — ECC SNARKs (Groth16/Halo2) are **not** quantum-safe | high / research |

### Tier 1 (v1 launch)

- **One-time addresses via ML-KEM (Kyber, FIPS 203)** — the PQ analogue of
  stealth addresses: sender encapsulates to the receiver's KEM key; a
  one-time address is derived from the shared secret. Receiver unlinkability
  without any trusted setup.
- Amounts transparent in v1; block explorer shows flows.

### Tier 2 (planned upgrade; protocol reserves the note model at genesis)

- Note commitment `c = BLAKE2b-256(ML-DSA-pk ‖ amount ‖ rho ‖ r)`;
  notes form a merkle tree in consensus state.
- Spend: reveal `nullifier = BLAKE2b-256(sk ‖ rho)` + merkle path to `c` +
  ML-DSA signature. Consensus checks: path valid, nullifier unspent, signature
  matches the address inside `c`.
- What the observer sees: *a* note of *unknown* amount owned by *unknown*
  key was spent; the merkle position is visible (clustering risk — accepted
  trade for skipping zk math).
- All primitives are hashes + ML-DSA: **fully quantum-resistant without
  zero-knowledge proofs**.

### Tier 3 (research track)

- Full shielded model requires zero-knowledge proofs. ECC-based SNARKs
  (Groth16, Halo2 — e.g., what NULL uses) die to Shor. Quantum-safe proof
  systems exist in research (hash-based multilinear SNARKs: Ligero,
  Brakedown-class) with 100–500 KB proofs and slow provers.
- Decision: track research; do not ship ECC-SNARK privacy that will later be
  the chain's quantum liability.

## 4. Prior art & differentiation

- NULL (nullnet.sh): shielded-only, Halo2 proofs — best-in-class privacy,
  **but not quantum-resistant**.
- Monero: RingCT privacy — ECC ring signatures, not quantum-resistant.
- Octet's niche: **PQ-first from genesis** — privacy tiers that never rely on
  broken-under-Shor primitives.

## 5. Implementation notes

- Rust crates (Phase 1/2): `pqcrypto-mldsa` / `pqcrypto-sphincs` (PQClean
  bindings) or RustCrypto ML-DSA when stable; ML-KEM for Tier 1 stealth.
- Reference Python cannot express ML-DSA in stdlib — signatures are exercised
  in node tests (Phase 1), the reference implementation keeps hash-level
  primitives only.
- Block size budget at full adoption: assume ~5 KB per transaction after
  Tier 1; revisit at Tier 2 (adds merkle paths) and Tier 3 (adds proofs).
