"""內部樹 -> Roblox XML。`parse.parse_value()` 的鏡像。

兩件事一定要做對,不然產出的檔案 Studio 開得起來但長得不對:

1. **差異序列化。** Roblox 只寫「跟預設值不同」的屬性。全部照寫不會壞,但檔案會腫,
   而且 diff 起來看不出人到底改了什麼。這裡沿用 `defaults.defaults_for()` 那張表當基準。

2. **圓角是四個角。** 現代 Roblox 序列化的是 `TopLeftRadius`/`TopRightRadius`/
   `BottomLeftRadius`/`BottomRightRadius`,不是 `CornerRadius`
   (後者在 API dump 0.734 已是 `CanSave:false` 的 legacy 別名)。
   寫 `CornerRadius` 的檔案 Studio 讀得進去,但存檔後會被四角取代 —— 我們直接寫四角,
   讓來回一趟是穩定的。
"""

import re
import xml.etree.ElementTree as ET

from . import defaults, enums

XML_DECL = '<?xml version="1.0" encoding="utf-8"?>\n'
ROOT_OPEN = (
    '<roblox xmlns:xmime="http://www.w3.org/2005/05/xmlmime" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="http://www.roblox.com/roblox.xsd" version="4">'
)
ROOT_CLOSE = "</roblox>"

# UICorner.CornerRadius 是 legacy 別名,實際存檔的是這四個。
CORNER_PROPS = ("TopLeftRadius", "TopRightRadius", "BottomLeftRadius", "BottomRightRadius")

# 屬性名 -> 用哪個 XML tag。查不到就照值的型別猜(見 _tag_for_value)。
TAG_OVERRIDE = {
    "Name": "string",
    "Text": "string",
    "PlaceholderText": "string",
    "Image": "Content",
    "ImageContent": "Content",
    "Texture": "Content",
    "Video": "Content",
    "FontFace": "Font",
    "AnchorPoint": "Vector2",
    "ImageRectOffset": "Vector2",
    "ImageRectSize": "Vector2",
    "MinSize": "Vector2",
    "MaxSize": "Vector2",
    "Offset": "Vector2",
    "CanvasPosition": "Vector2",
    "SliceCenter": "Rect2D",
    "ZIndex": "int",
    "DisplayOrder": "int",
    "LayoutOrder": "int",
    "BorderSizePixel": "int",
    "FillDirectionMaxCells": "int",
    "MaxVisibleGraphemes": "int",
    "MinTextSize": "int",
    "MaxTextSize": "int",
}

# 這些屬性用 Color3uint8 序列化(Roblox 對 BackgroundColor3 這類就是這樣寫的)
COLOR_UINT8 = {
    "BackgroundColor3", "BorderColor3", "TextColor3", "TextStrokeColor3",
    "ImageColor3", "PlaceholderColor3", "ScrollBarImageColor3",
}

_INVALID_XML = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f]"      # XML 1.0 不允許的控制字元
)


class EmitError(ValueError):
    pass


# --------------------------------------------------------------------------
# 值 -> XML
# --------------------------------------------------------------------------


def _esc(text):
    """屬性文字進 XML。`&`、`<`、`>` 一定要跳脫 —— `Text: 血量 < 20%` 會直接毀掉檔案。"""
    if not isinstance(text, str):
        text = str(text)
    text = _INVALID_XML.sub("", text)
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _num(v):
    """浮點數盡量短。1.0 -> 1,不要寫成 1.0 —— 跟 rbx_xml 的輸出一致。"""
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        return "INF" if f > 0 else "-INF"
    if f == int(f) and abs(f) < 1e16:
        return str(int(f))
    return repr(f)


def _tag_for_value(prop, value):
    if prop in TAG_OVERRIDE:
        return TAG_OVERRIDE[prop]
    if prop in enums.PROPERTY_ENUM:
        return "token"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, tuple):
        if len(value) == 2:
            return "UDim"
        if len(value) == 4:
            return "UDim2"
        if len(value) == 3:
            if all(isinstance(x, (int, float)) for x in value):
                return "Color3uint8" if prop in COLOR_UINT8 else "Color3"
            return "Font"
    if isinstance(value, list):
        if value and isinstance(value[0], tuple):
            return "ColorSequence" if isinstance(value[0][1], tuple) else "NumberSequence"
    raise EmitError("不知道 %s=%r 該用哪個 XML 標籤" % (prop, value))


