"""Vice City splash art + icon generator (PIL) — original neon-vice art,
no third-party assets. Sunset over a paradise island, palms, neon coin."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 900, 520
ASSETS = Path(__file__).resolve().parent / "assets"


def _font(size: int, bold: bool = True):
    names = ["arialbd.ttf", "arial.ttf"] if bold else ["arial.ttf", "arialbd.ttf"]
    for n in names:
        p = Path("C:/Windows/Fonts") / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _vgrad(w, h, stops):
    """Vertical multi-stop gradient."""
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    n = len(stops) - 1
    for y in range(h):
        t = y / (h - 1) * n
        i = min(int(t), n - 1)
        f = t - i
        c0, c1 = stops[i], stops[i + 1]
        col = tuple(int(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))
        d.line([(0, y), (w, y)], fill=col)
    return img


def _palm(d: ImageDraw.ImageDraw, x, y, scale=1.0, color=(12, 8, 34)):
    """Stylized palm silhouette."""
    # trunk: curved stack of segments
    import math
    pts = []
    for i in range(9):
        t = i / 8
        pts.append((x + math.sin(t * 1.1) * 14 * scale, y - t * 120 * scale))
    d.line(pts, fill=color, width=max(3, int(9 * scale)))
    tx, ty = pts[-1]
    for ang, ln in [(-150, 66), (-110, 74), (-70, 70), (-30, 62), (10, 60),
                    (50, 58), (190, 60), (160, 64), (130, 66)]:
        ex = tx + math.cos(math.radians(ang)) * ln * scale
        ey = ty + math.sin(math.radians(ang)) * ln * scale * 0.55 - 8 * scale
        mx = (tx + ex) / 2
        my = (ty + ey) / 2 - 14 * scale
        d.line([(tx, ty), (mx, my), (ex, ey)], fill=color,
               width=max(2, int(4 * scale)))
    # coconuts
    for dx, dy in [(-6, -4), (5, -2)]:
        d.ellipse([tx + dx * scale - 4, ty + dy * scale - 4,
                   tx + dx * scale + 4, ty + dy * scale + 4], fill=color)


def _coin(d: ImageDraw.ImageDraw, cx, cy, r):
    """Neon coin with VC monogram."""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 196, 40),
              outline=(255, 45, 149), width=7)
    d.ellipse([cx - r + 14, cy - r + 14, cx + r - 14, cy + r - 14],
              outline=(0, 230, 255), width=4)
    f = _font(int(r * 0.9))
    d.text((cx, cy - r * 0.06), "VC", font=f, fill=(24, 10, 40), anchor="mm")


def make_splash(path: Path):
    img = _vgrad(W, H, [
        (24, 10, 52), (66, 16, 96), (146, 32, 122),
        (232, 62, 110), (255, 128, 66), (255, 196, 90),
    ])
    d = ImageDraw.Draw(img)
    # sun + reflection
    d.ellipse([W // 2 - 70, 300 - 70, W // 2 + 70, 300 + 70],
              fill=(255, 226, 130))
    glow = img.filter(ImageFilter.GaussianBlur(0))
    for i, (yy, wdt) in enumerate([(330, 140), (356, 200), (382, 150),
                                   (408, 210), (434, 160), (460, 220)]):
        d.line([(W // 2 - wdt // 2, yy), (W // 2 + wdt // 2, yy)],
               fill=(255, 210, 140), width=3)
    # sea
    d.rectangle([0, 320, W, H], fill=(38, 16, 74))
    for i, (yy, wdt) in enumerate([(330, 150), (356, 220), (382, 170),
                                   (408, 240), (434, 190), (462, 260),
                                   (490, 230)]):
        xx = W // 2 + (-1) ** i * 8
        d.line([(xx - wdt // 2, yy), (xx + wdt // 2, yy)],
               fill=(255, 150, 90), width=3)
    # horizon glow
    d.line([(0, 319), (W, 319)], fill=(255, 90, 120), width=4)
    # islands
    d.ellipse([60, 285, 340, 335], fill=(16, 8, 40))
    d.ellipse([560, 290, 880, 338], fill=(16, 8, 40))
    # palms
    _palm(d, 130, 300, 1.05, (10, 6, 30))
    _palm(d, 235, 305, 0.8, (10, 6, 30))
    _palm(d, 770, 302, 1.0, (10, 6, 30))
    _palm(d, 675, 306, 0.75, (10, 6, 30))
    # coin
    _coin(d, W // 2, 165, 84)
    # titles
    f1 = _font(64)
    d.text((W // 2, 428), "VICE CITY", font=f1, fill=(255, 45, 149),
           stroke_width=4, stroke_fill=(10, 5, 30), anchor="mm")
    f2 = _font(19, bold=False)
    d.text((W // 2, 472),
           "The Paradise Coin  ·  OctetHash PoW  ·  Quantum-Safe (ML-DSA-65)",
           font=f2, fill=(0, 230, 255), anchor="mm")
    f3 = _font(15, bold=False)
    d.text((W // 2, 500), "VC  ·  ticker VC  ·  testnet in progress",
           font=f3, fill=(180, 170, 220), anchor="mm")
    img.save(path)
    return img


def make_icon(path: Path, size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2
    r = int(size * 0.42)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 196, 40),
              outline=(255, 45, 149), width=max(6, size // 40))
    d.ellipse([cx - r * 0.82, cy - r * 0.82, cx + r * 0.82, cy + r * 0.82],
              outline=(0, 230, 255), width=max(3, size // 70))
    d.text((cx, cy), "VC", font=_font(int(r * 0.9)),
           fill=(24, 10, 40), anchor="mm")
    img.save(path, sizes=[(size, size), (64, 64), (32, 32), (16, 16)])


def ensure_assets() -> tuple[Path, Path]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    splash = ASSETS / "splash.png"
    icon = ASSETS / "icon.ico"
    if not splash.exists():
        make_splash(splash)
    if not icon.exists():
        make_icon(icon)
    return splash, icon


if __name__ == "__main__":
    s, i = ensure_assets()
    print("assets:", s, i)


def make_banner(path: Path, w: int = 980, h: int = 170):
    """Wide header banner: island sunset + neon coin + wordmark."""
    img = _vgrad(w, h, [
        (24, 10, 52), (66, 16, 96), (146, 32, 122),
        (232, 62, 110), (255, 128, 66),
    ])
    d = ImageDraw.Draw(img)
    # sun + sea line
    d.ellipse([w // 2 - 46, h - 60 - 46, w // 2 + 46, h - 60 + 46],
              fill=(255, 226, 130))
    d.rectangle([0, h - 48, w, h], fill=(38, 16, 74))
    for i, yy in enumerate(range(h - 44, h, 9)):
        xx = w // 2 + (-1) ** i * 6
        d.line([(xx - 60, yy), (xx + 60, yy)], fill=(255, 150, 90), width=2)
    d.line([(0, h - 49), (w, h - 49)], fill=(255, 90, 120), width=3)
    _palm(d, 70, h - 52, 0.72, (10, 6, 30))
    _palm(d, w - 74, h - 52, 0.72, (10, 6, 30))
    _coin(d, 148, h // 2 - 4, 44)
    f1 = _font(44)
    d.text((226, h // 2 - 22), "VICE CITY", font=f1, fill=(255, 45, 149),
           stroke_width=3, stroke_fill=(10, 5, 30))
    f2 = _font(15, bold=False)
    d.text((228, h // 2 + 16), "The Paradise Coin · OctetHash PoW · ML-DSA-65",
           font=f2, fill=(0, 230, 255))
    img.save(path)
    return img


def make_coin_png(path: Path, size: int = 96):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    _coin(d, size // 2, size // 2, int(size * 0.42))
    img.save(path)


def make_qr(path: Path, text: str, size: int = 190):
    import qrcode
    qr = qrcode.QRCode(border=1, box_size=6)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0b0a18", back_color=(255, 196, 40))
    img = img.convert("RGB").resize((size, size), Image.NEAREST)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size - 1, size - 1], outline=(255, 45, 149), width=4)
    img.save(path)


def ensure_all(banner_size=(980, 170)) -> dict:
    ASSETS.mkdir(parents=True, exist_ok=True)
    splash = ASSETS / "splash.png"
    icon = ASSETS / "icon.ico"
    banner = ASSETS / "banner.png"
    coin = ASSETS / "coin.png"
    if not splash.exists():
        make_splash(splash)
    if not icon.exists():
        make_icon(icon)
    if not banner.exists() or banner_size != (980, 170):
        make_banner(banner, *banner_size)
    if not coin.exists():
        make_coin_png(coin)
    return {"splash": splash, "icon": icon, "banner": banner, "coin": coin}


if __name__ == "__main__":
    print(ensure_all())
