"""Vice City — the Paradise Coin. Desktop wallet + mining control panel.

Run:            python -m app.vicecity.app
Headless test:  python -m app.vicecity.app --selftest
"""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):          # PyInstaller
    ASSETS = Path(getattr(sys, "_MEIPASS")) / "vicecity_assets"
else:
    ASSETS = Path(__file__).resolve().parent / "assets"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling modules

import customtkinter as ctk

PINK = "#ff2d95"
CYAN = "#00e6ff"
GOLD = "#ffc428"
BG = "#14102b"
PANEL = "#1c1740"
TEXT_DIM = "#b4aadd"


def ensure_assets():
    import art
    art.ASSETS.mkdir(parents=True, exist_ok=True)
    splash = ASSETS / "splash.png"
    icon = ASSETS / "icon.ico"
    if not splash.exists():
        art.make_splash(splash)
    if not icon.exists():
        art.make_icon(icon)
    return splash, icon


# --- headless selftest -------------------------------------------------------
def selftest() -> int:
    import wallet_core
    print("=== Vice City wallet selftest ===")
    rc = wallet_core.selftest()
    import mining_core
    print("gpus           :", mining_core.list_gpus())
    print("cpu cores      :", mining_core.cpu_count())
    print("miner default  :", mining_core.DEFAULT_MINER,
          "| exists:", mining_core.DEFAULT_MINER.exists())
    return rc


