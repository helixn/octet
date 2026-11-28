"""One-shot patch: theme page + pool page + wallet name into app.py."""
from pathlib import Path

p = Path("app/vicecity/app.py")
t = p.read_text(encoding="utf-8")

# 1) theme-aware colors: load settings, apply effective theme at startup
t = t.replace('''    assets = ensure_assets()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    from PIL import Image
    import hashlib
    import wallet_core
    import mining_core
    import gpu_miner as gm

    holder = {"w": wallet_core.load_or_create_wallet()}''',
'''    import theme as theme_mod
    settings = theme_mod.load_settings()
    T = theme_mod.effective_theme(settings)
    # live colors for this UI session (restart applies edits)
    globals()["PINK"] = T["accent"]
    globals()["CYAN"] = T["accent2"]
    globals()["GOLD"] = T["gold"]
    globals()["BG"] = T["bg"]
    globals()["PANEL"] = T["panel"]
    globals()["PANEL2"] = T["panel2"]
    globals()["BORDER"] = T["border"]
    globals()["DIM"] = T["dim"]
    globals()["GREEN"] = T["green"]
    globals()["RED"] = T["red"]
    globals()["THEME"] = T
    palette = settings.get("theme", "vice")

    assets = ensure_assets()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    from PIL import Image
    import hashlib
    import wallet_core
    import mining_core
    import gpu_miner as gm
    import pool as pool_mod
    import psutil_free_specs as specs_mod

    holder = {"w": wallet_core.load_or_create_wallet()}''')

# banner per palette
t = t.replace('''    banner = ctk.CTkImage(Image.open(assets["banner"]), size=(1008, 175))
    ctk.CTkLabel(root, image=banner, text="").pack(fill="x")''',
'''    banner = ctk.CTkImage(Image.open(assets["banner"]), size=(1008, 175))
    ctk.CTkLabel(root, image=banner, text="").pack(fill="x")
    wallet_name_lbl = ctk.CTkLabel(
        sidebar, text="🏷 " + settings.get("wallet_name", "My Vice Wallet"),
        text_color=CYAN, font=("Consolas", 12, "bold"), wraplength=180)
    wallet_name_lbl.pack(fill="x", padx=14, pady=(2, 8))''')

# 2) nav entries for the two new pages
t = t.replace('''    page_wallet = add_nav("💰  Кошелёк")
    page_mining = add_nav("⛏  Майнинг")
    page_node = add_nav("🌐  Нода")
    page_about = add_nav("ℹ  О монете")''','''    page_wallet = add_nav("💰  Кошелёк")
    page_mining = add_nav("⛏  Майнинг")
    page_node = add_nav("🌐  Нода")
    page_pool = add_nav("🏊  Пул")
    page_theme = add_nav("🎨  Оформление")
    page_about = add_nav("ℹ  О монете")''')