def prop_xml(prop, value):
    """一個屬性 -> 一段 XML。回 None 代表這個屬性不寫。"""
    tag = _tag_for_value(prop, value)

    if tag == "token":
        table = enums.PROPERTY_ENUM.get(prop, {})
        rev = {v: k for k, v in table.items()}
        if isinstance(value, str):
            if value not in rev:
                raise EmitError("%s 沒有 %r 這個 enum 值" % (prop, value))
            value = rev[value]
        return '<token name="%s">%d</token>' % (prop, int(value))

    if tag == "bool":
        return '<bool name="%s">%s</bool>' % (prop, "true" if value else "false")
    if tag == "int":
        return '<int name="%s">%d</int>' % (prop, int(value))
    if tag == "float":
        return '<float name="%s">%s</float>' % (prop, _num(value))
    if tag == "string":
        return '<string name="%s">%s</string>' % (prop, _esc(value))
    if tag == "ProtectedString":
        return '<ProtectedString name="%s">%s</ProtectedString>' % (prop, _esc(value))
    if tag == "Content":
        # 空字串要寫 <null/>,不然 Studio 會當成沒設過
        if not value:
            return '<Content name="%s"><null></null></Content>' % prop
        return '<Content name="%s"><url>%s</url></Content>' % (prop, _esc(value))
    if tag == "UDim":
        return '<UDim name="%s"><S>%s</S><O>%s</O></UDim>' % (
            prop, _num(value[0]), _num(value[1]))
    if tag == "UDim2":
        return ('<UDim2 name="%s"><XS>%s</XS><XO>%s</XO><YS>%s</YS><YO>%s</YO></UDim2>'
                % (prop, _num(value[0]), _num(value[1]), _num(value[2]), _num(value[3])))
    if tag == "Vector2":
        return '<Vector2 name="%s"><X>%s</X><Y>%s</Y></Vector2>' % (
            prop, _num(value[0]), _num(value[1]))
    if tag == "Color3":
        return ('<Color3 name="%s"><R>%s</R><G>%s</G><B>%s</B></Color3>'
                % (prop, _num(value[0]), _num(value[1]), _num(value[2])))
    if tag == "Color3uint8":
        packed = (0xFF << 24) | (_u8(value[0]) << 16) | (_u8(value[1]) << 8) | _u8(value[2])
        return '<Color3uint8 name="%s">%d</Color3uint8>' % (prop, packed)
    if tag in ("Rect2D", "Rect"):
        return ('<Rect2D name="%s"><min><X>%s</X><Y>%s</Y></min>'
                '<max><X>%s</X><Y>%s</Y></max></Rect2D>'
                % (prop, _num(value[0]), _num(value[1]), _num(value[2]), _num(value[3])))
    if tag == "Font":
        family, weight, style = value
        url = family if family.startswith("rbx") else (
            "rbxasset://fonts/families/%s.json" % family)
        return ('<Font name="%s"><Family><url>%s</url></Family>'
                '<Weight>%d</Weight><Style>%s</Style><CachedFaceId><null></null>'
                '</CachedFaceId></Font>' % (prop, _esc(url), int(weight), _esc(style)))
    if tag == "ColorSequence":
        flat = []
        for t, c in value:
            flat += [_num(t), _num(c[0]), _num(c[1]), _num(c[2]), "0"]
        return '<ColorSequence name="%s">%s </ColorSequence>' % (prop, " ".join(flat))
    if tag == "NumberSequence":
        flat = []
        for t, v in value:
            flat += [_num(t), _num(v), "0"]
        return '<NumberSequence name="%s">%s </NumberSequence>' % (prop, " ".join(flat))

    raise EmitError("沒有 %s 標籤的寫出器" % tag)


def _u8(v):
    return max(0, min(255, int(round(float(v) * 255))))


# --------------------------------------------------------------------------
# 節點 -> XML
# --------------------------------------------------------------------------


def changed_props(class_name, props):
    """濾掉跟預設值相同的屬性。Name 永遠寫(它是路徑,不是外觀)。"""
    base = defaults.defaults_for(class_name)
    out = {}
    for k, v in props.items():
        if k == "Name":
            out[k] = v
            continue
        if k in base and values_equal(base[k], v):
            continue
        out[k] = v
    return out


