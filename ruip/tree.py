"""文字版 layout 樹 —— 給 agent 讀的另一半。

圖能看出「長什麼樣」,但看不出「為什麼」。這裡把算完的絕對座標、顏色、
文字內容、以及 Visible=false 這種一眼看不出來的狀態列成表,
讓 agent 不必猜就能改對屬性。
"""

import json

from . import defaults


def _hex(c):
    if not c:
        return "-"
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(round(v * 255)))) for v in c[:3])


def _pct(t):
    return f"{int(round(float(t or 0) * 100))}%"


def _udim2_str(u):
    return f"{{{u[0]:g},{u[1]:g}}},{{{u[2]:g},{u[3]:g}}}"


def describe(box):
    """一個元素的重點屬性,壓成一行。"""
    node = box.node
    cls = node.class_name
    bits = [f"({box.x:.0f},{box.y:.0f} {box.w:.0f}x{box.h:.0f})"]

    if box.hidden_by == "self":
        bits.append("!VISIBLE=false")
    elif box.hidden_by == "ancestor":
        bits.append("!父層隱藏")
    elif box.invisible:
        bits.append("!" + box.invisible)

    bg_t = float(node.get("BackgroundTransparency", 0.0) or 0.0)
    if cls in defaults.GUI_OBJECT_CLASSES:
        if bg_t < 1.0:
            bits.append(f"bg={_hex(node.get('BackgroundColor3'))}"
                        + (f"/{_pct(bg_t)}透" if bg_t > 0 else ""))
        else:
            bits.append("bg=透明")

    if cls in defaults.TEXT_CLASSES:
        raw = node.get("Text", "") or ""
        shown = raw if len(raw) <= 40 else raw[:37] + "…"
        bits.append(f'text="{shown}"')
        bits.append(f"{box.text_size:g}px" if box.text_size else "")
        bits.append(f"{node.get('TextXAlignment')}/{node.get('TextYAlignment')}")
        bits.append(_hex(node.get("TextColor3")))
        tt = float(node.get("TextTransparency", 0.0) or 0.0)
        if tt > 0:
            bits.append(f"文字{_pct(tt)}透")
        if node.get("TextScaled"):
            bits.append("Scaled")
        if node.get("TextWrapped"):
            bits.append("Wrapped")
        if node.get("RichText"):
            bits.append("RichText")
        face = node.get("FontFace")
        if face:
            bits.append(f"{face[0]}@{face[1]}")

    if cls in defaults.IMAGE_CLASSES:
        img = node.get("Image", "") or ""
        bits.append(f"img={img or '(空)'}")
        st = node.get("ScaleType", "Stretch")
        if st != "Stretch":
            bits.append(st)
        it = float(node.get("ImageTransparency", 0) or 0)
        if it > 0:
            bits.append(f"{_pct(it)}透")

    if cls == "ScrollingFrame":
        bits.append(f"canvas={_udim2_str(node.get('CanvasSize'))}")

    z = node.get("ZIndex", 1)
    if z != 1:
        bits.append(f"Z={z}")
    if node.get("ClipsDescendants"):
        bits.append("Clip")
    rot = float(node.get("Rotation", 0) or 0)
    if abs(rot) > 1e-6:
        bits.append(f"rot={rot:g}°")

    mods = []
    for c in node.children:
        if c.class_name in defaults.MODIFIER_CLASSES:
            mods.append(c.class_name[2:])
    if mods:
        bits.append("+" + ",".join(sorted(set(mods))))

    return " ".join(b for b in bits if b)


