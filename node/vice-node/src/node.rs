//! vicd — Vice City testnet node (Phase 2c+2d): chain store, mempool,
//! JSON-RPC, P2P broadcast/sync. Single-threaded consensus state; threads
//! are I/O only. Testnet consensus params by default (--mainnet switches to
//! the v0.3 genesis profile, 4 GiB light-path cache).
use std::collections::HashMap;
use std::io::{BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use vice_core::tx::{merkle_root, validate_block, Block, BlockHeader,
                    Transaction, UtxoSet};
use vice_core::{block_seed, gen_cache, Params};

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs()
}

pub struct NodeState {
    params: Params,
    datadir: PathBuf,
    cache: Vec<Vec<u8>>,
    seed_epoch: Vec<u8>,
    blocks: Vec<Block>,
    utxo: UtxoSet,
    mempool: HashMap<String, Transaction>,
    miner_commit: String,
    peers: Vec<String>,
}

impl NodeState {
    pub fn new(params: Params, datadir: PathBuf, miner_commit: String,
           peers: Vec<String>) -> Self {
        std::fs::create_dir_all(&datadir).expect("datadir");
        let seed_epoch =
            vice_core::epoch_seed(0, &[0x11u8; 32]);
        let cache =
            gen_cache(&seed_epoch, params.profile.cache_words);
        let mut st = NodeState {
            params,
            datadir,
            cache,
            seed_epoch,
            blocks: Vec::new(),
            utxo: UtxoSet::new(),
            mempool: HashMap::new(),
            miner_commit,
            peers,
        };
        st.load_or_genesis();
        st
    }

    fn chain_path(&self) -> PathBuf {
        self.datadir.join("chain.jsonl")
    }

    fn load_or_genesis(&mut self) {
        if self.chain_path().exists() {
            for line in std::fs::read_to_string(self.chain_path())
                .expect("read chain")
                .lines()
            {
                let block: Block =
                    serde_json::from_str(line).expect("chain line");
                self.apply_unchecked(&block);
            }
            println!(
                "chain loaded: {} blocks, tip {}",
                self.blocks.len(),
                self.tip_hash()
            );
            return;
        }
        // Pinned genesis (gate K4): identical on every node — fixed
        // timestamp, unspendable coinbase commit (no vk maps to all-zero
        // digest). The miner's first reward arrives in block 1's coinbase.
        let subsidy = vice_core::params::subsidy_at(&self.params, 0);
        let coinbase = Transaction {
            version: 1,
            inputs: vec![vice_core::tx::TxIn {
                prev_txid: vice_core::tx::coinbase_prev_txid(0),
                out_index: 0,
                vk: Vec::new(),
                sig: Vec::new(),
            }],
            outputs: vec![vice_core::tx::TxOut {
                commit: hex::encode([0u8; 32]),
                amount: subsidy,
            }],
        };
        let txids: Vec<[u8; 32]> = vec![coinbase.txid()];
        let header = BlockHeader {
            version: 1,
            height: 0,
            prev_hash: hex::encode([0u8; 32]),
            merkle_root: hex::encode(merkle_root(&txids)),
            timestamp: 0, // pinned (gate K4) — genesis must be identical everywhere
            target: hex::encode(self.params.target),
            seed_block: hex::encode(block_seed(&[0u8; 32], 0)),
            nonce: 0,
            solution: hex::encode([0u8; 32]),
        };
        let genesis = Block { header, txs: vec![coinbase] };
        self.apply_unchecked(&genesis);
        self.persist(&genesis);
        println!(
            "genesis created: height 0, tip {}",
            self.tip_hash()
        );
    }

    fn apply_unchecked(&mut self, block: &Block) {
        for tx in &block.txs {
            let txid_hex = hex::encode(tx.txid());
            for (idx, out) in tx.outputs.iter().enumerate() {
                self.utxo.insert(
                    (txid_hex.clone(), idx as u32),
                    (out.commit.clone(), out.amount),
                );
            }
        }
        for tx in &block.txs {
            if !tx.is_coinbase() {
                for input in &tx.inputs {
                    self.utxo
                        .remove(&(input.prev_txid.clone(), input.out_index));
                }
            }
        }
        self.blocks.push(block.clone());
    }

