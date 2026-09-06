"""字型解析:Roblox 的 FontFace(family + weight + style) -> 本機真實 .ttf/.otf。

本機裝了 Roblox 客戶端就有整套原廠字型(content/fonts + families/*.json),
用它們量測與繪製,文字寬度才會跟 Studio 一致 —— 拿 Arial 頂替會整排跑掉。
"""

import glob
import json
import os

from PIL import ImageFont

_ROBLOX_VERSIONS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Roblox\Versions"),
    os.path.expandvars(r"%LOCALAPPDATA%\Bloxstrap\Versions"),
    r"C:\Program Files (x86)\Roblox\Versions",
]

_font_dirs = None
_family_cache = {}
_font_cache = {}
_missing = set()


def _discover():
    """找出 Roblox 的 content/fonts 與 StudioFonts 目錄(可能有多個版本)。"""
    global _font_dirs
    if _font_dirs is not None:
        return _font_dirs
    dirs = []
    for base in _ROBLOX_VERSIONS:
        if not os.path.isdir(base):
            continue
        for ver in sorted(os.listdir(base), reverse=True):
            for sub in ("content/fonts", "StudioFonts"):
                p = os.path.join(base, ver, sub.replace("/", os.sep))
                if os.path.isdir(p):
                    dirs.append(p)
    _font_dirs = dirs
    return dirs


def roblox_available():
    return bool(_discover())


# Roblox 換過字型:Gotham 系列已全面改用 BuilderSans,舊 place 仍寫著舊名字。
# 值是 None 表示「認得但本機沒有」,會走 fallback 且照常回報。
FAMILY_ALIASES = {
    "GothamSSm": "BuilderSans",
    "Gotham": "BuilderSans",
    "GothamBold": "BuilderSans",
    "GothamBlack": "BuilderSans",
    "GothamMedium": "BuilderSans",
    "Arial": "LegacyArial",
    "SourceSans": "SourceSansPro",
    "Zekton": "Zekton",
}


def _load_family(family):
    """讀 families/<family>.json,回傳 [(weight, style, 檔案路徑或 None), …]"""
    if family in _family_cache:
        return _family_cache[family]
    family = FAMILY_ALIASES.get(family, family)
    if family in _family_cache:
        return _family_cache[family]
    faces = []
    for d in _discover():
        cand = os.path.join(d, "families", family + ".json")
        if not os.path.isfile(cand):
            continue
        try:
            with open(cand, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        for face in data.get("faces", []):
            asset = face.get("assetId", "")
            path = None
            if asset.startswith("rbxasset://"):
                rel = asset[len("rbxasset://") :]
                # rbxasset://fonts/Foo.ttf -> <content>/fonts/Foo.ttf
                for d2 in _discover():
                    base = d2
                    if rel.startswith("fonts/"):
                        cand2 = os.path.join(os.path.dirname(base), *rel.split("/"))
                    else:
                        cand2 = os.path.join(base, *rel.split("/"))
                    if os.path.isfile(cand2):
                        path = cand2
                        break
                if path is None:
                    leaf = rel.rsplit("/", 1)[-1]
                    path = _find_file(leaf)
            faces.append((face.get("weight", 400), face.get("style", "normal"), path))
        break
    if not faces:
        # 沒有 family json(例如 Zekton / 自訂字型),用檔名猜
        hit = _find_file(family + "-Regular.ttf") or _find_file(family + ".ttf")
        if hit:
            faces = [(400, "normal", hit)]
    _family_cache[family] = faces
    return faces


def _find_file(leaf):
    for d in _discover():
        p = os.path.join(d, leaf)
        if os.path.isfile(p):
            return p
        hits = glob.glob(os.path.join(d, leaf))
        if hits:
            return hits[0]
    return None


def _pick_face(family, weight, italic):
    faces = _load_family(family)
    usable = [f for f in faces if f[2]]
    if not usable:
        return None
    want_style = "italic" if italic else "normal"
    same_style = [f for f in usable if f[1] == want_style] or usable
    # 先求 style 相符,再求 weight 最接近
    best = min(same_style, key=lambda f: abs(f[0] - weight))
    return best[2]


_FALLBACKS = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
]


def _fallback_path():
    for p in _FALLBACKS:
        if os.path.isfile(p):
            return p
    return None