# --- GUI ----------------------------------------------------------------------
def run_gui() -> None:
    splash_path, icon_path = ensure_assets()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    from PIL import Image
    import wallet_core
    import mining_core

    wallet = wallet_core.load_or_create_wallet()

    root = ctk.CTk()
    root.withdraw()
    root.title("Vice City Wallet")
    try:
        root.iconbitmap(str(icon_path))
    except Exception:
        pass

    # --- splash -------------------------------------------------------------
    splash = ctk.CTkToplevel(root)
    splash.overrideredirect(True)
    img = ctk.CTkImage(Image.open(splash_path), size=(900, 520))
    ctk.CTkLabel(splash, image=img, text="").pack()
    pvar = ctk.StringVar(value="Загрузка кошелька…")
    ctk.CTkLabel(splash, textvariable=pvar,
                 text_color=CYAN, font=("Consolas", 14)).place(x=30, y=470)
    w, h = 900, 520
    splash.update_idletasks()
    sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
    splash.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    splash.attributes("-topmost", True)

    steps = ["Открытие ключей ML-DSA-65…", "Адрес vc1 готов ✓",
             "Панель майнинга: сканирование карт…"]
    si = [0]

    def step():
        if si[0] < len(steps):
            pvar.set(steps[si[0]])
            si[0] += 1
            splash.after(700, step)
        else:
            splash.destroy()
            root.deiconify()
            root.geometry("980x640")
            root.eval("tk::PlaceWindow . center")

    splash.after(500, step)

    # --- main window ----------------------------------------------------------
    tab = ctk.CTkTabview(root, fg_color=BG)
    tab.pack(fill="both", expand=True, padx=12, pady=12)
    tab.add(" 💰 Кошелёк ")
    tab.add(" ⛏ Майнинг ")
    tab.add(" ℹ О монете ")

    # Wallet tab ---------------------------------------------------------------
    wf = tab.tab(" 💰 Кошелёк ")
    ctk.CTkLabel(wf, text="Vice City", font=("Arial Black", 34),
                 text_color=PINK).pack(pady=(18, 2))
    ctk.CTkLabel(wf, text="The Paradise Coin — тестнет ещё не запущен, "
                          "баланс появится с нодой (Фаза 2)",
                 text_color=TEXT_DIM).pack(pady=(0, 14))
    card = ctk.CTkFrame(wf, fg_color=PANEL, corner_radius=14)
    card.pack(fill="x", padx=30, pady=8)
    ctk.CTkLabel(card, text="Твой адрес (vc1):", text_color=CYAN,
                 font=("Consolas", 14)).pack(anchor="w", padx=18, pady=(14, 2))
    addr_var = ctk.StringVar(value=wallet["address"])
    ctk.CTkEntry(card, textvariable=addr_var, width=620,
                 font=("Consolas", 13), state="readonly").pack(padx=18, pady=4)
    ctk.CTkLabel(card, text=f"Отпечаток vk: "
                            f"{wallet['vk'][:8].hex()}…{wallet['vk'][-8:].hex()}"
                            f"   ·   ML-DSA-65 (FIPS 204, quantum-safe)",
                 text_color=TEXT_DIM, font=("Consolas", 11)).pack(
        anchor="w", padx=18, pady=(2, 4))
    ctk.CTkLabel(card, text=f"Файл кошелька: {wallet_core.WALLET_FILE}",
                 text_color=TEXT_DIM, font=("Consolas", 11)).pack(
        anchor="w", padx=18, pady=(0, 14))

    btns = ctk.CTkFrame(wf, fg_color="transparent")
    btns.pack(pady=10)

    def copy_addr():
        root.clipboard_clear()
        root.clipboard_append(wallet["address"])
        cinfo.configure(text="✓ адрес скопирован в буфер")

    ctk.CTkButton(btns, text="Скопировать адрес", command=copy_addr,
                  fg_color=PINK, hover_color="#d11f7a").pack(side="left",
                                                             padx=8)
    cinfo = ctk.CTkLabel(wf, text="новый" if wallet.get("fresh")
                         else "существующий кошелёк",
                         text_color=TEXT_DIM)
    cinfo.pack()

    # Mining tab -----------------------------------------------------------------
    mf = tab.tab(" ⛏ Майнинг ")
    cfg = mining_core.load_config()
    miner = mining_core.MinerProcess()

    top = ctk.CTkFrame(mf, fg_color="transparent")
    top.pack(fill="x", padx=18, pady=(14, 4))
    ctk.CTkLabel(top, text="Карты (GPU)", font=("Arial Black", 20),
                 text_color=CYAN).pack(anchor="w")

    gpu_frame = ctk.CTkScrollableFrame(mf, fg_color=PANEL, height=170)
    gpu_frame.pack(fill="x", padx=18, pady=6)
    gpu_vars = {}
    pl_vars = {}
    for g in mining_core.list_gpus():
        row = ctk.CTkFrame(gpu_frame, fg_color="transparent")
        row.pack(fill="x", pady=3)
        key = str(g["index"])
        var = ctk.BooleanVar(value=cfg["gpu_enabled"].get(key, True))
        gpu_vars[key] = var
        ctk.CTkCheckBox(
            row, text=f"GPU {g['index']}:  {g['name']}  ({g['mem_mb']} MB)",
            variable=var, checkbox_width=22, checkbox_height=22,
            fg_color=PINK, hover_color="#d11f7a").pack(side="left", padx=8)
        ctk.CTkLabel(row, text="Power limit W:", text_color=TEXT_DIM).pack(
            side="left", padx=(20, 4))
        pl = ctk.StringVar(value=cfg["gpu_power_limit"].get(key, ""))
        pl_vars[key] = pl
        ctk.CTkEntry(row, textvariable=pl, width=70,
                     placeholder_text="—").pack(side="left")

    cpurow = ctk.CTkFrame(mf, fg_color=PANEL, corner_radius=12)
    cpurow.pack(fill="x", padx=18, pady=6)
    cpu_var = ctk.BooleanVar(value=cfg.get("cpu_mining", False))
    ctk.CTkCheckBox(cpurow, text="CPU-майнинг (медленно, для ботнетов не годится 😉)",
                    variable=cpu_var, checkbox_width=22, checkbox_height=22,
                    fg_color=CYAN).pack(side="left", padx=10, pady=10)
    ctk.CTkLabel(cpurow, text="Ядра:", text_color=TEXT_DIM).pack(side="left",
                                                                 padx=(16, 6))
    cores = ctk.CTkSpinBox(cpurow, width=80,
                           from_=1, to=mining_core.cpu_count())
    cores.set(min(cfg.get("cpu_cores", mining_core.cpu_count()),
                  mining_core.cpu_count()))
    cores.pack(side="left")

    mrow = ctk.CTkFrame(mf, fg_color=PANEL, corner_radius=12)
    mrow.pack(fill="x", padx=18, pady=6)
    ctk.CTkLabel(mrow, text="Путь к майнеру:", text_color=TEXT_DIM).pack(
        anchor="w", padx=10, pady=(10, 0))
    mpath = ctk.StringVar(value=cfg["miner_path"])
    ctk.CTkEntry(mrow, textvariable=mpath, width=700,
                 font=("Consolas", 12)).pack(padx=10, pady=2)
    ctk.CTkLabel(mrow, text="Доп. аргументы:", text_color=TEXT_DIM).pack(
        anchor="w", padx=10)
    xargs = ctk.StringVar(value=cfg.get("extra_args", ""))
    ctk.CTkEntry(mrow, textvariable=xargs, width=400,
                 font=("Consolas", 12)).pack(padx=10, pady=(0, 10))

    log = ctk.CTkTextbox(mf, height=130, fg_color="#0d0a20",
                         font=("Consolas", 11), text_color=CYAN)
    log.pack(fill="both", expand=True, padx=10, pady=(4, 10))
    log.insert("0.0", "== Vice City miner console ==\n"
                       "Режим: benchmark OctetHash (stratum-протокол придёт "
                       "с нодой в Фазе 2).\n\n")

    def persist():
        cfg["miner_path"] = mpath.get().strip()
        cfg["extra_args"] = xargs.get().strip()
        cfg["gpu_enabled"] = {k: v.get() for k, v in gpu_vars.items()}
        cfg["gpu_power_limit"] = {k: v.get() for k, v in pl_vars.items()}
        cfg["cpu_mining"] = cpu_var.get()
        cfg["cpu_cores"] = int(cores.get())
        mining_core.save_config(cfg)

    def on_line(line):
        log.insert("end", line + "\n")
        log.see("end")

    def start_mining():
        persist()
        msg = miner.start(cfg, on_line)
        log.insert("end", msg + "\n")
        log.see("end")

    def stop_mining():
        persist()
        log.insert("end", miner.stop() + "\n")
        log.see("end")

    brow = ctk.CTkFrame(mf, fg_color="transparent")
    brow.pack(pady=8)
    ctk.CTkButton(brow, text="🚀 Запустить", command=start_mining,
                  fg_color=PINK, hover_color="#d11f7a",
                  font=("Arial", 15, "bold"), height=40, width=170).pack(
        side="left", padx=8)
    ctk.CTkButton(brow, text="⏹ Стоп", command=stop_mining,
                  fg_color="#3a2f66", hover_color="#5a1f45",
                  font=("Arial", 15, "bold"), height=40, width=120).pack(
        side="left", padx=8)

    # About tab ------------------------------------------------------------------
    af = tab.tab(" ℹ О монете ")
    ctk.CTkLabel(af, text="VICE CITY (VC)", font=("Arial Black", 40),
                 text_color=GOLD).pack(pady=(30, 4))
    lines = (
        "PoW: OctetHash v0.3 — 4 ГиБ датасет, re-key каждый блок, +2 ГиБ/год",
        "Криптография: ML-DSA-65 (FIPS 204) — квантово-стойкая с рождения",
        "Приватность: одноразовые адреса (ML-KEM), модель нот — Tier 1→2",
        "Защита: SRAM-асики исключены ёмкостью, ботнеты — ценой полосы",
        "",
        "Спека: docs/pow.md · Крипта: docs/crypto.md",
        "Репозиторий: github.com/helixn/octet",
        "Сетевой протокол и стратум-майнер — Фаза 2 (нода на Rust)",
    )
    for ln in lines:
        ctk.CTkLabel(af, text=ln, text_color=TEXT_DIM,
                     font=("Consolas", 13)).pack(pady=2)

    root.mainloop()


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