    fn persist(&self, block: &Block) {
        use std::io::Write as IoWrite;
        let mut f = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.chain_path())
            .expect("open chain");
        writeln!(f, "{}", serde_json::to_string(block).expect("serialize"))
            .expect("append");
    }

    #[allow(dead_code)]
    fn tip(&self) -> Option<&Block> {
        self.blocks.last()
    }

    fn tip_hash(&self) -> String {
        self.blocks.last().map(|b| b.block_id_hex()).unwrap_or_default()
    }

    fn tip_solution(&self) -> Vec<u8> {
        self.blocks
            .last()
            .map(|b| hex::decode(&b.header.solution).unwrap_or_default())
            .unwrap_or_default()
    }

    /// 2c: standalone tx validation for the mempool (no block context).
    pub fn accept_tx(&mut self, tx: Transaction) -> Result<String, String> {
        if tx.is_coinbase() || tx.outputs.is_empty() {
            return Err("coinbase/empty tx rejected".into());
        }
        let txid_hex = hex::encode(tx.txid());
        let mut in_total = 0u64;
        let mut spent = Vec::new();
        for input in &tx.inputs {
            let key = (input.prev_txid.clone(), input.out_index);
            let Some((commit, amount)) = self.utxo.get(&key) else {
                return Err(format!("unknown outpoint {}", input.prev_txid));
            };
            let Some(vk) = vice_core::addr::vk_from_bytes(&input.vk) else {
                return Err("bad vk".into());
            };
            if hex::encode(vice_core::addr::commit_of_vk(&input.vk)) != *commit
                || !vice_core::addr::verify(&vk, &tx.txid(), &input.sig)
            {
                return Err(format!("bad signature for {}", input.prev_txid));
            }
            in_total += amount;
            spent.push(key);
        }
        let out_total: u64 = tx.outputs.iter().map(|o| o.amount).sum();
        if out_total > in_total {
            return Err(format!("overspend {in_total} -> {out_total}"));
        }
        // mempool double-spend guard
        for other in self.mempool.values() {
            for a in &other.inputs {
                if spent.contains(&(a.prev_txid.clone(), a.out_index)) {
                    return Err("conflicts with a mempool tx".into());
                }
            }
        }
        self.mempool.insert(txid_hex.clone(), tx);
        Ok(txid_hex)
    }

    /// 2c: block template — coinbase (subsidy) + all mempool txs.
    pub fn template(&self, coinbase_commit: &str) -> Block {
        let height = self.blocks.len() as u64;
        let subsidy = vice_core::params::subsidy_at(&self.params, height);
        let mut txs = vec![Transaction {
            version: 1,
            inputs: vec![vice_core::tx::TxIn {
                prev_txid: vice_core::tx::coinbase_prev_txid(height),
                out_index: 0,
                vk: Vec::new(),
                sig: Vec::new(),
            }],
            outputs: vec![vice_core::tx::TxOut {
                commit: coinbase_commit.to_string(),
                amount: subsidy,
            }],
        }];
        txs.extend(self.mempool.values().cloned());
        let txids: Vec<[u8; 32]> = txs.iter().map(|t| t.txid()).collect();
        let seed_block = block_seed(&self.tip_solution(), height);
        Block {
            header: BlockHeader {
                version: 1,
                height,
                prev_hash: self.tip_hash(),
                merkle_root: hex::encode(merkle_root(&txids)),
                timestamp: now(),
                target: hex::encode(self.params.target),
                seed_block: hex::encode(&seed_block),
                nonce: 0,
                solution: hex::encode([0u8; 32]),
            },
            txs,
        }
    }

    /// 2b: validate + accept a block (chain append, broadcast by caller).
    pub fn accept_block(&mut self, block: Block) -> Result<String, String> {
        let height = self.blocks.len() as u64;
        let next_utxo = validate_block(
            &block,
            &self.params,
            height,
            &self.tip_hash(),
            &self.tip_solution(),
            &self.utxo,
            &self.cache,
            &self.seed_epoch,
        )
        .map_err(|e| format!("{e:?}"))?;
        for tx in &block.txs {
            let txid_hex = hex::encode(tx.txid());
            self.mempool.remove(&txid_hex);
        }
        self.utxo = next_utxo;
        self.persist(&block);
        self.blocks.push(block.clone());
        Ok(block.block_id_hex())
    }


    // ---- test/API helpers ---------------------------------------------------
    pub fn height(&self) -> u64 {
        self.blocks.last().map(|b| b.header.height).unwrap_or(0)
    }

    pub fn balance(&self, commit: &str) -> u64 {
        self.utxo
            .values()
            .filter(|(c, _)| c == commit)
            .map(|(_, a)| a)
            .sum()
    }

    pub fn mempool_len(&self) -> usize {
        self.mempool.len()
    }

    pub fn coinbase_txid(&self, height: u64) -> String {
        hex::encode(self.blocks[height as usize].txs[0].txid())
    }

    pub fn seed_epoch(&self) -> Vec<u8> {
        self.seed_epoch.clone()
    }

    pub fn cache(&self) -> Vec<Vec<u8>> {
        self.cache.clone()
    }

    pub fn add_peer(&mut self, peer: String) {
        self.peers.push(peer);
    }

    /// 2d: broadcast a message to all peers (fire-and-forget).
    pub fn broadcast(&self, msg: &serde_json::Value) {
        let payload = serde_json::to_vec(msg).expect("serialize");
        for peer in &self.peers {
            if let Ok(mut stream) = TcpStream::connect(peer) {
                let _ = stream.write_all(&(payload.len() as u32).to_le_bytes());
                let _ = stream.write_all(&payload);
            }
        }
    }

    pub fn handle_message(&mut self, msg: &serde_json::Value)
                   -> Option<serde_json::Value> {
        match msg.get("type").and_then(|t| t.as_str()) {
            Some("block") => {
                if let Ok(block) =
                    serde_json::from_value::<Block>(msg["block"].clone())
                {
                    let height = self.blocks.len() as u64;
                    if block.header.height == height {
                        if let Ok(id) = self.accept_block(block) {
                            println!("p2p: accepted block {id}");
                            let b = self.blocks.last().unwrap().clone();
                            let m = serde_json::json!({
                                "type": "block", "block": b
                            });
                            self.broadcast(&m);
                        }
                    }
                }
                None
            }
            Some("sync") => {
                let from = msg.get("from_height").and_then(|v| v.as_u64()).unwrap_or(0);
                let upto = self.blocks.len() as u64;
                if from < upto {
                    let blocks: Vec<Block> =
                        self.blocks[from as usize..].to_vec();
                    return Some(serde_json::json!({
                        "type": "chain",
                        "blocks": blocks,
                    }));
                }
                None
            }
            Some("chain") => {
                if let Ok(blocks) =
                    serde_json::from_value::<Vec<Block>>(msg["blocks"].clone())
                {
                    for block in blocks {
                        let height = self.blocks.len() as u64;
                        if block.header.height == height {
                            let _ = self.accept_block(block);
                        }
                    }
                }
                None
            }
            _ => None
        }
    }

    /// 2d: p2p listener thread (length-prefixed JSON messages).
    pub fn start_p2p(state: Arc<Mutex<Self>>, port: u16) {
        std::thread::spawn(move || {
            let Ok(listener) = TcpListener::bind(("0.0.0.0", port)) else {
                eprintln!("p2p: cannot bind port {port}");
                return;
            };
            println!("p2p listening on {port}");
            for conn in listener.incoming() {
                let Ok(stream) = conn else { continue };
                let state = Arc::clone(&state);
                std::thread::spawn(move || {
                    let mut reader = BufReader::new(stream);
                    let mut len_buf = [0u8; 4];
                    while reader.read_exact(&mut len_buf).is_ok() {
                        let len =
                            u32::from_le_bytes(len_buf) as usize;
                        // framing cap — attacker-controlled length prefix
                        // must not become an OOM (gate review N2)
                        if len > 64 * 1024 * 1024 {
                            break;
                        }
                        let mut payload = vec![0u8; len];
                        if reader.read_exact(&mut payload).is_err() {
                            break;
                        }
                        if let Ok(msg) =
                            serde_json::from_slice::<serde_json::Value>(&payload)
                        {
                            let reply = state
                                .lock()
                                .expect("lock")
                                .handle_message(&msg);
                            if let Some(reply) = reply {
                                let bytes =
                                    serde_json::to_vec(&reply).expect("serialize");
                                let stream = reader.get_mut();
                                let _ = stream
                                    .write_all(&(bytes.len() as u32).to_le_bytes());
                                let _ = stream.write_all(&bytes);
                                break; // close -> clean EOF for the requester
                            }
                        }
                    }
                });
            }
        });
    }

    /// 2d: one sync round against every peer.
    pub fn sync_once(&mut self) {
        let my_height = self.blocks.len() as u64;
        let msg = serde_json::json!({"type": "sync", "from_height": my_height});
        let payload = serde_json::to_vec(&msg).expect("serialize");
        let peers = self.peers.clone();
        for peer in &peers {
            let Ok(mut stream) = TcpStream::connect(peer) else { continue };
            if stream.write_all(&(payload.len() as u32).to_le_bytes()).is_err()
            {
                continue;
            }
            if stream.write_all(&payload).is_err() {
                continue;
            }
            let mut reader = BufReader::new(stream);
            let mut len_buf = [0u8; 4];
            while reader.read_exact(&mut len_buf).is_ok() {
                let len = u32::from_le_bytes(len_buf) as usize;
                let mut buf = vec![0u8; len];
                if reader.read_exact(&mut buf).is_err() {
                    break;
                }
                if let Ok(reply) =
                    serde_json::from_slice::<serde_json::Value>(&buf)
                {
                    self.handle_message(&reply);
                }
            }
        }
    }
}

