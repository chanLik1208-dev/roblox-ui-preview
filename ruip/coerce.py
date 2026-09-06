"""把人(或 AI)寫的字串,變成 parse.py 那套內部值表示法。

雕刻工具的人機介面全部經過這裡。設計原則只有一條:
**AI 寫錯的時候要當場報錯,而且要說出正確寫法** —— 靜默忽略一個打錯的屬性名,
比報錯難查十倍(改完渲染出來一模一樣,然後開始懷疑人生)。

型別從「class + 屬性名」推得,兩層來源:
  1. `defaults.py` —— 手工表,值的表示法保證跟 parse.py 一致,涵蓋 GUI 渲染會用到的。
  2. `apidump.py` —— 4020 個屬性全在,補上 defaults 沒收的(ResetOnSpawn、Modal…)。
兩層都查不到 = 這個 class 沒有這個屬性,報錯並列出相近的名字。
"""

import re

from . import apidump, defaults, enums

# defaults.py 的值長什麼樣 -> 是什麼型別。用值的形狀反推,省一張表。
_TUPLE_TYPE = {2: "UDim", 4: "UDim2"}

# 屬性名 -> 型別,給「值的形狀推不出來」的情況(2/4-tuple 撞型別)。
NAME_TYPE_HINTS = {
    "AnchorPoint": "Vector2",
    "ImageRectOffset": "Vector2",
    "ImageRectSize": "Vector2",
    "MinSize": "Vector2",
    "MaxSize": "Vector2",
    "Offset": "Vector2",
    "CanvasPosition": "Vector2",
    "SliceCenter": "Rect",
    "CanvasSize": "UDim2",
    "FontFace": "Font",
    "Image": "Content",
    "Text": "string",
    "Name": "string",
}