# Roblox 內部用 float32 存所有數值。`<Color3>` 裡的 0.2352941334247589 其實就是
# float32(60/255),跟 double 的 0.23529411764705882 差 3.6e-8 —— 用 == 比會判成
# 「這個屬性改了」,於是 dump 出來原封不動再 apply 也會冒出一堆假改動,
# 而且真的把檔案改掉。float32 大約 7 位有效數字,1e-6 夠寬也夠嚴
# (真的改一階色是 1/255 ≈ 0.0039,差三個數量級)。
FLOAT_TOL = 1e-6


def values_equal(a, b, tol=FLOAT_TOL):
    """兩個屬性值算不算「一樣」。數值走容差,其餘走 ==。"""
    if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
        if len(a) != len(b):
            return False
        return all(values_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= tol
    return a == b


_same = values_equal          # 舊名字,內部還有人用


def normalize_props(class_name, props):
    """寫出前的正規化 —— 把「人寫的寫法」轉成「Roblox 實際序列化的寫法」。

    1. `CornerRadius` -> 四個角(現代 Roblox 存的是四角,前者是 legacy 別名)
    2. `Image` <-> `ImageContent` 成對同步(新舊並存,只改一邊檔案會自相矛盾)
    """
    from . import apidump

    out = dict(props)
    if class_name == "UICorner" and "CornerRadius" in out:
        r = out.pop("CornerRadius")
        for p in CORNER_PROPS:
            out.setdefault(p, r)

    for key in list(out):
        twin = apidump.content_twin(class_name, key)
        if twin and twin not in props:
            out[twin] = out[key]
    return out


def node_xml(node, ref_alloc, indent=0, pretty=True):
    """一個節點(含後代)-> XML 字串。

    ref_alloc() 每次回一個沒被用過的 referent 字串。
    """
    pad = "  " * indent if pretty else ""
    nl = "\n" if pretty else ""
    cls = node.class_name

    props = normalize_props(cls, node.props)
    props.setdefault("Name", node.name)
    props = changed_props(cls, props)

    # Name 排第一,其餘照字母序 —— 產出穩定,diff 才有意義
    keys = ["Name"] + sorted(k for k in props if k != "Name")

    # 配到的號寫回節點 —— 剛插進去的東西後面才能被 reorder / 再次修改定址到
    ref = ref_alloc()
    try:
        node.referent = ref
    except AttributeError:                  # 不是 parse.Node 也沒關係
        pass

    parts = ["%s<Item class=\"%s\" referent=\"%s\">%s" % (pad, cls, ref, nl)]
    parts.append("%s  <Properties>%s" % (pad, nl))
    for k in keys:
        try:
            frag = prop_xml(k, props[k])
        except EmitError:
            raise
        if frag:
            parts.append("%s    %s%s" % (pad, frag, nl))
    parts.append("%s  </Properties>%s" % (pad, nl))
    for child in node.children:
        parts.append(node_xml(child, ref_alloc, indent + 1, pretty))
    parts.append("%s</Item>%s" % (pad, nl))
    return "".join(parts)


def document_xml(nodes, ref_alloc=None, pretty=True):
    """一棵或多棵樹 -> 完整的 .rbxlx/.rbxmx 檔內容。"""
    alloc = ref_alloc or make_ref_alloc()
    body = "".join(node_xml(n, alloc, 1, pretty) for n in nodes)
    nl = "\n" if pretty else ""
    return XML_DECL + ROOT_OPEN + nl + body + ROOT_CLOSE + nl


def make_ref_alloc(taken=None, prefix="RUIS"):
    """referent 配號器。避開已存在的號碼 —— 撞號會讓 Ref 屬性指到錯的物件。"""
    used = set(taken or ())
    counter = [0]

    def alloc():
        while True:
            counter[0] += 1
            cand = "%s%d" % (prefix, counter[0])
            if cand not in used:
                used.add(cand)
                return cand
    return alloc


def parse_fragment(xml_text):
    """把 emit 出來的片段讀回 ElementTree,給 splice 用。"""
    return ET.fromstring(xml_text)
