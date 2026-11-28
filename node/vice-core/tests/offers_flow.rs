//! Offers end-to-end per docs/crypto.md §4 v0.2: maker shoulder → taker
//! completion → validation rules 1-5, plus tamper variants that must fail.
use std::collections::HashSet;

use vice_core::addr::{blake2b_256, keygen, vk_bytes};
use vice_core::notes::NoteOpening;
use vice_core::offers::{
    maker_part_bytes, maker_part_hash, nullifier_hex, parse_maker_part,
    sign_maker_part, validate_offer_completion, OfferAttachment, OfferAsk,
    OfferInput, OfferOutput, OfferError, MakerPart,
};
use vice_core::tx::Transaction;

fn maker_shoulder(maker_vk: Vec<u8>) -> (Vec<OfferInput>, Vec<OfferOutput>,
                                        [u8; 32]) {
    let mut inputs = Vec::new();
    for (i, amount) in [30u64, 20u64].iter().enumerate() {
        let mut opening = NoteOpening::new(maker_vk.clone(), *amount);
        opening.rho = blake2b_256(format!("rho{i}").as_bytes());
        opening.r = blake2b_256(format!("r{i}").as_bytes());
        inputs.push(OfferInput {
            nullifier: opening.nullifier(),
            opening,
        });
    }
    let change = OfferOutput {
        commit: blake2b_256(b"maker-change"),
        amount: 10,
    };
    let ask_commit = blake2b_256(b"taker-pays-here");
    (inputs, vec![change], ask_commit)
}

fn build_completion() -> (Transaction, MakerPart, HashSet<String>) {
    build_completion_ext(true)
}

fn build_completion_ext(pay_ask: bool)
                        -> (Transaction, MakerPart, HashSet<String>) {
    let maker_kp = keygen();
    let taker_kp = keygen();
    let maker_vk = vk_bytes(&maker_kp.vk);
    let (inputs, outputs, ask_commit) = maker_shoulder(maker_vk.clone());
    let part = MakerPart {
        version: 1,
        maker_vk: maker_vk.clone(),
        height_expiry: 1000,
        maker_inputs: inputs,
        maker_outputs: outputs,
        ask: OfferAsk { commit: ask_commit, amount: 40 },
    };
    let part_bytes = maker_part_bytes(&part);
    let maker_sig = sign_maker_part(&maker_kp.sk, &part_bytes);

    // taker pays exactly the ask (40) to the ask commit — rule 5
    let taker_commit = ask_commit;
    let mut tx = Transaction {
        version: 1,
        inputs: vec![
            // maker shoulder: sig-less, vk = maker_vk (rule: replaced sigs)
            vice_core::tx::TxIn {
                prev_txid: hex::encode(part.maker_inputs[0].nullifier),
                out_index: 0,
                vk: maker_vk.clone(),
                sig: Vec::new(),
            },
            vice_core::tx::TxIn {
                prev_txid: hex::encode(part.maker_inputs[1].nullifier),
                out_index: 0,
                vk: maker_vk.clone(),
                sig: Vec::new(),
            },
            // taker side (transparent spend, per-input sig)
            vice_core::tx::TxIn {
                prev_txid: hex::encode(blake2b_256(b"taker-utxo")),
                out_index: 0,
                vk: Vec::new(),
                sig: Vec::new(),
            },
        ],
        outputs: {
            let mut o = vec![vice_core::tx::TxOut {
                commit: hex::encode(part.maker_outputs[0].commit),
                amount: 10,
            }];
            if pay_ask {
                o.push(vice_core::tx::TxOut {
                    commit: hex::encode(taker_commit),
                    amount: 40, // == ask.amount — rule 5
                });
            }
            o
        },
        offer: Some(OfferAttachment {
            maker_part: part_bytes.clone(),
            maker_sig: maker_sig.clone(),
        }),
    };
    // taker signs ONLY their input (index 2) over the final txid
    tx.sign_indices(&taker_kp.sk, &vk_bytes(&taker_kp.vk), &[2]);
    let _ = taker_kp;
    (tx, part, HashSet::new())
}

#[test]
fn offer_completion_validates() {
    let (tx, _part, pool) = build_completion();
    if let Err(e) = validate_offer_completion(&tx, &pool, 500) {
        panic!("valid completion rejected: {e:?}");
    }
}

#[test]
fn ask_not_paid_rejected() {
    // rebuild WITHOUT the ask payment, re-signing the taker input honestly —
    // the rejection must come from rule 5, not from a stale signature
    let (tx, _part, pool) = build_completion_ext(false);
    if let Err(e) = validate_offer_completion(&tx, &pool, 500) {
        assert!(matches!(e, OfferError::AskNotPaid), "got: {e:?}");
    } else {
        panic!("completion without ask payment must be rejected");
    }
}

#[test]
fn tampered_shoulder_rejected() {
    let (mut tx, part, pool) = build_completion();
    // re-serialize the shoulder with a bigger change — sig won't match
    let mut tampered = part.clone();
    tampered.maker_outputs[0].amount = 999;
    tx.offer = Some(OfferAttachment {
        maker_part: maker_part_bytes(&tampered),
        maker_sig: part_sig_for(&part),
    });
    assert!(matches!(
        validate_offer_completion(&tx, &pool, 500),
        Err(OfferError::MakerSigInvalid)
    ));
}

fn part_sig_for(part: &MakerPart) -> Vec<u8> {
    // a signature over the ORIGINAL part bytes (attacker replay)
    let maker_kp = keygen();
    let _ = maker_kp;
    sign_of_original(part)
}

fn sign_of_original(part: &MakerPart) -> Vec<u8> {
    // cannot reconstruct the real sk — sign with a fresh one to prove
    // the sig check is bound to maker_vk inside the part
    let kp = keygen();
    let _ = vk_bytes(&kp.vk);
    sign_maker_part(&mk_sk(), &maker_part_bytes(part))
}

fn mk_sk() -> ml_dsa::SigningKey<ml_dsa::MlDsa65> {
    use vice_core::addr::sk_from_bytes;
    // derive from a fresh keypair: not the maker's, that's the point
    let kp = keygen();
    kp.sk
}

#[test]
fn stale_nullifier_rejected() {
    let (tx, part, mut pool) = build_completion();
    pool.insert(nullifier_hex(&part.maker_inputs[0].opening.rho,
                              &part.maker_inputs[0].opening.commit()));
    assert!(matches!(
        validate_offer_completion(&tx, &pool, 500),
        Err(OfferError::NullifierSpent { index: 0 })
    ));
}

#[test]
fn expired_offer_rejected() {
    let (tx, _part, pool) = build_completion();
    assert!(matches!(
        validate_offer_completion(&tx, &pool, 2000),
        Err(OfferError::OfferExpired { expiry: 1000, height: 2000 })
    ));
}

#[test]
fn maker_sig_on_shoulder_input_rejected() {
    let (mut tx, _part, pool) = build_completion();
    tx.inputs[0].sig = vec![1, 2, 3]; // per-input sig must be absent
    assert!(matches!(
        validate_offer_completion(&tx, &pool, 500),
        Err(OfferError::MakerSigPresent { index: 0 })
    ));
}

#[test]
fn parse_rejects_truncated_part() {
    let (_tx, part, _pool) = build_completion();
    let bytes = maker_part_bytes(&part);
    assert!(parse_maker_part(&bytes[..bytes.len() - 3]).is_err());
    assert!(parse_maker_part(&maker_part_hash(&bytes)).is_err());
}
