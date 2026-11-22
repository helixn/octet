//! vicd — Vice City node CLI. All logic lives in the `vice_node` lib crate.
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

fn main() {
    let mut datadir =
        PathBuf::from(std::env::var("APPDATA").unwrap_or_else(|_| ".".into()))
            .join("ViceCity")
            .join("node");
    let mut rpc_port: u16 = 9332;
    let mut p2p_port: u16 = 9333;
    let mut peers: Vec<String> = Vec::new();
    let mut miner_commit = String::new();
    let mut mainnet = false;
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--datadir" => {
                datadir = PathBuf::from(args.next().unwrap_or_default())
            }
            "--rpc-port" => {
                rpc_port = args.next().and_then(|v| v.parse().ok()).unwrap_or(9332)
            }
            "--p2p-port" => {
                p2p_port = args.next().and_then(|v| v.parse().ok()).unwrap_or(9333)
            }
            "--peer" => peers.push(args.next().unwrap_or_default()),
            "--miner-commit" => miner_commit = args.next().unwrap_or_default(),
            "--mainnet" => mainnet = true,
            _ => {}
        }
    }
    let params = if mainnet { vice_core::MAINNET } else { vice_core::TESTNET };
    if miner_commit.is_empty() {
        let kp = vice_core::addr::keygen();
        let vk = vice_core::addr::vk_bytes(&kp.vk);
        miner_commit = hex::encode(vice_core::addr::commit_of_vk(&vk));
        println!("node coinbase address: {}", vice_core::addr::vc_address(&vk));
    }
    let peers_path = datadir.join("peers.txt");
    if peers_path.exists() {
        for line in std::fs::read_to_string(&peers_path).expect("peers").lines() {
            if !line.trim().is_empty() {
                peers.push(line.trim().to_string());
            }
        }
    }
    println!(
        "vicd: Vice City node | network: {} | datadir: {}",
        if mainnet { "mainnet" } else { "testnet" },
        datadir.display()
    );
    let state = Arc::new(Mutex::new(vice_node::NodeState::new(
        params, datadir, miner_commit, peers,
    )));
    vice_node::NodeState::start_p2p(Arc::clone(&state), p2p_port);
    let sync_state = Arc::clone(&state);
    std::thread::spawn(move || loop {
        std::thread::sleep(std::time::Duration::from_secs(15));
        sync_state.lock().expect("lock").sync_once();
    });
    vice_node::rpc_loop(state, rpc_port);
}
