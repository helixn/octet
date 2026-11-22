"""Vice City — the Paradise Coin. Desktop wallet + mining + node control.

Design: sidebar navigation, neon-vice cards, sliders for every numeric
parameter. Run:            python -m app.vicecity.app
Headless test:             python -m app.vicecity.app --selftest
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

if getattr(sys, "frozen", False):          # PyInstaller
    ASSETS = Path(getattr(sys, "_MEIPASS")) / "vicecity_assets"
else:
    ASSETS = Path(__file__).resolve().parent / "assets"
sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling modules

import customtkinter as ctk

PINK = "#ff2d95"
PINK_DARK = "#c2186f"
CYAN = "#00e6ff"
GOLD = "#ffc428"
BG = "#0b0a18"
PANEL = "#171233"
PANEL2 = "#1d1740"
BORDER = "#2a2150"
DIM = "#a99dd6"
GREEN = "#39ff88"
RED = "#ff5566"

APPDATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "ViceCity"


def ensure_assets():
    import art
    return art.ensure_all()


# --- headless selftest -------------------------------------------------------
def selftest() -> int:
    import wallet_core
    import mining_core
    print("=== Vice City wallet selftest ===")
    rc = wallet_core.selftest()
    print("gpus           :", mining_core.list_gpus())
    print("cpu cores      :", mining_core.cpu_count())
    return rc


# --- small reusable widgets ----------------------------------------------------
def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=kw.get("fg_color", PANEL),
                        corner_radius=16,
                        border_width=1, border_color=BORDER)


def slider_row(parent, label, frm, to, init, fmt=str, width=210,
               progress=PINK, button=CYAN):
    """Label — slider — live value. Returns (frame, StringVar, slider)."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    var = ctk.StringVar(value=fmt(init))

    def on_change(v):
        var.set(fmt(float(v)))

    ctk.CTkLabel(row, text=label, text_color=DIM, anchor="w",
                 width=150).pack(side="left")
    slider = ctk.CTkSlider(row, from_=frm, to=to, width=width,
                           number_of_steps=max(1, int(to - frm)),
                           progress_color=progress, button_color=button,
                           button_hover_color=PINK, command=on_change)
    slider.set(init)
    slider.pack(side="left", padx=10)
    val = ctk.CTkLabel(row, text=fmt(init), text_color=CYAN, width=90,
                       font=("Consolas", 13))
    val.pack(side="left")
    return row, var, slider


def status_pill(parent):
    return ctk.CTkLabel(parent, text="● офлайн", text_color=RED,
                        font=("Consolas", 13, "bold"),
                        fg_color=PANEL2, corner_radius=12, width=190,
                        height=30)


