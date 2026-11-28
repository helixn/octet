//! Cross-language signature compatibility: a signature made by the Python
//! wallet (dilithium-py) must verify in the Rust node. Files are generated
//! by the local compat check; the test skips when they are absent (CI).
use vice_core::addr::vk_from_bytes;

#[test]
fn python_signature_verifies_in_rust() {
    let tmp = std::env::var("TEMP")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| std::path::PathBuf::from("/tmp"));
    let vk_hex = std::fs::read_to_string(tmp.join("py_vk.hex"))
        .unwrap_or_default();
    if vk_hex.trim().is_empty() {
        eprintln!("py_vk.hex absent — skipping (CI)");
        return;
    }
    let sig_hex = std::fs::read_to_string(tmp.join("py_sig.hex")).unwrap();
    let vk = vk_from_bytes(&hex::decode(vk_hex.trim()).unwrap())
        .expect("decode vk");
    let sig = hex::decode(sig_hex.trim()).unwrap();
    assert!(vice_core::addr::verify(&vk, b"vice-city-cross-lang-test", &sig),
            "Python dilithium-py signature must verify in Rust");
}
