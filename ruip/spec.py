"""`.gui` 縮排 DSL —— AI 撰寫 Roblox GUI 的格式,以及它的反向(dump)。

為什麼不用 JSON/YAML:JSON 巢狀四層以後 AI 很容易漏括號,而且 diff 難看;
YAML 要多一個相依(這個專案只相依 Pillow)。縮排 DSL 只有兩種行,
parser 一百行,而且**長得像 Studio 的 Explorer**,AI 一看就懂。

    ScreenGui Shop              <- 標頭行:  <ClassName> [Name]
      ResetOnSpawn: false       <- 屬性行:  <Key>: <value>
      Frame Panel
        Size: {0.5,0}{0.6,0}
        UICorner                <- 省略 Name 時 Name = ClassName(跟 Roblox 一致)
          CornerRadius: 12px

`dump()` 是 `parse_text()` 的反向,而且**吐出來的一定是完整的**(所有非預設屬性都寫)。
這條性質是整個雕刻流程的地基:dump -> 編輯 -> apply 不會掉東西。
"""

import json
import re

from . import apidump, coerce, defaults, emit, enums, parse

HEADER = re.compile(r'^(?P<cls>[A-Za-z_][A-Za-z0-9_]*)(?:\s+(?P<name>"[^"]*"|\S.*?))?\s*$')
PROP = re.compile(r'^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<val>.*)$')


class SpecError(ValueError):
    def __init__(self, msg, line_no=None, line=None):
        self.line_no = line_no
        self.line = line
        if line_no is not None:
            msg = "第 %d 行: %s\n    %s" % (line_no, msg, line or "")
        super().__init__(msg)


# --------------------------------------------------------------------------
# 讀:.gui -> Node 樹
# --------------------------------------------------------------------------