def get(font_face, size):
    """font_face = (family, weight, style),size = TextSize(px)。回傳 PIL FreeTypeFont。

    Roblox 的 TextSize 是「行高」而不是 em size —— 實測 em ≈ TextSize,
    但 SourceSansPro 的 ascender+descender 略大於 em,所以直接用 size 當 em
    再由 layout 端依 metrics 對齊,誤差最小。
    """
    family, weight, style = font_face
    size = max(1, int(round(size)))
    key = (family, weight, style, size)
    if key in _font_cache:
        return _font_cache[key]

    italic = str(style).lower() == "italic"
    path = _pick_face(family, weight, italic)
    if path is None:
        # 數字 family = 開發者自己上傳的字型資產,本機一定沒有
        _missing.add(f"自訂字型 rbxassetid://{family}" if family.isdigit() else family)
        path = _fallback_path()
    try:
        font = ImageFont.truetype(path, size) if path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def missing_families():
    return sorted(_missing)


# --------------------------------------------------------------------------
# CJK fallback
# --------------------------------------------------------------------------

# Roblox 內建的字型全部只涵蓋拉丁/希臘/西里爾。中日韓文字在 Roblox 客戶端是靠
# 引擎自己的 fallback 鏈補的 —— 這裡照做,不然中文 UI 預覽出來全是豆腐,
# agent 會以為是自己把文字寫壞了。
#
# 沒有用 fontTools 去讀 cmap(會多一個相依),改用碼位範圍判斷:
# 一個 run 只要含 CJK 就整段換成 CJK 字型。CJK 字型自己也有拉丁字母,
# 所以「商店 SHOP」這種混排不會壞。
_CJK_RANGES = (
    (0x1100, 0x11FF),    # 韓文字母
    (0x2E80, 0x2FDF),    # 部首
    (0x3000, 0x30FF),    # 標點 + 平假名 + 片假名
    (0x3130, 0x318F),    # 韓文相容字母
    (0x3400, 0x4DBF),    # 擴充 A
    (0x4E00, 0x9FFF),    # 統一表意文字
    (0xA960, 0xA97F),
    (0xAC00, 0xD7AF),    # 韓文音節
    (0xF900, 0xFAFF),    # 相容表意文字
    (0xFF00, 0xFFEF),    # 全形
    (0x20000, 0x3FFFF),  # 擴充 B 以後
)

# 依「粗體與否」挑。繁中優先(這台機器的使用情境),其次日韓通用的。
_CJK_FONTS = {
    False: [r"C:\Windows\Fonts\msjh.ttc", r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\mingliu.ttc", r"C:\Windows\Fonts\simsun.ttc",
            r"C:\Windows\Fonts\YuGothR.ttc", r"C:\Windows\Fonts\malgun.ttf"],
    True: [r"C:\Windows\Fonts\msjhbd.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
           r"C:\Windows\Fonts\mingliub.ttc", r"C:\Windows\Fonts\YuGothB.ttc",
           r"C:\Windows\Fonts\malgunbd.ttf"],
}

_cjk_missing = False


def has_cjk(text):
    if not text:
        return False
    for ch in text:
        cp = ord(ch)
        for lo, hi in _CJK_RANGES:
            if lo <= cp <= hi:
                return True
    return False


def _cjk_path(bold):
    for p in _CJK_FONTS[bool(bold)]:
        if os.path.isfile(p):
            return p
    for p in _CJK_FONTS[not bool(bold)]:
        if os.path.isfile(p):
            return p
    return None


def get_for_text(font_face, size, text):
    """跟 `get()` 一樣,但會先看這段文字需不需要 CJK 字型。"""
    global _cjk_missing
    if not has_cjk(text):
        return get(font_face, size)

    _family, weight, _style = font_face
    bold = int(weight or 400) >= 600
    size = max(1, int(round(size)))
    key = ("__cjk__", bold, size)
    if key in _font_cache:
        return _font_cache[key]

    path = _cjk_path(bold)
    if path is None:
        _cjk_missing = True
        return get(font_face, size)
    try:
        font = ImageFont.truetype(path, size)
    except OSError:
        _cjk_missing = True
        return get(font_face, size)
    _font_cache[key] = font
    return font


def cjk_unavailable():
    return _cjk_missing