NAMED_COLORS = {
    "white": (1.0, 1.0, 1.0),
    "black": (0.0, 0.0, 0.0),
    "red": (1.0, 0.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
    "yellow": (1.0, 1.0, 0.0),
    "cyan": (0.0, 1.0, 1.0),
    "magenta": (1.0, 0.0, 1.0),
    "gray": (0.5, 0.5, 0.5),
    "grey": (0.5, 0.5, 0.5),
}

FONT_WEIGHT_NAMES = {
    "thin": 100, "extralight": 200, "light": 300, "regular": 400, "normal": 400,
    "medium": 500, "semibold": 600, "bold": 700, "extrabold": 800, "heavy": 900,
}

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
_BRACE_PAIR = re.compile(r"^\{\s*(%s)\s*,\s*(%s)\s*\}$" % (_NUM, _NUM))
_BRACE_QUAD = re.compile(
    r"^\{\s*(%s)\s*,\s*(%s)\s*\}\s*\{\s*(%s)\s*,\s*(%s)\s*\}$" % (_NUM, _NUM, _NUM, _NUM)
)
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$|^#?([0-9a-fA-F]{3})$")
_RGB = re.compile(r"^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$", re.I)
_PX = re.compile(r"^(%s)\s*px$" % _NUM, re.I)
_PCT = re.compile(r"^(%s)\s*%%$" % _NUM)


class CoerceError(ValueError):
    """訊息本身就是給 AI 看的修正建議,不要只寫「型別錯誤」。"""


# --------------------------------------------------------------------------
# 型別判定
# --------------------------------------------------------------------------


def type_for(class_name, prop_name):
    """(class, 屬性名) -> 內部型別名。查不到回 None。

    **API dump 優先**,因為只有它知道 class。同一個屬性名在不同 class 可以是
    不同型別:`ScrollingFrame.CanvasSize` 是 UDim2,`SurfaceGui.CanvasSize` 是
    Vector2 —— 靠名字猜必錯一半。dump 不在時才退回下面兩層。

    enum 一律回 "enum";呼叫端去 enums.PROPERTY_ENUM 拿合法值表。
    """
    api = apidump.type_of(class_name, prop_name)
    if isinstance(api, tuple):          # ("enum", "FillDirection")
        return "enum"
    if api:
        return api

    if prop_name in enums.PROPERTY_ENUM:
        return "enum"
    if prop_name in NAME_TYPE_HINTS:
        return NAME_TYPE_HINTS[prop_name]

    d = defaults.defaults_for(class_name)
    if prop_name in d:
        return _type_of_value(d[prop_name])
    return None


def _type_of_value(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if isinstance(v, tuple):
        if len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
            return "Color3"
        if len(v) == 3:
            return "Font"
        return _TUPLE_TYPE.get(len(v))
    if isinstance(v, list):
        if v and isinstance(v[0], tuple) and len(v[0]) == 2:
            return "ColorSequence" if isinstance(v[0][1], tuple) else "NumberSequence"
    return None


def known_property(class_name, prop_name):
    if prop_name == "Name":
        return True
    if prop_name in defaults.defaults_for(class_name):
        return True
    return apidump.find_property(class_name, prop_name) is not None


def suggest(class_name, prop_name, limit=5):
    """打錯屬性名時挑出長得像的。

    要處理的是兩種真實的打錯法:漏字(TxtSize)與拼錯(BackgroudColor3)。
    漏字用「是不是子序列」抓,拼錯用字元交集抓,再用長度差把
    MouseWheelBackwardConnectionCount 這種剛好共用很多字母的長名字壓下去。
    """
    cands = set(defaults.defaults_for(class_name)) | set(apidump.properties_of(class_name))
    if not cands:
        return []
    target = prop_name.lower()

    def score(c):
        cl = c.lower()
        if cl == target:
            return 999
        common = len(set(cl) & set(target))
        prefix = len(_common_prefix(cl, target))
        sub = 5 if (target in cl or cl in target) else 0
        seq = 5 if (_is_subseq(target, cl) or _is_subseq(cl, target)) else 0
        penalty = abs(len(cl) - len(target)) * 0.7
        return common + prefix * 2 + sub + seq - penalty

    ranked = sorted(cands, key=score, reverse=True)
    return [c for c in ranked[:limit] if score(c) > 6]


def _is_subseq(short, long_):
    it = iter(long_)
    return all(ch in it for ch in short)


def _common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return a[:n]


# --------------------------------------------------------------------------
# 值解析
# --------------------------------------------------------------------------


def value(class_name, prop_name, raw):
    """主要入口:raw(字串或原生型別)-> 內部表示法。"""
    if not known_property(class_name, prop_name):
        tips = suggest(class_name, prop_name)
        hint = ("  你是不是要寫:" + "、".join(tips)) if tips else ""
        raise CoerceError("%s 沒有 %s 這個屬性。%s" % (class_name, prop_name, hint))

    if not apidump.writable(class_name, prop_name):
        raise CoerceError("%s.%s 是唯讀的,寫不進檔案。" % (class_name, prop_name))

    t = type_for(class_name, prop_name)
    if t is None:
        # dump 認得這個屬性,但它是 CFrame / Ref / 物件參照這種 GUI 用不到的型別
        raise CoerceError(
            "%s.%s 的型別這個工具還不支援(只處理 GUI 用得到的型別)。"
            % (class_name, prop_name)
        )

    try:
        return _convert(t, prop_name, raw)
    except CoerceError:
        raise
    except (ValueError, TypeError, AttributeError) as exc:
        raise CoerceError(
            "%s.%s 需要 %s,但 %r 解不出來。%s"
            % (class_name, prop_name, t, raw, _syntax_hint(t))
        ) from exc


def _syntax_hint(t):
    return {
        "UDim2": "  寫法:{0.5,10}{0,100} 或 0.5,10,0,100 或 100px 或 50%",
        "UDim": "  寫法:{0,8} 或 8px 或 50%",
        "Vector2": "  寫法:0.5,0.5",
        "Color3": "  寫法:#1E1E28 或 rgb(30,30,40) 或 0.1,0.1,0.16 或 white",
        "Rect": "  寫法:x0,y0,x1,y1",
        "Font": "  寫法:BuilderSans 或 BuilderSans:700 或 BuilderSans:700:Italic",
        "bool": "  寫法:true / false",
    }.get(t, "")


def _convert(t, prop_name, raw):
    fn = _CONVERTERS.get(t)
    if fn is None:
        raise CoerceError("內部錯誤:沒有 %s 的轉換器" % t)
    return fn(prop_name, raw)


def _nums(s, want=None):
    parts = [p for p in re.split(r"[,\s]+", s.strip().strip("{}")) if p]
    vals = [float(p) for p in parts]
    if want is not None and len(vals) != want:
        raise ValueError("要 %d 個數字,給了 %d" % (want, len(vals)))
    return vals


def _to_udim2(_prop, raw):
    if isinstance(raw, (tuple, list)):
        v = [float(x) for x in raw]
        if len(v) != 4:
            raise ValueError("UDim2 要 4 個數字")
        return tuple(v)
    s = str(raw).strip()
    m = _BRACE_QUAD.match(s)
    if m:
        return tuple(float(g) for g in m.groups())
    m = _PX.match(s)
    if m:
        n = float(m.group(1))
        return (0.0, n, 0.0, n)
    m = _PCT.match(s)
    if m:
        n = float(m.group(1)) / 100.0
        return (n, 0.0, n, 0.0)
    return tuple(_nums(s, 4))


def _to_udim(_prop, raw):
    if isinstance(raw, (tuple, list)):
        v = [float(x) for x in raw]
        if len(v) != 2:
            raise ValueError("UDim 要 2 個數字")
        return tuple(v)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return (0.0, float(raw))       # 純數字 = offset,最常見的意圖
    s = str(raw).strip()
    m = _BRACE_PAIR.match(s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = _PX.match(s)
    if m:
        return (0.0, float(m.group(1)))
    m = _PCT.match(s)
    if m:
        return (float(m.group(1)) / 100.0, 0.0)
    v = _nums(s)
    if len(v) == 1:
        return (0.0, v[0])
    if len(v) == 2:
        return (v[0], v[1])
    raise ValueError("UDim 要 1~2 個數字")


def _to_vector2(_prop, raw):
    if isinstance(raw, (tuple, list)):
        v = [float(x) for x in raw]
        if len(v) != 2:
            raise ValueError("Vector2 要 2 個數字")
        return tuple(v)
    return tuple(_nums(str(raw), 2))


def _to_color3(_prop, raw):
    if isinstance(raw, (tuple, list)):
        v = [float(x) for x in raw]
        if len(v) != 3:
            raise ValueError("Color3 要 3 個數字")
        if any(x > 1.0 for x in v):     # 0..255 寫法自動降到 0..1
            v = [x / 255.0 for x in v]
        return tuple(v)
    s = str(raw).strip()
    low = s.lower()
    if low in NAMED_COLORS:
        return NAMED_COLORS[low]
    m = _RGB.match(s)
    if m:
        return tuple(int(g) / 255.0 for g in m.groups())
    m = _HEX.match(s)
    if m:
        h = m.group(1) or m.group(2)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    v = _nums(s, 3)
    if any(x > 1.0 for x in v):
        v = [x / 255.0 for x in v]
    return tuple(v)


def _to_rect(_prop, raw):
    if isinstance(raw, (tuple, list)):
        return tuple(float(x) for x in raw)
    return tuple(_nums(str(raw), 4))


def _to_font(_prop, raw):
    """family[:weight][:style] —— weight 吃數字也吃名字。"""
    if isinstance(raw, (tuple, list)) and len(raw) == 3:
        return (str(raw[0]), int(raw[1]), str(raw[2]))
    parts = [p.strip() for p in str(raw).split(":")]
    family = parts[0] or "SourceSansPro"
    weight, style = 400, "Normal"
    for p in parts[1:]:
        pl = p.lower()
        if pl in ("italic", "oblique"):
            style = "Italic"
        elif pl == "normal":
            style = "Normal"
        elif pl in FONT_WEIGHT_NAMES:
            weight = FONT_WEIGHT_NAMES[pl]
        else:
            weight = int(float(p))
    return (family, weight, style)


def _to_bool(_prop, raw):
    if isinstance(raw, bool):
        return raw
    s = str(raw).strip().lower()
    if s in ("true", "yes", "on", "1"):
        return True
    if s in ("false", "no", "off", "0"):
        return False
    raise ValueError("不是 true/false")


def _to_int(_prop, raw):
    if isinstance(raw, bool):
        return int(raw)
    return int(float(raw))


def _to_float(_prop, raw):
    return float(raw)


def _to_string(_prop, raw):
    return raw if isinstance(raw, str) else str(raw)


def _to_content(_prop, raw):
    s = str(raw).strip()
    if s.isdigit():                     # 只給數字 = asset id
        return "rbxassetid://" + s
    return s


def _to_enum(prop, raw):
    table = enums.PROPERTY_ENUM.get(prop)
    if table is None:
        # `enums.py` 只收渲染會用到的 enum,不可能收全(RollOffMode、
        # ElasticBehavior、ResampleMode…)。沒有對照表時**保持整數**原樣 ——
        # 轉成字串的話 dump 出來再讀回就不等於原值,會冒出一堆假改動。
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        s = str(raw).strip()
        return int(s) if s.lstrip("-").isdigit() else s
    names = list(table.values())
    if isinstance(raw, int) and not isinstance(raw, bool):
        if raw in table:
            return table[raw]
        raise CoerceError("%s 沒有 token %d。合法值:%s" % (prop, raw, "、".join(names)))
    s = str(raw).strip()
    if s.startswith("Enum."):            # 容忍 Enum.FillDirection.Vertical 寫法
        s = s.rsplit(".", 1)[-1]
    for n in names:
        if n.lower() == s.lower():
            return n
    if s.isdigit() and int(s) in table:
        return table[int(s)]
    raise CoerceError("%s 沒有 %r 這個值。合法值:%s" % (prop, s, "、".join(names)))


def _sequence_conv(kind):
    def conv(_prop, raw):
        if isinstance(raw, list):
            return raw
        # "0 #FFFFFF, 1 #000000"(色) / "0 0, 1 1"(數)
        out = []
        for chunk in str(raw).split(","):
            parts = chunk.split()
            if len(parts) < 2:
                raise ValueError("每段要有 時間 + 值")
            t = float(parts[0])
            if kind == "color":
                out.append((t, _to_color3(None, parts[1])))
            else:
                out.append((t, float(parts[1])))
        return out
    return conv


_CONVERTERS = {
    "UDim2": _to_udim2,
    "UDim": _to_udim,
    "Vector2": _to_vector2,
    "Color3": _to_color3,
    "Rect": _to_rect,
    "Font": _to_font,
    "bool": _to_bool,
    "int": _to_int,
    "float": _to_float,
    "string": _to_string,
    "Content": _to_content,
    "enum": _to_enum,
    "ColorSequence": _sequence_conv("color"),
    "NumberSequence": _sequence_conv("number"),
}