def render_tree(root, boxes, max_depth=None):
    """畫成 Explorer 風格的樹。boxes 用來查每個節點算出來的座標。"""
    by_node = {id(b.node): b for b in boxes}
    lines = []

    def walk(node, prefix, is_last, depth):
        if max_depth is not None and depth > max_depth:
            return
        if depth == 0:
            head = f"{node.name} [{node.class_name}]"
        else:
            head = prefix + ("└── " if is_last else "├── ") + \
                f"{node.name} [{node.class_name}]"
        box = by_node.get(id(node))
        if box is not None:
            head += "  " + describe(box)
        elif node.class_name in defaults.MODIFIER_CLASSES:
            head += "  " + _modifier_desc(node)
        lines.append(head)

        kids = [c for c in node.children
                if defaults.is_renderable(c.class_name)
                or c.class_name in defaults.MODIFIER_CLASSES]
        child_prefix = prefix + ("    " if is_last else "│   ") if depth else ""
        for i, c in enumerate(kids):
            walk(c, child_prefix, i == len(kids) - 1, depth + 1)

    walk(root, "", True, 0)
    return "\n".join(lines)


def _modifier_desc(node):
    cls = node.class_name
    if cls == "UICorner":
        # 四角優先 —— 現代 Roblox 寫的是它們,不是 CornerRadius(見 layout._corner_radius)
        corners = [node.props[k] for k in
                   ("TopLeftRadius", "TopRightRadius", "BottomLeftRadius", "BottomRightRadius")
                   if k in node.props]
        if corners and len({tuple(c) for c in corners}) > 1:
            return "radius=" + "/".join(f"{c[0]:g}s+{c[1]:g}px" for c in corners)
        r = corners[0] if corners else node.get("CornerRadius")
        return f"radius={r[0]:g}s+{r[1]:g}px"
    if cls == "UIStroke":
        return (f"{_hex(node.get('Color'))} {node.get('Thickness'):g}px "
                f"{node.get('ApplyStrokeMode')}")
    if cls == "UIPadding":
        return " ".join(
            f"{k[7:]}={node.get(k)[0]:g}s+{node.get(k)[1]:g}px"
            for k in ("PaddingTop", "PaddingRight", "PaddingBottom", "PaddingLeft"))
    if cls == "UIListLayout":
        p = node.get("Padding")
        return (f"{node.get('FillDirection')} pad={p[0]:g}s+{p[1]:g}px "
                f"{node.get('HorizontalAlignment')}/{node.get('VerticalAlignment')} "
                f"sort={node.get('SortOrder')}")
    if cls == "UIGridLayout":
        return f"cell={_udim2_str(node.get('CellSize'))} pad={_udim2_str(node.get('CellPadding'))}"
    if cls == "UIAspectRatioConstraint":
        return f"ratio={node.get('AspectRatio'):g} {node.get('AspectType')}"
    if cls == "UIScale":
        return f"scale={node.get('Scale'):g}"
    if cls == "UITextSizeConstraint":
        return f"{node.get('MinTextSize')}..{node.get('MaxTextSize')}"
    if cls == "UIGradient":
        return f"rot={node.get('Rotation'):g}° stops={len(node.get('Color') or [])}"
    return ""


def to_json(root, boxes):
    by_node = {id(b.node): b for b in boxes}

    def conv(node):
        box = by_node.get(id(node))
        out = {"class": node.class_name, "name": node.name}
        if box is not None:
            out["rect"] = [round(box.x, 2), round(box.y, 2),
                           round(box.w, 2), round(box.h, 2)]
            out["visible"] = box.hidden_by is None
            if box.hidden_by:
                out["hiddenBy"] = box.hidden_by
            if box.text_size:
                out["textSize"] = box.text_size
        props = {}
        for k, v in sorted(node.props.items()):
            if k in ("Name", "AttributesSerialize", "Tags"):
                continue
            props[k] = v if not isinstance(v, tuple) else list(v)
        if props:
            out["props"] = props
        kids = [conv(c) for c in node.children
                if defaults.is_renderable(c.class_name)
                or c.class_name in defaults.MODIFIER_CLASSES]
        if kids:
            out["children"] = kids
        return out

    return json.dumps(conv(root), ensure_ascii=False, indent=2, default=str)
