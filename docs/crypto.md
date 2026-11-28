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


## 4. Оферы (Offers) — Tier 2: обмен без биржи (v0.2 design, 2026-11-28)

> v0.2 — после ревью pq-crypto-review (5 блокеров закрыты): maker_vk
> в файле, плечо вложено в транзакцию, правило оплаты ask, честные
> раскрытия нот, экономика от реальных размеров ML-DSA-65.

### 4.1. Модель и файл офера

Офер = пред-подписанное ПЛЕЧО (что отдаю). Файл публикуется где угодно.

```
OfferFile {
  version: 1
  maker_vk: [u8; 1952]        // ключ офера — тейкер проверяет maker_sig (A-3)
  height_expiry: u64
  maker_inputs: [ { note_commit, amount, rho, r } ... ]
        // открытия нот офера: владение доказывается раскрытием
        // (валидатор пересчитывает commit(pk,amount,rho,r) == note_commit)
  maker_outputs: [ { commit, amount } ... ]   // сдача офера
  ask: { commit: hex, amount: u64 }           // что хочет взамен
  maker_sig: ML-DSA-65 over H("vice-offer-v1" ‖ maker_part)
}

maker_part = length-prefixed бинарная сериализация (как unsigned_payload
в tx.rs — прецедент репо) кортежа {version, maker_vk, height_expiry,
maker_inputs, maker_outputs, ask}. NOT sorted-JSON: байт-детерминизм без
JSON-нормализационных ловушек.
```

Владение maker-нотами: каждое раскрытие проверяется
`commit(pk, amount, rho, r) == note_commit` И `pk == maker_vk` — все
входные ноты плеча принадлежат оферу, чей ключ подписал намерение.

### 4.2. Атомарность: OfferCompletion-транзакция

```
Transaction.offer = {                        // новое поле, ВХОДИТ в txid
  maker_part: bytes                          // канонические байты плеча (A-2)
  maker_sig: ML-DSA-65
}
inputs:  maker_inputs(открытые) ++ taker_inputs   // оба плеча
outputs: maker_outputs ++ taker_outputs           // оба плеча
```

Правила валидатора (сверх обычных):
1. `H(maker_part) == H из подписи` и `maker_sig` валидна над
   `H("vice-offer-v1" ‖ maker_part)` ключом `maker_vk`;
2. раскрытия maker-входов валидны и их pk == maker_vk (владение плечом);
   per-input подписи для maker-входов ЗАМЕНЕНЫ maker_sig (тейкер не мог
   подписать за офера, офер не знал txid);
3. подписи тейкера — обычные per-input над txid ПОЛНОЙ транзакции
   (поле offer включено в txid → тейкер биндит и плечо);
4. nullifier'ы maker-входов свежи, height <= height_expiry;
5. **ОПЛАТА ASK**: существует выход с
   `commit == ask.commit && amount == ask.amount` — РАВЕНСТВО (не ≥),
   против обхода переплатой ниже ask. Это правило делает атомарность
   конструктивной: плечо без оплаты не проходит консенсус (фикс A-1).

Мемпол-пул: nullifier'ы внутри блока проверяются последовательно
(первая completion потребляет плечо, вторая с тем же плечом отклоняется)
— паттерн уже реализован для UTXO в tx.rs.

### 4.3. Отмена, reorg, front-run

Отмена = офер тратит входные ноты обычно → nullifier'ы плеча погашены →
completion отклоняется. Reorg возвращает nullifier'ы в пул — это
стандартная семантика финальности, а не уязвимость. Front-run (офер
видит чужую completion в mempool и успевает потратить ноты раньше) —
inherent-риск тейкера, ограничен height_expiry.

### 4.4. Приватность — честная граница

- Плечо офера публично с момента публикации файла: коммиты, суммы,
  открытия нот (в v0.2 раскрытия кладутся в completion), сдача офера
  навсегда связана с офером — хуже бейзлайна Tier 2, осознанно (как у Chia).
- Сумма ask публична on-chain — это консенсусное требование правила 5.
- Тейкер: nullifier'ы не связывают его с файлом ДО включения транзакции;
  после включения связка тейкер↔офер публична (offer прикреплён).
- Полное скрытие сумм = Tier 3 (zk) — в оферах не обещается.

### 4.5. Квантовая проверка (по протоколу pq-crypto-review)

| Элемент | Примитив | Шор? |
|---|---|---|
| maker_sig / taker_sig | ML-DSA-65 | нет |
| maker_part_hash / txid / txid-байндинг | BLAKE2b-256 | нет |
| note commit / nullifier / merkle-пути | BLAKE2b | нет |
| Владение нотой | раскрытие (pk, amount, rho, r) + recommit | нет |

ECC нет нигде; владение нотой = ML-DSA + открытие коммита, без ECDH —
фиксируется как правило имплементации (не «дорешать» ECC-примитивом).
Grover квадратичен по хэшам — 256-бит коммиты покрывают.

### 4.6. Размеры и экономика (реальные ML-DSA-65: sig 3309, pk 1952)

- OfferCompletion 1+1 вход / 1+1 выход: 2×(1952 vk) + taker sig 3309 +
  taker vk 1952 + maker_sig 3309 + maker_part ≈ 12–13 КБ.
- С несколькими входами: +3.3–5.3 КБ на дополнительный вход.
- Бюджет блока §5 пересчитан: обычная транзакция 1-in/1-out ≈ 5.6 КБ;
  оферы 2–4× этого. Для блоков 10+ транзакций ок.

### 4.7. Открытые вопросы (на pow-spec-review перед имплементацией)

1. Мульти-офер (одно плечо тейкера закрывает несколько оферов) — v2.
2. Частичное закрытие — v2 (усложняет атомарность правила 5).
3. Роутинг оферов: публичный реестр vs чистый P2P-обмен файлами.
4. Взаимодействие с Tier-1 (KEM-стелс): оферы поверх стелс-адресов.
5. Комиссия оферных транзакций: тейкер платит + min fee против mempool-
   спама чужими плечами.
6. Constant-time сравнение maker_part_hash/nullifier'ов и запрет
   логирования rho/r — на этап имплементации (side-channel фаза).