def parse_text(text, strict=True, directives=None):
    """`.gui` 文字 -> [Node, …](頂層可以有多棵)。

    strict=True 時屬性名／型別／enum 值一律驗證(coerce 會報錯並給建議);
    strict=False 只做語法解析,值原樣留著 —— 給「先看看檔案結構」用。

    `directives` 給的話會被填入檔頭的 `# @path …` —— dump 出來的 spec 帶著
    它從哪裡來,apply 就不必再叫使用者把路徑抄一遍。
    """
    roots = []
    stack = []          # [(indent, Node)]
    lines = text.splitlines()

    for i, raw in enumerate(lines, 1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            body_c = line.lstrip()[1:].strip()
            if directives is not None and body_c.startswith("@"):
                key, _, val = body_c[1:].partition(" ")
                directives[key.strip()] = val.strip()
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise SpecError("縮排請用空白,不要用 tab", i, raw)

        indent = len(line) - len(line.lstrip())
        body = line.strip()

        while stack and stack[-1][0] >= indent:
            stack.pop()

        m = PROP.match(body)
        if m:
            if not stack:
                raise SpecError("屬性 %s 沒有所屬的物件(前面要先有一行標頭)"
                                % m.group("key"), i, raw)
            node = stack[-1][1]
            key = m.group("key")
            val = _unquote(m.group("val").strip())
            if key == "Name":
                node.name = val
                node.props["Name"] = val
                continue
            if strict:
                try:
                    node.props[key] = coerce.value(node.class_name, key, val)
                except coerce.CoerceError as exc:
                    raise SpecError(str(exc), i, raw) from None
            else:
                node.props[key] = val
            continue

        m = HEADER.match(body)
        if not m:
            raise SpecError("看不懂這行。標頭是 `ClassName 名字`,屬性是 `Key: 值`", i, raw)

        cls = m.group("cls")
        if strict and not _class_ok(cls):
            raise SpecError("沒有 %s 這個 class(或它不能被建立)" % cls, i, raw)
        name = _unquote((m.group("name") or "").strip()) or cls

        node = parse.Node(cls)
        node.name = name
        node.props["Name"] = name

        if stack:
            parent = stack[-1][1]
            node.parent = parent
            parent.children.append(node)
        else:
            roots.append(node)
        stack.append((indent, node))

    if not roots:
        raise SpecError("這個 spec 是空的")
    return roots


def _unquote(s):
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    return s


def _class_ok(cls):
    from . import apidump
    if cls in defaults.CLASS_DEFAULTS or cls in defaults.CONTAINER_CLASSES:
        return True
    if not apidump.available():
        return True                      # 沒有 dump 就不要擋人
    return apidump.class_exists(cls) and apidump.creatable(cls)


def parse_file(path, strict=True, directives=None):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.lower().endswith(".json"):
        return from_json(json.loads(text), strict=strict)
    return parse_text(text, strict=strict, directives=directives)


def from_json(data, strict=True):
    """`{"class","name","props","children"}` 的等價格式,給程式產生用。"""
    if isinstance(data, dict):
        data = [data]
    out = []
    for entry in data:
        out.append(_json_node(entry, strict))
    return out


def _json_node(entry, strict):
    cls = entry.get("class")
    if not cls:
        raise SpecError("每個節點都要有 class")
    node = parse.Node(cls)
    node.name = entry.get("name", cls)
    node.props["Name"] = node.name
    for k, v in (entry.get("props") or {}).items():
        if k == "Name":
            node.name = v
            node.props["Name"] = v
        elif strict:
            node.props[k] = coerce.value(cls, k, v)
        else:
            node.props[k] = v
    for child in entry.get("children") or []:
        c = _json_node(child, strict)
        c.parent = node
        node.children.append(c)
    return node


# --------------------------------------------------------------------------
# 寫:Node 樹 -> .gui
# --------------------------------------------------------------------------


def dump(nodes, indent=0, include_defaults=False, source_path=None):
    """Node(或一串)-> `.gui` 文字。只寫非預設屬性,除非 include_defaults。

    給了 source_path 就在檔頭寫一行 `# @path …`。這行讓 apply 知道要改回哪裡 ——
    真實 place 裡叫 `Header` 的東西可能有九個,靠名字自動比對一定會撞,
    但人也不該為此把路徑再抄一次。
    """
    if isinstance(nodes, parse.Node):
        nodes = [nodes]
    out = []
    if source_path:
        out.append("# @path " + source_path)
        out.append("")
    for n in nodes:
        _dump_node(n, indent, out, include_defaults)
    return "\n".join(out) + "\n"


def _dump_node(node, indent, out, include_defaults):
    pad = "  " * indent
    head = node.class_name
    if node.name != node.class_name:
        head += " " + (_quote(node.name) if _needs_quote(node.name) else node.name)
    if out and indent == 0:
        out.append("")
    out.append(pad + head)

    props = emit.normalize_props(node.class_name, node.props)
    props.pop("Name", None)
    # UICorner 四角相同時倒成一個 CornerRadius —— 人比較好讀,寫回去 emit 會再拆開
    props = _fold_corners(node.class_name, props)
    props = _fold_content_twins(node.class_name, props)
    if not include_defaults:
        props = emit.changed_props(node.class_name, props)
        props.pop("Name", None)
        # Studio 屬性面板看不到的東西也不要寫進 spec。最典型的是
        # DefinesCapabilities —— 每個 Item 都有,真實 place dump 出來是 440 行雜訊。
        props = {k: v for k, v in props.items()
                 if not apidump.hidden(node.class_name, k)}

    # **只倒得出讀得回來的東西。** 腳本的 Source、CFrame 這類 coerce 不處理的型別
    # 倒出去會讓 spec 讀不回來(而且 Source 動輒幾十 KB 的 base64)。
    # 沒倒出來不代表會不見 —— 預設是合併,檔案裡原本的值原封不動。
    props = {k: v for k, v in props.items()
             if coerce.type_for(node.class_name, k) is not None}

    for k in sorted(props):
        out.append("%s  %s: %s" % (pad, k, format_value(node.class_name, k, props[k])))

    for child in node.children:
        _dump_node(child, indent + 1, out, include_defaults)


def _fold_corners(class_name, props):
    if class_name != "UICorner":
        return props
    vals = [props.get(k) for k in emit.CORNER_PROPS]
    if all(v is not None for v in vals) and len({tuple(v) for v in vals}) == 1:
        out = {k: v for k, v in props.items() if k not in emit.CORNER_PROPS}
        out["CornerRadius"] = vals[0]
        return out
    return props


def _fold_content_twins(class_name, props):
    """`Image` 跟 `ImageContent` 同值時只留舊名 —— 人好讀,寫回去 emit 會再補上另一半。"""
    out = dict(props)
    for key in list(out):
        if not key.endswith("Content"):
            continue
        base = key[: -len("Content")]
        if base in out and out[base] == out[key]:
            out.pop(key)
    return out


def _needs_quote(name):
    return (not name) or name != name.strip() or re.search(r"[\s:#\"]", name) is not None


def _quote(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def format_value(class_name, prop, value):
    """值 -> 最好讀的簡寫。要求:再餵回 coerce.value() 要拿到一模一樣的東西。"""
    t = coerce.type_for(class_name, prop)

    if t == "enum" or prop in enums.PROPERTY_ENUM:
        return str(value)
    if t == "bool" or isinstance(value, bool):
        return "true" if value else "false"
    if t == "string" or isinstance(value, str):
        s = str(value)
        return _quote(s) if _needs_quote_value(s) else s
    if t == "Color3":
        return _fmt_color(value)
    if t == "Font":
        return _fmt_font(value)
    if t == "UDim2":
        return "{%s,%s}{%s,%s}" % tuple(_g(x) for x in value)
    if t == "UDim":
        return "{%s,%s}" % (_g(value[0]), _g(value[1]))
    if t in ("Vector2", "Rect"):
        return ",".join(_g(x) for x in value)
    if t == "ColorSequence":
        return ", ".join("%s %s" % (_g(t0), _fmt_color(c)) for t0, c in value)
    if t == "NumberSequence":
        return ", ".join("%s %s" % (_g(t0), _g(v)) for t0, v in value)
    if isinstance(value, (int, float)):
        return _g(value)
    if isinstance(value, tuple):
        return ",".join(_g(x) for x in value)
    return str(value)


def _needs_quote_value(s):
    return s != s.strip() or "\n" in s or s.startswith("#") or s.startswith('"')


def _g(v):
    """數字 -> 字串。**一定要能原值讀回來。**

    這裡曾經寫 `round(v, 6)`,結果 `0.0641666…` 被倒成 `0.064167`,
    再讀回來就跟原值不等 —— dump 之後什麼都沒改再 apply,會冒出一堆
    「Position 變了」的假改動,而且真的把檔案改掉。
    `repr()` 給的是**能精確 round-trip 的最短字串**,該用的是它。
    """
    if isinstance(v, float):
        if v != v:
            return "nan"
        if v in (float("inf"), float("-inf")):
            return "inf" if v > 0 else "-inf"
        if v == int(v) and abs(v) < 1e16:
            return str(int(v))
        return repr(v)
    return str(v)


def _fmt_color(c):
    """8-bit 表得準就寫 #RRGGBB(人好讀),表不準就寫浮點(不能損失精度)。"""
    ints = [int(round(x * 255)) for x in c]
    if all(0 <= i <= 255 for i in ints) and all(abs(i / 255.0 - x) < 1e-6 for i, x in zip(ints, c)):
        return "#%02X%02X%02X" % tuple(ints)
    return ",".join(_g(x) for x in c)


def _fmt_font(f):
    family, weight, style = f
    if style != "Normal":
        return "%s:%d:%s" % (family, weight, style)
    if weight != 400:
        return "%s:%d" % (family, weight)
    return str(family)
