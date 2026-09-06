"""文字排版:換行、TextScaled、RichText、對齊。

Roblox 的行框高度就是 TextSize(不是 ascent+descent),baseline 落在
行框頂 + ascent —— 所以 descender 本來就會略微溢出行框,這跟 Studio 一致。
"""

import html
import re

from . import fonts

_TAG_RE = re.compile(r"<(/?)([a-zA-Z]+)((?:\s+[^>]*)?)/?>")
_ATTR_RE = re.compile(r"([a-zA-Z]+)\s*=\s*\"([^\"]*)\"")


class Run:
    """一段樣式一致的文字。"""

    __slots__ = ("text", "bold", "italic", "color", "size", "stroke", "underline", "strike")

    def __init__(self, text, bold=False, italic=False, color=None, size=None,
                 stroke=None, underline=False, strike=False):
        self.text = text
        self.bold = bold
        self.italic = italic
        self.color = color
        self.size = size
        self.stroke = stroke
        self.underline = underline
        self.strike = strike

    def clone(self, text):
        return Run(text, self.bold, self.italic, self.color, self.size,
                   self.stroke, self.underline, self.strike)


def _parse_color(value):
    value = value.strip()
    m = re.match(r"^#([0-9a-fA-F]{6})$", value)
    if m:
        v = int(m.group(1), 16)
        return ((v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255)
    m = re.match(r"^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$", value)
    if m:
        return tuple(int(m.group(i)) / 255 for i in (1, 2, 3))
    named = {
        "red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1),
        "white": (1, 1, 1), "black": (0, 0, 0), "yellow": (1, 1, 0),
        "cyan": (0, 1, 1), "magenta": (1, 0, 1), "gray": (.5, .5, .5),
        "grey": (.5, .5, .5), "orange": (1, .65, 0), "purple": (.5, 0, .5),
    }
    return named.get(value.lower())


def parse_rich(source):
    """RichText -> [Run]。不支援的標籤直接剝掉(跟 Roblox 對未知標籤的處理一致)。"""
    runs = []
    stack = [{"bold": False, "italic": False, "color": None, "size": None,
              "stroke": None, "underline": False, "strike": False}]
    pos = 0
    buf = []

    def flush():
        if buf:
            s = stack[-1]
            runs.append(Run(html.unescape("".join(buf)), s["bold"], s["italic"],
                            s["color"], s["size"], s["stroke"],
                            s["underline"], s["strike"]))
            buf.clear()

    for m in _TAG_RE.finditer(source):
        buf.append(source[pos:m.start()])
        pos = m.end()
        closing, tag, attrs = m.group(1) == "/", m.group(2).lower(), m.group(3)
        raw = m.group(0)

        if tag == "br":
            flush()
            runs.append(Run("\n"))
            continue
        if tag not in ("b", "i", "u", "s", "font", "stroke", "uc", "sc"):
            continue

        flush()
        if closing:
            if len(stack) > 1:
                stack.pop()
            continue
        # 自閉合標籤(<font color="#fff"/>)不推堆疊
        state = dict(stack[-1])
        if tag == "b":
            state["bold"] = True
        elif tag == "i":
            state["italic"] = True
        elif tag == "u":
            state["underline"] = True
        elif tag == "s":
            state["strike"] = True
        elif tag == "font":
            for k, v in _ATTR_RE.findall(attrs):
                k = k.lower()
                if k == "color":
                    c = _parse_color(v)
                    if c:
                        state["color"] = c
                elif k == "size":
                    try:
                        state["size"] = float(v)
                    except ValueError:
                        pass
        elif tag == "stroke":
            color, thickness = (0, 0, 0), 1.0
            for k, v in _ATTR_RE.findall(attrs):
                if k.lower() == "color":
                    color = _parse_color(v) or color
                elif k.lower() == "thickness":
                    try:
                        thickness = float(v)
                    except ValueError:
                        pass
            state["stroke"] = (color, thickness)
        if raw.endswith("/>"):
            runs_before = len(runs)
            del runs_before
            continue
        stack.append(state)

    buf.append(source[pos:])
    flush()
    return [r for r in runs if r.text != ""]


def _font_for(run, base_face, base_size):
    family, weight, style = base_face
    if run.bold:
        weight = max(weight, 700)
    if run.italic:
        style = "Italic"
    size = run.size if run.size else base_size
    # 走 get_for_text 而不是 get:Roblox 內建字型沒有中日韓字符,
    # 直接量測會得到 .notdef 的寬度,畫出來是一排豆腐(見 fonts.get_for_text)。
    return fonts.get_for_text((family, weight, style), size, run.text), size


def _split_tokens(text):
    """切成 [(片段, 是否可在此後換行)] —— 空白後可換行,CJK 每字後可換行。"""
    out = []
    buf = ""
    for ch in text:
        buf += ch
        if ch == " " or ch == "\t" or ch == "-":
            out.append(buf)
            buf = ""
        elif "⺀" <= ch <= "鿿" or "가" <= ch <= "퟿" or "＀" <= ch <= "￯":
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


class Line:
    __slots__ = ("pieces", "width")

    def __init__(self):
        self.pieces = []  # [(Run, str, PIL font, advance)]
        self.width = 0.0


def layout(runs, base_face, base_size, max_width, wrapped, line_height=1.0,
           max_graphemes=-1):
    """把 runs 排成行。回傳 (lines, width, height)。"""
    lines = [Line()]
    used = 0

    def cur():
        return lines[-1]

    def newline():
        lines.append(Line())

    def push(run, piece, font):
        adv = font.getlength(piece)
        cur().pieces.append((run, piece, font, adv))
        cur().width += adv

    for run in runs:
        font, _sz = _font_for(run, base_face, base_size)
        segments = run.text.split("\n")
        for si, seg in enumerate(segments):
            if si > 0:
                newline()
            if not seg:
                continue
            if max_graphemes >= 0:
                room = max_graphemes - used
                if room <= 0:
                    seg = ""
                elif len(seg) > room:
                    seg = seg[:room]
                used += len(seg)
                if not seg:
                    continue
            if not wrapped:
                push(run, seg, font)
                continue
            for token in _split_tokens(seg):
                adv = font.getlength(token)
                if cur().width + adv <= max_width or not cur().pieces:
                    # 單一 token 就超寬 -> 硬切
                    if adv > max_width and not cur().pieces:
                        acc = ""
                        for ch in token:
                            if font.getlength(acc + ch) > max_width and acc:
                                push(run, acc, font)
                                newline()
                                acc = ch
                            else:
                                acc += ch
                        if acc:
                            push(run, acc, font)
                        continue
                    push(run, token, font)
                else:
                    newline()
                    stripped = token.lstrip(" ")
                    if stripped:
                        push(run, stripped, font)

    width = max((ln.width for ln in lines), default=0.0)
    height = len(lines) * base_size * line_height
    return lines, width, height


def measure(runs, base_face, base_size, max_width, wrapped, line_height=1.0,
            max_graphemes=-1):
    _lines, w, h = layout(runs, base_face, base_size, max_width, wrapped,
                          line_height, max_graphemes)
    return w, h


def fit_scaled(runs, base_face, box_w, box_h, wrapped, line_height=1.0,
               min_size=1, max_size=100, max_graphemes=-1):
    """TextScaled:二分搜尋最大的、排得進 box 的 TextSize。"""
    lo, hi = int(min_size), int(max_size)
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        w, h = measure(runs, base_face, mid, box_w, wrapped, line_height, max_graphemes)
        if w <= box_w + 0.5 and h <= box_h + 0.5:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def runs_from(node_text, rich):
    if rich:
        return parse_rich(node_text)
    return [Run(t) for t in [node_text]] if node_text else []