# 3) insert POOL + THEME pages before ABOUT section
anchor = '''    # ============================ ABOUT PAGE ==================================='''
new_pages = '''    # ============================ POOL PAGE ====================================
    pf = page_pool
    ctk.CTkLabel(pf, text="Пул", font=("Arial Black", 30),
                 text_color=CYAN).pack(anchor="w", padx=8, pady=(6, 10))
    ctk.CTkLabel(pf, text="Свой майнинг-пул: майнеры подключают gpu_miner "
                          "к адресу пула; пул раздаёт jobs ноды, "
                          "перепроверяет решения и ведёт статы шаров.",
                 text_color=DIM, font=("Consolas", 12)).pack(
        anchor="w", padx=8, pady=(0, 8))

    hw = specs_mod.hardware_specs()
    gate = pool_mod.hardware_gate(hw, int(settings.get("pool_min_ram_gb", 96)),
                                  int(settings.get("pool_min_threads", 14)))
    hw_card = card(pf)
    hw_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(hw_card, text="ТРЕБОВАНИЯ К МОЩНОСТИ (пороги — слайдеры)",
                 text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 0))
    hw_pill = ctk.CTkLabel(
        hw_card,
        text=("✓ МОЩНОСТЬ ДОСТАТОЧНА" if gate["ok"] else
              "✗ НИЖЕ ПОРОГА — пул не запустится"),
        text_color=GREEN if gate["ok"] else RED,
        font=("Arial", 15, "bold"), fg_color=PANEL2, corner_radius=10,
        height=34)
    hw_pill.pack(anchor="w", padx=20, pady=6)
    ram_row, ram_min_var, _ = slider_row(
        hw_card, "Мин. RAM, ГБ:", 0, 128, int(settings.get("pool_min_ram_gb",
                                                           96)), width=220)
    ram_row.pack(fill="x", padx=20, pady=4)
    thr_row, thr_min_var, _ = slider_row(
        hw_card, "Мин. потоков CPU:", 1, os.cpu_count() or 1,
        int(settings.get("pool_min_threads", 14)), width=220)
    thr_row.pack(fill="x", padx=20, pady=4)
    ctk.CTkLabel(hw_card, text=f"Факт: {hw['ram_gb']} ГБ RAM · "
                               f"{hw['threads']} потоков CPU",
                 text_color=CYAN, font=("Consolas", 13, "bold")).pack(
        anchor="w", padx=20, pady=(0, 12))

    pool_card = card(pf)
    pool_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(pool_card, text="НАСТРОЙКИ ПУЛА", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 0))
    pool_name_var = ctk.StringVar(
        value=settings.get("wallet_name", "My Vice Pool") + " Pool")
    ctk.CTkEntry(pool_card, textvariable=pool_name_var, width=420,
                 font=("Consolas", 12), fg_color=PANEL2,
                 border_color=BORDER).pack(anchor="w", padx=20, pady=4)
    port_row, pool_port_var, _ = slider_row(pool_card, "Порт пула:", 1024,
                                            65535,
                                            int(settings.get("pool_port",
                                                             9342)),
                                            width=220)
    port_row.pack(fill="x", padx=20, pady=4)

    pool_state = {"srv": None}
    pool_stats = ctk.CTkLabel(pool_card, text="пул не запущен",
                              text_color=DIM, font=("Consolas", 12))
    pool_stats.pack(anchor="w", padx=20, pady=6)

    def persist_pool():
        settings["pool_min_ram_gb"] = int(float(ram_min_var.get()))
        settings["pool_min_threads"] = int(float(thr_min_var.get()))
        settings["pool_port"] = int(float(pool_port_var.get()))
        theme_mod.save_settings(settings)

    def start_pool():
        persist_pool()
        specs = specs_mod.hardware_specs()
        g = pool_mod.hardware_gate(
            specs, settings["pool_min_ram_gb"], settings["pool_min_threads"])
        if not g["ok"]:
            pool_stats.configure(
                text=f"✗ гейт: {specs['ram_gb']} ГБ RAM / "
                     f"{specs['threads']} потоков ниже порога",
                text_color=RED)
            return
        srv = pool_mod.PoolServer(node_url.get().replace(":9332", ":9332"),
                                  pool_name_var.get().strip(),
                                  settings["pool_port"])
        try:
            srv.start()
        except OSError as e:
            pool_stats.configure(text=f"✗ порт занят ({e})", text_color=RED)
            return
        pool_state["srv"] = srv
        pool_stats.configure(
            text=f"● пул онлайн :{settings['pool_port']} · "
                 f"майнеры подключают gpu_miner --node http://<ip>:"
                 f"{settings['pool_port']}",
            text_color=GREEN)

    def stop_pool():
        if pool_state["srv"]:
            pool_state["srv"].stop()
            pool_state["srv"] = None
            pool_stats.configure(text="пул остановлен", text_color=DIM)

    def refresh_pool_stats():
        srv = pool_state.get("srv")
        if srv:
            try:
                s = gm.http_json(f"http://127.0.0.1:{settings['pool_port']}"
                                 f"/api/stats", timeout=3)
                pool_stats.configure(
                    text=f"● майнеры: {s['miners']} · шары: "
                         f"{sum(s['shares'].values())} · блоки: "
                         f"{s['blocks_found']}", text_color=GREEN)
            except Exception:
                pass
        root.after(3000, refresh_pool_stats)

    prow = ctk.CTkFrame(pf, fg_color="transparent")
    prow.pack(pady=6)
    ctk.CTkButton(prow, text="▶ ЗАПУСТИТЬ ПУЛ", command=start_pool,
                  fg_color=CYAN, hover_color="#00b0cc", text_color="#0b0a18",
                  font=("Arial", 15, "bold"), height=42,
                  width=200).pack(side="left", padx=8)
    ctk.CTkButton(prow, text="⏹ СТОП", command=stop_pool,
                  fg_color=PANEL2, hover_color="#3a2f66", border_width=1,
                  border_color=BORDER, font=("Arial", 15, "bold"),
                  height=42, width=130).pack(side="left", padx=8)

    # ============================ THEME PAGE ===================================
    tf = page_theme
    ctk.CTkLabel(tf, text="Оформление", font=("Arial Black", 30),
                 text_color=PINK).pack(anchor="w", padx=8, pady=(6, 10))
    ctk.CTkLabel(tf, text="Цвета, обложка и имя кошелька. «Применить» "
                          "перезапускает окно с новой темой.",
                 text_color=DIM, font=("Consolas", 12)).pack(
        anchor="w", padx=8, pady=(0, 8))

    preset_card = card(tf)
    preset_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(preset_card, text="ТЕМЫ (пресеты + палитры обложки)",
                 text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 4))
    pr_row = ctk.CTkFrame(preset_card, fg_color="transparent")
    pr_row.pack(padx=20, pady=4)
    for key, pr in theme_mod.PRESETS.items():
        ctk.CTkButton(pr_row, text=pr["title"].split(" (")[0],
                      width=130, height=40,
                      fg_color=pr["accent"], hover_color=pr["accent2"],
                      text_color="#0b0a18",
                      command=lambda k=key: (
                          settings.update({"theme": k,
                                           "custom_colors": {}}),
                          theme_mod.save_settings(settings),
                          restart_app())).pack(side="left", padx=6)

    color_card = card(tf)
    color_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(color_card, text="СВОИ ЦВЕТА", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 4))
    color_row = ctk.CTkFrame(color_card, fg_color="transparent")
    color_row.pack(padx=20, pady=4)

    def pick_color(field):
        import tkinter.colorchooser as cc
        _, hexcol = cc.askcolor(color=T.get(field, PINK))
        if hexcol:
            cc2 = dict(settings.get("custom_colors", {}))
            cc2[field] = hexcol
            settings.update({"theme": settings.get("theme", "vice"),
                             "custom_colors": cc2})
            theme_mod.save_settings(settings)

    ctk.CTkButton(color_row, text="Акцент (розовый)", width=170,
                  command=lambda: pick_color("accent"),
                  fg_color=PINK).pack(side="left", padx=6)
    ctk.CTkButton(color_row, text="Второй (циан)", width=170,
                  command=lambda: pick_color("accent2"),
                  fg_color=CYAN, text_color="#0b0a18").pack(side="left",
                                                            padx=6)
    ctk.CTkButton(color_row, text="Золото", width=140,
                  command=lambda: pick_color("gold"),
                  fg_color=GOLD, text_color="#0b0a18").pack(side="left",
                                                            padx=6)

    cover_card = card(tf)
    cover_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(cover_card, text="ОБЛОЖКА", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 4))
    cover_row = ctk.CTkFrame(cover_card, fg_color="transparent")
    cover_row.pack(padx=20, pady=4)
    for key in ["sunset", "ocean", "aurora", "noir", "sakura"]:
        ctk.CTkButton(cover_row, text={"sunset": "🌅", "ocean": "🌊",
                                       "aurora": "🌌", "noir": "🖤",
                                       "sakura": "🌸"}[key], width=64,
                      height=44,
                      command=lambda k=key: (
                          theme_mod.set_custom_cover.__self__ if False else
                          settings.update({"custom_cover": "",
                                           "theme": k}),
                          theme_mod.save_settings(settings),
                          restart_app())).pack(side="left", padx=4)
    ctk.CTkButton(cover_row, text="📁 Своя картинка", width=180, height=44,
                  command=lambda: pick_cover_file(), fg_color=PANEL2,
                  border_width=1, border_color=BORDER).pack(side="left",
                                                            padx=8)

    def pick_cover_file():
        import tkinter.filedialog as fd
        path = fd.askopenfilename(title="Выбери обложку",
                                  filetypes=[("Изображения",
                                              "*.png *.jpg *.jpeg *.bmp")])
        if path:
            try:
                theme_mod.set_custom_cover(path)
                settings["custom_cover"] = str(
                    theme_mod.COVERS_DIR / ("cover" + Path(path).suffix))
                theme_mod.save_settings(settings)
                restart_app()
            except Exception as ex:
                ctk.CTkLabel(tf, text=f"✗ {ex}", text_color=RED).pack()

    name_card = card(tf)
    name_card.pack(fill="x", padx=8, pady=6)
    ctk.CTkLabel(name_card, text="ИМЯ КОШЕЛЬКА (локальное, видно в сайдбаре "
                                 "и пуле)", text_color=CYAN,
                 font=("Consolas", 12, "bold")).pack(anchor="w", padx=20,
                                                     pady=(12, 4))
    name_var = ctk.StringVar(
        value=settings.get("wallet_name", "My Vice Wallet"))
    ctk.CTkEntry(name_card, textvariable=name_var, width=420,
                 font=("Consolas", 13), fg_color=PANEL2,
                 border_color=BORDER).pack(anchor="w", padx=20, pady=4)
    ctk.CTkLabel(name_card, text="Уникальность on-chain (регистрация имени "
                                 "нотой) — Tier-2 роадмап; сейчас имя "
                                 "локальное и уникально на устройстве.",
                 text_color=DIM, font=("Consolas", 11)).pack(
        anchor="w", padx=20, pady=(0, 12))

    def save_name():
        settings["wallet_name"] = name_var.get().strip() or "My Vice Wallet"
        theme_mod.save_settings(settings)
        wallet_name_lbl.configure(text="🏷 " + settings["wallet_name"])
        pool_name_var.set(settings["wallet_name"] + " Pool")

    ctk.CTkButton(name_card, text="Сохранить имя", command=save_name,
                  fg_color=PINK, hover_color=PINK_DARK, height=36,
                  width=180).pack(anchor="w", padx=20, pady=(0, 14))

''' + anchor
t = t.replace(anchor, new_pages, 1)

# 4) restart helper + custom cover in ensure_assets
t = t.replace('''    show("💰  Кошелёк")
    root.after(300, refresh_balance)
    root.mainloop()''','''    def restart_app():
        root.destroy()
        run_gui()

    # custom user cover overrides the built-in banner
    cover_file = theme_mod.active_cover_path(settings)
    if cover_file is not None:
        try:
            custom_banner = ctk.CTkImage(Image.open(cover_file),
                                         size=(1008, 175))
            for wdg in root.pack_slaves():
                if isinstance(wdg, ctk.CTkLabel) and wdg.cget("image"):
                    wdg.configure(image=custom_banner)
                    break
        except Exception:
            pass

    show("💰  Кошелёк")
    root.after(300, refresh_balance)
    refresh_pool_stats()
    root.mainloop()''')

p.write_text(t, encoding="utf-8")
print("app.py: theme + pool pages wired")