pub fn rpc_loop(state: Arc<Mutex<NodeState>>, port: u16) {
    let Ok(server) = tiny_http::Server::http(("127.0.0.1", port)) else {
        eprintln!("rpc: cannot bind port {port}");
        return;
    };
    println!("rpc listening on http://127.0.0.1:{port}");
    for mut request in server.incoming_requests() {
        let method = request.method().to_string();
        let url = request.url().to_string();
        let mut body = String::new();
        let _ = request.as_reader().read_to_string(&mut body);

        let mut st = state.lock().expect("lock");
        let (status, payload) = route(&method, &url, &body, &mut st);
        let response = tiny_http::Response::from_string(payload)
            .with_status_code(status)
            .with_header(
                tiny_http::Header::from_bytes("Content-Type", "application/json")
                    .expect("header"),
            );
        let _ = request.respond(response);
    }
}

fn route(method: &str, url: &str, body: &str, st: &mut NodeState)
         -> (u16, String) {
    let (path, query) = url.split_once('?').unwrap_or((url, ""));
    let q = |key: &str| -> Option<String> {
        query.split('&').find_map(|kv| {
            let (k, v) = kv.split_once('=')?;
            (k == key).then(|| v.to_string())
        })
    };
    match (method, path) {
        ("GET", "/api/info") => {
            let j = serde_json::json!({
                "coin": "Vice City (VC)",
                "height": st.blocks.len() as u64 - 1,
                "tip": st.tip_hash(),
                "mempool": st.mempool.len(),
                "peers": st.peers.len(),
                "network": if st.params.profile.cache_words == 2048 {
                    "testnet" } else { "mainnet" },
            });
            (200, j.to_string())
        }
        ("GET", "/api/balance") => {
            let Some(commit) = q("commit") else {
                return (400, "{\"error\":\"commit=? required\"}".into());
            };
            let bal: u64 = st
                .utxo
                .values()
                .filter(|(c, _)| *c == commit)
                .map(|(_, a)| a)
                .sum();
            (200, serde_json::json!({"commit": commit, "balance": bal}).to_string())
        }
        ("GET", "/api/template") => {
            let commit = q("commit").unwrap_or_else(|| st.miner_commit.clone());
            if !commit.is_empty() {
                st.miner_commit = commit;
            }
            let miner = st.miner_commit.clone();
            (200, serde_json::to_string(&st.template(&miner)).expect("serialize"))
        }
        ("POST", "/api/tx") => match serde_json::from_str::<Transaction>(body) {
            Ok(tx) => match st.accept_tx(tx) {
                Ok(txid) => (200, serde_json::json!({"accepted": txid}).to_string()),
                Err(e) => (400, serde_json::json!({"error": e}).to_string()),
            },
            Err(e) => (400, serde_json::json!({"error": e.to_string()}).to_string()),
        },
        ("POST", "/api/block") => match serde_json::from_str::<Block>(body) {
            Ok(block) => match st.accept_block(block) {
                Ok(id) => {
                    let m = serde_json::json!({
                        "type": "block",
                        "block": st.blocks.last().unwrap().clone(),
                    });
                    st.broadcast(&m);
                    (200, serde_json::json!({"accepted": id}).to_string())
                }
                Err(e) => (400, serde_json::json!({"error": e}).to_string()),
            },
            Err(e) => (400, serde_json::json!({"error": e.to_string()}).to_string()),
        },
        ("GET", "/api/mempool") => (
            200,
            serde_json::json!({
                "txs": st.mempool.values().map(|t| t.txid_hex()).collect::<Vec<_>>()
            })
            .to_string(),
        ),
        ("GET", p) if p.starts_with("/api/block/") => {
            let h: u64 = p.trim_start_matches("/api/block/").parse().unwrap_or(0);
            if let Some(block) = st.blocks.get(h as usize) {
                (200, serde_json::to_string(block).expect("serialize"))
            } else {
                (404, "{\"error\":\"not found\"}".into())
            }
        }
        _ => (404, "{\"error\":\"unknown route\"}".into()),
    }
}
