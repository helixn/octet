"""Vice City mining core: GPU enumeration via nvidia-smi, settings
persistence, miner process control. Until the Vice City node (Phase 2)
ships a stratum protocol, the 'mine' button runs the built-in OctetHash
benchmark binary — honest placeholder, same engine as the coin."""
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ViceCity"
CONFIG_FILE = CONFIG_DIR / "mining.json"


def _default_miner() -> Path:
    """Dev: repo cuda build. Frozen: next to the exe (dist/miners/)."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for cand in (exe_dir / "miners" / "octet_test.exe",
                     exe_dir / "octet_test.exe"):
            if cand.exists():
                return cand
        return exe_dir / "miners" / "octet_test.exe"
    return Path(__file__).resolve().parents[2] / "cuda" / "octet_test.exe"


DEFAULT_MINER = _default_miner()


def list_gpus() -> list[dict]:
    """[{index, name, mem_mb}] via nvidia-smi; empty on failure."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW).stdout
        gpus = []
        for row in csv.reader(io.StringIO(out.strip())):
            if len(row) >= 3:
                gpus.append({"index": int(row[0]), "name": row[1].strip(),
                             "mem_mb": int(row[2])})
        return gpus
    except Exception:
        return []


def cpu_count() -> int:
    return os.cpu_count() or 1


def default_config() -> dict:
    gpus = list_gpus()
    return {
        "miner_path": str(DEFAULT_MINER),
        "gpu_enabled": {str(g["index"]): True for g in gpus},
        "gpu_power_limit": {str(g["index"]): "" for g in gpus},
        "cpu_mining": False,
        "cpu_cores": cpu_count(),
        "extra_args": "",
        "mode": "bench",
    }


def load_config() -> dict:
    cfg = default_config()
    if CONFIG_FILE.exists():
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k, v in saved.items():
                if k in cfg:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


class MinerProcess:
    """Runs the miner/bench binary, streams output to a callback."""

    def __init__(self):
        self.proc = None

    def start(self, cfg: dict, on_line) -> str:
        if self.proc and self.proc.poll() is None:
            return "Уже запущено"
        exe = cfg.get("miner_path") or str(DEFAULT_MINER)
        if not Path(exe).exists():
            return f"Не найден майнер: {exe}\nУкажи путь в настройках."
        args = [exe]
        if cfg.get("extra_args"):
            args += str(cfg["extra_args"]).split()
        # CUDA device selection from the enabled GPU set
        enabled = [i for i, on in cfg.get("gpu_enabled", {}).items() if on]
        if enabled and len(enabled) < len(cfg.get("gpu_enabled", {})):
            env = dict(os.environ,
                       CUDA_VISIBLE_DEVICES=",".join(enabled))
        else:
            env = dict(os.environ)
        self.proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW)
        import threading
        threading.Thread(target=self._pump, args=(on_line,),
                         daemon=True).start()
        return f"Запущено: {' '.join(args)}"

    def _pump(self, on_line):
        try:
            for line in self.proc.stdout:
                on_line(line.rstrip())
        except Exception as e:
            on_line(f"[stream error: {e}]")

    def stop(self) -> str:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
            return "Остановлено"
        return "Не запущено"

    def running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)


if __name__ == "__main__":
    print("gpus:", list_gpus())
    print("cpus:", cpu_count())
    print("config:", load_config()["miner_path"])
