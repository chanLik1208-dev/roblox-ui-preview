"""before / after 並排對照圖。

雕刻工具最重要的產出其實不是那個檔,是**這張圖** —— agent 用 Read 打開它,
就真的看到自己剛才改了什麼。沒有這張圖,「改完」只是一個信念。
"""

from PIL import Image, ImageChops, ImageDraw

from . import fonts

GAP = 16
HEADER = 30
BG = (24, 24, 28)
FG = (235, 235, 240)
ACCENT = (120, 200, 255)


def _label_font(size=15):
    try:
        f = fonts.get(("BuilderSans", 600, "Normal"), size)
        if f is not None:
            return f
    except Exception:                      # noqa: BLE001 — 字型缺失不該讓對照圖掛掉
        pass
    return None


def side_by_side(before, after, labels=("BEFORE", "AFTER"), diff=False):
    """兩張(或三張)圖拼成一張,上面有標題列。"""
    panels = [(labels[0], before), (labels[1], after)]
    if diff:
        panels.append(("DIFF", diff_heat(before, after)))

    h = max(img.height for _l, img in panels)
    w = sum(img.width for _l, img in panels) + GAP * (len(panels) - 1)
    out = Image.new("RGB", (w, h + HEADER), BG)
    draw = ImageDraw.Draw(out)
    font = _label_font()

    x = 0
    for label, img in panels:
        if img.mode != "RGB":
            img = _flatten(img)
        out.paste(img, (x, HEADER))
        draw.text((x + 8, 8), label, fill=ACCENT if label == "AFTER" else FG, font=font)
        draw.rectangle([x, HEADER, x + img.width - 1, HEADER + img.height - 1],
                       outline=(60, 60, 70))
        x += img.width + GAP
    return out


def _flatten(img):
    """RGBA 貼到深色底上 —— 對照圖不要透明,不然棋盤格會干擾判讀。"""
    bg = Image.new("RGB", img.size, BG)
    bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
    return bg


def diff_heat(before, after):
    """哪裡變了 —— 差異放大成青色熱區,沒變的地方壓暗。"""
    a = _flatten(before) if before.mode != "RGB" else before
    b = _flatten(after) if after.mode != "RGB" else after
    if a.size != b.size:
        b = b.resize(a.size)
    d = ImageChops.difference(a, b).convert("L")
    d = d.point(lambda v: min(255, v * 4))          # 微小差異也要看得見
    out = Image.new("RGB", a.size, (14, 14, 18))
    tint = Image.new("RGB", a.size, ACCENT)
    out.paste(tint, mask=d)
    return out


def changed_pixels(before, after):
    """變了幾個像素 —— 摘要用。回 (變動數, 總數)。"""
    a = _flatten(before) if before.mode != "RGB" else before
    b = _flatten(after) if after.mode != "RGB" else after
    if a.size != b.size:
        return (-1, a.width * a.height)
    d = ImageChops.difference(a, b).convert("L")
    hist = d.histogram()
    same = hist[0]
    total = a.width * a.height
    return (total - same, total)