# --- GUI ---------------------------------------------------------------------
def run_gui() -> None:
    assets = ensure_assets()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    from PIL import Image
    import hashlib
    import wallet_core
    import mining_core
    import gpu_miner as gm

    holder = {"w": wallet_core.load_or_create_wallet()}

    def wallet_commit() -> str:
        return hashlib.blake2b(holder["w"]["vk"], digest_size=32).hexdigest()

    root = ctk.CTk()
    root.withdraw()
    root.title("Vice City Wallet")
    try:
        root.iconbitmap(str(assets["icon"]))
    except Exception:
        pass

    # --- splash ---------------------------------------------------------------
    splash = ctk.CTkToplevel(root)
    splash.overrideredirect(True)
    img = ctk.CTkImage(Image.open(assets["splash"]), size=(900, 520))
    ctk.CTkLabel(splash, image=img, text="").pack()
    pvar = ctk.StringVar(value="Загрузка кошелька…")
    ctk.CTkLabel(splash, textvariable=pvar, text_color=CYAN,
                 font=("Consolas", 14)).place(x=30, y=470)
    splash.update_idletasks()
    sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
    splash.geometry("900x520+%d+%d" % ((sw - 900) // 2, (sh - 520) // 2))
    splash.attributes("-topmost", True)
    steps = ["Открытие ключей ML-DSA-65…", "Адрес vc1 готов ✓",
             "Рендер райского острова…"]
    si = [0]

    def step():
        if si[0] < len(steps):
            pvar.set(steps[si[0]])
            si[0] += 1
            splash.after(650, step)
        else:
            splash.destroy()
            root.deiconify()
            root.geometry("1040x700")
            root.eval("tk::PlaceWindow . center")

    splash.after(450, step)

    # --- layout: banner + sidebar + pages --------------------------------------
    banner = ctk.CTkImage(Image.open(assets["banner"]), size=(1008, 175))
    ctk.CTkLabel(root, image=banner, text="").pack(fill="x")

    body = ctk.CTkFrame(root, fg_color=BG)
    body.pack(fill="both", expand=True)

    sidebar = ctk.CTkFrame(body, fg_color=PANEL, width=210, corner_radius=0)
    sidebar.pack(side="left", fill="y")

    pages_host = ctk.CTkFrame(body, fg_color=BG)
    pages_host.pack(side="left", fill="both", expand=True, padx=14, pady=10)

    nav_buttons = {}
    page_frames = {}

    def show(name):
        for n, f in page_frames.items():
            if n == name:
                f.pack(fill="both", expand=True)
            else:
                f.pack_forget()
        for n, b in nav_buttons.items():
            b.configure(fg_color=PINK if n == name else "transparent",
                        text_color="#0b0a18" if n == name else DIM)

    def add_nav(label):
        b = ctk.CTkButton(sidebar, text=label, anchor="w", height=44,
                          corner_radius=12, font=("Arial", 15, "bold"),
                          fg_color="transparent", text_color=DIM,
                          hover_color=PANEL2,
                          command=lambda: show(label))
        b.pack(fill="x", padx=12, pady=6)
        nav_buttons[label] = b
        page_frames[label] = ctk.CTkFrame(pages_host, fg_color=BG)
        return page_frames[label]

    page_wallet = add_nav("💰  Кошелёк")
    page_mining = add_nav("⛏  Майнинг")
    page_node = add_nav("🌐  Нода")
    page_about = add_nav("ℹ  О монете")

    node_url = ctk.StringVar(value="http://127.0.0.1:9332")

    # ============================ WALLET PAGE ==================================
    wf = page_wallet
    ctk.CTkLabel(wf, text="Кошелёк", font=("Arial Black", 30),
                 text_color=PINK).pack(anchor="w", padx=8, pady=(6, 10))

    addr_card = card(wf)
    addr_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(addr_card, text="АДРЕС", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(14, 0))
    addr_var = ctk.StringVar(value=holder["w"]["address"])
    ctk.CTkEntry(addr_card, textvariable=addr_var, width=660,
                 font=("Consolas", 13), state="readonly",
                 fg_color=PANEL2, border_color=BORDER).pack(anchor="w",
                                                            padx=20, pady=4)
    ctk.CTkLabel(addr_card,
                 text="ML-DSA-65 (FIPS 204) · quantum-safe · "
                      f"ключи: {APPDATA_DIR / 'wallet.json'}",
                 text_color=DIM, font=("Consolas", 11)).pack(
        anchor="w", padx=20, pady=(0, 6))

    bal_card = card(wf)
    bal_card.pack(fill="x", padx=8, pady=6)
    coin_img = ctk.CTkImage(Image.open(assets["coin"]), size=(84, 84))
    ctk.CTkLabel(bal_card, image=coin_img, text="").pack(side="left",
                                                         padx=24, pady=16)
    bal_var = ctk.StringVar(value="— VC")
    ctk.CTkLabel(bal_card, textvariable=bal_var, font=("Arial Black", 40),
                 text_color=GOLD).pack(side="left", padx=8)
    ctk.CTkLabel(bal_card, text="VC · Vice City", text_color=DIM).pack(
        side="left", padx=(0, 18), pady=(0, 26))

    bal_sub = ctk.CTkLabel(bal_card, text="баланс из ноды", text_color=DIM,
                           font=("Consolas", 11))
    bal_sub.pack(side="left", padx=6, pady=(0, 30))

    qr_path = APPDATA_DIR / "address_qr.png"
    import art as _art
    _art.make_qr(qr_path, holder["w"]["address"])
    qr_img = ctk.CTkImage(Image.open(qr_path), size=(150, 150))
    ctk.CTkLabel(bal_card, image=qr_img, text="").pack(side="right", padx=20,
                                                       pady=10)

    def refresh_balance():
        try:
            commit = wallet_commit()
            info = gm.http_json(node_url.get() + "/api/info", timeout=4)
            bal = gm.http_json(node_url.get() + "/api/balance?commit=" + commit,
                               timeout=4)
            bal_var.set(f"{bal['balance']} VC")
            bal_sub.configure(text=f"нода онлайн · высота {info['height']}",
                              text_color=GREEN)
        except Exception as e:
            bal_var.set("— VC")
            bal_sub.configure(text=f"нода недоступна ({e.__class__.__name__})",
                              text_color=RED)

    def copy_addr():
        root.clipboard_clear()
        root.clipboard_append(holder["w"]["address"])
        copy_info.configure(text="✓ адрес скопирован в буфер")

    brow = ctk.CTkFrame(wf, fg_color="transparent")
    brow.pack(anchor="w", padx=8, pady=8)
    ctk.CTkButton(brow, text="Скопировать адрес", command=copy_addr,
                  fg_color=PINK, hover_color=PINK_DARK, height=38).pack(
        side="left", padx=6)
    ctk.CTkButton(brow, text="⟳ Обновить баланс", command=refresh_balance,
                  fg_color=PANEL2, hover_color=PANEL, height=38,
                  border_width=1, border_color=BORDER).pack(side="left",
                                                            padx=6)
    copy_info = ctk.CTkLabel(wf, text="", text_color=GREEN,
                             font=("Consolas", 11))
    copy_info.pack(anchor="w", padx=10)


    # ------------------------ cold wallet --------------------------------------
    def refresh_wallet_ui():
        addr_var.set(holder["w"]["address"])
        _art.make_qr(qr_path, holder["w"]["address"])
        new_qr = ctk.CTkImage(Image.open(qr_path), size=(150, 150))
        for wdg in bal_card.pack_slaves():
            try:
                if wdg.cget("image"):
                    wdg.configure(image=new_qr)
                    break
            except Exception:
                pass
        copy_info.configure(text="✓ кошелёк обновлён")

    def save_cold(cold):
        import tkinter.messagebox as mb
        if WALLET_FILE.exists():
            if not mb.askyesno(
                "Перезаписать кошелёк?",
                "Текущий кошелёк будет ПЕРЕЗАПИСАН. Старые ключи будут "
                "потеряны, если у тебя нет их резервной копии. Продолжить?",
            ):
                return False
        wallet_core.save_cold_wallet(cold, store_seed=True)
        holder["w"] = wallet_core.load_or_create_wallet()
        refresh_wallet_ui()
        root.after(300, refresh_balance)
        return True

    def create_cold_dialog():
        import tkinter.messagebox as mb
        import random as _rnd
        cold = {"data": wallet_core.create_cold_wallet()}
        dlg = ctk.CTkToplevel(root)
        dlg.title("Создание холодного кошелька")
        dlg.geometry("880x700")
        dlg.attributes("-topmost", True)
        ctk.CTkLabel(dlg, text="Запиши 24 слова БУМАГОЙ и спрячь",
                     font=("Arial Black", 22), text_color=PINK).pack(
            pady=(18, 2))
        ctk.CTkLabel(dlg, text="Это единственная копия ключей. Слова нельзя "
                               "восстановить из файла кошелька. Никому их "
                               "не показывай.",
                     text_color=RED, font=("Consolas", 12)).pack(pady=2)
        grid = ctk.CTkFrame(dlg, fg_color=PANEL, corner_radius=14)
        grid.pack(padx=24, pady=12, fill="both", expand=True)

        def render_words():
            for w in grid.winfo_children():
                w.destroy()
            words = cold["data"]["words"]
            for col in range(4):
                colf = ctk.CTkFrame(grid, fg_color="transparent")
                colf.pack(side="left", fill="both", expand=True, padx=8)
                for i, word in enumerate(words[col * 6:(col + 1) * 6]):
                    n = col * 6 + i + 1
                    ctk.CTkLabel(colf, text=f"{n:2d}. {word}",
                                 font=("Consolas", 16, "bold"),
                                 text_color=CYAN).pack(anchor="w", pady=3)

        render_words()
        pass_row = ctk.CTkFrame(dlg, fg_color="transparent")
        pass_row.pack(fill="x", padx=24, pady=6)
        ctk.CTkLabel(pass_row, text="Пассфраза (25-е слово, опционально):",
                     text_color=DIM).pack(side="left")
        pass_var = ctk.StringVar()
        ctk.CTkEntry(pass_row, textvariable=pass_var, show="•",
                     width=260).pack(side="left", padx=8)
        wrote = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(dlg, text="Я записал(а) слова на бумагу",
                        variable=wrote, checkbox_width=22,
                        checkbox_height=22, fg_color=PINK).pack(pady=6)

        verify_row = ctk.CTkFrame(dlg, fg_color=PANEL2, corner_radius=12)
        verify_row.pack(fill="x", padx=24, pady=6)
        picks = sorted(_rnd.sample(range(24), 3))
        checks = []
        ctk.CTkLabel(verify_row, text="Проверка — введи слова №",
                     text_color=DIM).pack(side="left", padx=10)
        for n in picks:
            e = ctk.CTkEntry(verify_row, width=150,
                             placeholder_text="#" + str(n + 1))
            e.pack(side="left", padx=6)
            checks.append((n, e))

        def do_create():
            if not wrote.get():
                mb.showwarning("Сначала запиши",
                               "Отметь «Я записал(а)», когда запишешь слова.")
                return
            for n, e in checks:
                if e.get().strip().lower() != cold["data"]["words"][n]:
                    mb.showerror("Проверка не пройдена",
                                 "Слово №" + str(n + 1) + " введено неверно.")
                    return
            cold["data"]["entropy"] = wallet_core.mnemonic_to_entropy(
                cold["data"]["words"], pass_var.get())
            cold["data"]["vk"], cold["data"]["sk"] =                 wallet_core.keygen_from_entropy(cold["data"]["entropy"])
            if save_cold(cold["data"]):
                dlg.destroy()

        brow = ctk.CTkFrame(dlg, fg_color="transparent")
        brow.pack(pady=8)

        def regenerate():
            cold["data"] = wallet_core.create_cold_wallet(pass_var.get())
            render_words()

        ctk.CTkButton(brow, text="⟳ Другие слова", width=150,
                      command=regenerate, fg_color=PANEL2, border_width=1,
                      border_color=BORDER).pack(side="left", padx=6)
        ctk.CTkButton(brow, text="🆕 СОЗДАТЬ КОШЕЛЁК", command=do_create,
                      fg_color=PINK, hover_color=PINK_DARK,
                      font=("Arial", 14, "bold"), height=40,
                      width=220).pack(side="left", padx=6)

    def restore_dialog():
        import tkinter.messagebox as mb
        dlg = ctk.CTkToplevel(root)
        dlg.title("Восстановление из сид-фразы")
        dlg.geometry("760x460")
        dlg.attributes("-topmost", True)
        ctk.CTkLabel(dlg, text="Введи 24 слова (через пробел или с новых "
                               "строк)", font=("Arial Black", 20),
                     text_color=CYAN).pack(pady=(18, 6))
        words_box = ctk.CTkTextbox(dlg, height=140, font=("Consolas", 14),
                                   fg_color=PANEL2, border_width=1,
                                   border_color=BORDER)
        words_box.pack(fill="x", padx=24, pady=6)
        pass_row = ctk.CTkFrame(dlg, fg_color="transparent")
        pass_row.pack(fill="x", padx=24, pady=4)
        ctk.CTkLabel(pass_row, text="Пассфраза (если была):",
                     text_color=DIM).pack(side="left")
        pass_var = ctk.StringVar()
        ctk.CTkEntry(pass_row, textvariable=pass_var, show="•",
                     width=260).pack(side="left", padx=8)

        def do_restore():
            words = words_box.get("0.0", "end").split()
            try:
                w = wallet_core.restore_from_mnemonic(words, pass_var.get())
            except ValueError as e:
                mb.showerror("Ошибка", str(e))
                return
            if save_cold(w):
                dlg.destroy()

        ctk.CTkButton(dlg, text="🔑 ВОССТАНОВИТЬ", command=do_restore,
                      fg_color=PINK, hover_color=PINK_DARK,
                      font=("Arial", 14, "bold"), height=40,
                      width=220).pack(pady=10)

    cold_card = card(wf)
    cold_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(cold_card, text="ХОЛОДНЫЙ КОШЕЛЁК · 24 слова "
                                 "(BIP-39 → ML-DSA seed)", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 0))
    ctk.CTkLabel(cold_card, text="24 слова = 256 бит энтропии = seed ключей. "
                                 "Одни и те же слова на любом устройстве "
                                 "восстанавливают тот же vc1-адрес. Слова не "
                                 "хранятся в файле кошелька.",
                 text_color=DIM, font=("Consolas", 11)).pack(
        anchor="w", padx=20, pady=(2, 6))
    cold_row = ctk.CTkFrame(cold_card, fg_color="transparent")
    cold_row.pack(pady=(4, 14))
    ctk.CTkButton(cold_row, text="🆕 Создать холодный кошелёк",
                  command=create_cold_dialog, fg_color=PINK,
                  hover_color=PINK_DARK, height=40).pack(side="left", padx=8)
    ctk.CTkButton(cold_row, text="🔑 Восстановить из слов",
                  command=restore_dialog, fg_color=PANEL2,
                  hover_color=PANEL, height=40, border_width=1,
                  border_color=BORDER).pack(side="left", padx=8)

    # ============================ MINING PAGE ==================================
    mf = page_mining
    ctk.CTkLabel(mf, text="Майнинг", font=("Arial Black", 30),
                 text_color=CYAN).pack(anchor="w", padx=8, pady=(6, 10))

    gpus = mining_core.list_gpus()
    gpu_card = card(mf)
    gpu_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(gpu_card, text="КАРТЫ · power limit, W (0 = без лимита)",
                 text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 0))
    gpu_frame = ctk.CTkScrollableFrame(gpu_card, fg_color="transparent",
                                       height=150)
    gpu_frame.pack(fill="x", padx=10, pady=6)
    gpu_vars = {}
    pl_vars = {}
    for g in gpus:
        row = ctk.CTkFrame(gpu_frame, fg_color="transparent")
        row.pack(fill="x", pady=4)
        var = ctk.BooleanVar(value=True)
        gpu_vars[str(g["index"])] = var
        ctk.CTkCheckBox(
            row, text=f"GPU {g['index']}:  {g['name']}  ({g['mem_mb']} MB)",
            variable=var, checkbox_width=22, checkbox_height=22,
            fg_color=PINK, hover_color=PINK_DARK).pack(side="left", padx=8)
        pl_row, plv, _ = slider_row(row, "W:", 0, 350, 0,
                                    fmt=lambda v: "—" if float(v) == 0
                                    else f"{int(v)} W", width=150)
        pl_row.pack(side="left", padx=(18, 0))
        pl_vars[str(g["index"])] = plv

    sliders_card = card(mf)
    sliders_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(sliders_card, text="ПАРАМЕТРЫ", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 0))
    cores_row, cores_var, _ = slider_row(
        sliders_card, "Ядра CPU:", 1, mining_core.cpu_count(),
        mining_core.cpu_count(), width=220)
    cores_row.pack(fill="x", padx=20, pady=4)
    batch_row, batch_var, _ = slider_row(
        sliders_card, "Партия попыток:", 10_000, 2_000_000, 200_000,
        fmt=lambda v: f"{int(v):,}".replace(",", " "), width=220)
    batch_row.pack(fill="x", padx=20, pady=4)
    ctk.CTkLabel(sliders_card, text="Майнинг: поиск нонсов CUDA-солвером "
                                    "через minejob живой ноды",
                 text_color=DIM, font=("Consolas", 11)).pack(
        anchor="w", padx=20, pady=(2, 12))

    log = ctk.CTkTextbox(mf, height=170, fg_color="#0d0a20",
                         font=("Consolas", 11), text_color=CYAN,
                         border_width=1, border_color=BORDER,
                         corner_radius=14)
    log.pack(fill="both", expand=True, padx=8, pady=6)
    log.insert("0.0", "== Vice City miner console ==\n")

    miner_state = {"stop": threading.Event()}

    def on_line(line):
        log.insert("end", line + "\n")
        log.see("end")

    def start_mining():
        if not gm.MINER_EXE.exists():
            on_line("✗ CUDA-солвер не найден: " + str(gm.MINER_EXE))
            return
        miner_state["stop"].clear()
        commit = wallet_commit()
        batch = int(float(batch_var.get().replace(" ", "")))
        gpus_csv = ",".join(k for k, v in gpu_vars.items() if v.get()) or "0"

        def loop():
            on_line(f"▶ майнинг · GPU [{gpus_csv}] · партия {batch:,}")
            while not miner_state["stop"].is_set():
                try:
                    job = gm.http_json(node_url.get() +
                                       f"/api/minejob?commit={commit}")
                except Exception as e:
                    on_line(f"[нода недоступна: {e.__class__.__name__}] 3 с")
                    if miner_state["stop"].wait(3):
                        break
                    continue
                on_line(f"job {job['job_id']} h={job['height']} "
                        f"target {job['target'][:10]}…")
                try:
                    r = subprocess.run(
                        [str(gm.MINER_EXE), "mine", job["pow_header"],
                         job["seed_block"], job["target"], "0", str(batch)],
                        capture_output=True, text=True, timeout=3600,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        env={**os.environ,
                             "CUDA_VISIBLE_DEVICES": gpus_csv})
                except subprocess.TimeoutExpired:
                    on_line("  партия по таймауту — новый job")
                    continue
                out = r.stdout.strip()
                if not out.startswith("FOUND"):
                    on_line("  партия без решения — новый job")
                    continue
                _, nonce, solution = out.split()
                try:
                    res = gm.http_json(node_url.get() + "/api/submit",
                                       {"job_id": job["job_id"],
                                        "nonce": int(nonce),
                                        "solution": solution})
                    if "accepted" in res:
                        on_line(f"  ★ БЛОК ПРИНЯТ {res['accepted'][:16]}… "
                                f"nonce {nonce}")
                        root.after(0, refresh_balance)
                    else:
                        on_line(f"  отклонено: {res.get('error')}")
                except Exception as e:
                    on_line(f"  submit error: {e.__class__.__name__}")

        threading.Thread(target=loop, daemon=True).start()

    def stop_mining():
        miner_state["stop"].set()
        on_line("⏹ остановлено")

    mrow = ctk.CTkFrame(mf, fg_color="transparent")
    mrow.pack(pady=6)
    ctk.CTkButton(mrow, text="🚀 ЗАПУСТИТЬ МАЙНИНГ", command=start_mining,
                  fg_color=PINK, hover_color=PINK_DARK,
                  font=("Arial", 15, "bold"), height=42, width=220).pack(
        side="left", padx=8)
    ctk.CTkButton(mrow, text="⏹ СТОП", command=stop_mining,
                  fg_color=PANEL2, hover_color="#3a2f66", border_width=1,
                  border_color=BORDER, font=("Arial", 15, "bold"),
                  height=42, width=130).pack(side="left", padx=8)

    # ============================ NODE PAGE ====================================
    nf = page_node
    ctk.CTkLabel(nf, text="Нода", font=("Arial Black", 30),
                 text_color=GOLD).pack(anchor="w", padx=8, pady=(6, 10))

    ncard = card(nf)
    ncard.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(ncard, text="ПАРАМЕТРЫ НОДЫ (vicd)", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 0))
    node_path = ctk.StringVar(
        value=str(Path(__file__).resolve().parents[2] / "node" / "target"
                  / "release" / "vicd.exe"))
    ctk.CTkEntry(ncard, textvariable=node_path, width=680,
                 font=("Consolas", 12), fg_color=PANEL2,
                 border_color=BORDER).pack(anchor="w", padx=20, pady=4)
    datadir = ctk.StringVar(value=str(APPDATA_DIR / "node"))
    ctk.CTkEntry(ncard, textvariable=datadir, width=680,
                 font=("Consolas", 12), fg_color=PANEL2,
                 border_color=BORDER).pack(anchor="w", padx=20, pady=4)
    rpc_row, rpc_var, _ = slider_row(ncard, "RPC порт:", 1024, 65535, 9332,
                                     width=220)
    rpc_row.pack(fill="x", padx=20, pady=4)
    p2p_row, p2p_var, _ = slider_row(ncard, "P2P порт:", 1024, 65535, 9333,
                                     width=220)
    p2p_row.pack(fill="x", padx=20, pady=4)

    node_state = {"p": None}
    node_pill = status_pill(nf)
    node_pill.pack(anchor="w", padx=8, pady=4)

    def poll_node():
        while True:
            try:
                info = gm.http_json(node_url.get() + "/api/info", timeout=3)
                node_pill.after(0, lambda i=info: node_pill.configure(
                    text=f"● онлайн · h {i['height']}", text_color=GREEN))
            except Exception:
                node_pill.after(0, lambda: node_pill.configure(
                    text="● офлайн", text_color=RED))
            time.sleep(5)

    threading.Thread(target=poll_node, daemon=True).start()

    def start_node():
        exe = node_path.get().strip()
        if not Path(exe).exists():
            on_line("✗ vicd не найден: " + exe)
            return
        rpc = int(float(rpc_var.get()))
        node_state["p"] = subprocess.Popen(
            [exe, "--datadir", datadir.get().strip(),
             "--rpc-port", str(rpc),
             "--p2p-port", str(int(float(p2p_var.get())))],
            creationflags=subprocess.CREATE_NO_WINDOW)
        node_url.set(f"http://127.0.0.1:{rpc}")
        on_line(f"▶ vicd запущен: rpc {rpc}, p2p {int(float(p2p_var.get()))}")

    def stop_node():
        p = node_state.get("p")
        if p and p.poll() is None:
            p.terminate()
            on_line("⏹ vicd остановлен")
        node_state["p"] = None

    nrow = ctk.CTkFrame(nf, fg_color="transparent")
    nrow.pack(pady=6)
    ctk.CTkButton(nrow, text="▶ ЗАПУСТИТЬ НОДУ", command=start_node,
                  fg_color=GOLD, hover_color="#d8a020", text_color="#0b0a18",
                  font=("Arial", 15, "bold"), height=42, width=200).pack(
        side="left", padx=8)
    ctk.CTkButton(nrow, text="⏹ СТОП", command=stop_node,
                  fg_color=PANEL2, hover_color="#3a2f66", border_width=1,
                  border_color=BORDER, font=("Arial", 15, "bold"),
                  height=42, width=130).pack(side="left", padx=8)

    # ============================ ABOUT PAGE ===================================
    af = page_about
    ctk.CTkLabel(af, text="VICE CITY (VC)", font=("Arial Black", 42),
                 text_color=GOLD).pack(pady=(26, 4))
    for ln in (
        "PoW: OctetHash v0.3 — 4 ГиБ датасет, re-key каждый блок, +2 ГиБ/год",
        "Криптография: ML-DSA-65 (FIPS 204) — квантово-стойкая с рождения",
        "Приватность: одноразовые адреса (ML-KEM), модель нот — Tier 1→2",
        "Ретаргет: оконный ±4x, MTP(11), пол сложности — §9",
        "",
        "Спека: docs/pow.md · Крипта: docs/crypto.md",
        "Репозиторий: github.com/helixn/octet",
    ):
        ctk.CTkLabel(af, text=ln, text_color=DIM,
                     font=("Consolas", 13)).pack(pady=2)

    show("💰  Кошелёк")
    root.after(300, refresh_balance)
    root.mainloop()


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    run_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
