"""把 .rbxlx / .rbxmx(以及經 rbxl-engine 轉檔的 .rbxl / .rbxm)讀成輕量 GUI 樹。

設計重點:place dump 可以到 110 MB,直接 `ET.parse` 會吃掉幾 GB。
這裡用 iterparse + 邊走邊 clear,而且**只有 GUI 相關的 class 才解析屬性**,
其餘節點只留 Name,最後再把「自己不是 GUI 又沒有 GUI 後代」的子樹剪掉。
"""

import os
import sys
import xml.etree.ElementTree as ET

from . import convert, defaults, enums

# 這些 class 要完整解析屬性;其他的只留 Name 當路徑用
DETAILED = (
    defaults.GUI_OBJECT_CLASSES
    | defaults.MODIFIER_CLASSES
    | {"ScreenGui", "SurfaceGui", "BillboardGui"}
)
# 剪枝時要保留的「本身就是 GUI」的 class
GUI_ROOTS = defaults.GUI_OBJECT_CLASSES | {"ScreenGui", "SurfaceGui", "BillboardGui"}


class Node:
    __slots__ = ("class_name", "name", "props", "children", "parent", "referent")

    def __init__(self, class_name, referent=None):
        self.class_name = class_name
        self.name = class_name  # Roblox 預設 Name == ClassName,XML 省略時要 fallback
        self.props = {}
        self.children = []
        self.parent = None
        self.referent = referent

    def get(self, key, fallback=None):
        """讀屬性,沒寫就回類別預設值。"""
        if key in self.props:
            return self.props[key]
        d = defaults.defaults_for(self.class_name)
        if key in d:
            return d[key]
        return fallback

    def find_child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None

    def children_of_class(self, class_name):
        return [c for c in self.children if c.class_name == class_name]

    def first_of_class(self, class_name):
        for c in self.children:
            if c.class_name == class_name:
                return c
        return None

    @property
    def path(self):
        parts = []
        n = self
        while n is not None and n.class_name != "__root__":
            parts.append(n.name)
            n = n.parent
        return ".".join(reversed(parts))

    def __repr__(self):
        return f"<{self.class_name} {self.name!r} {len(self.children)} children>"


# --------------------------------------------------------------------------
# 屬性值解析
# --------------------------------------------------------------------------


def _f(el, tag, default=0.0):
    sub = el.find(tag)
    if sub is None or sub.text is None:
        return default
    try:
        return float(sub.text)
    except ValueError:
        return default


def _color_from_uint32(raw):
    """Color3uint8 序列化成一個 uint32(ARGB),alpha 恆為 0xFF。"""
    v = int(raw) & 0xFFFFFF
    return ((v >> 16 & 0xFF) / 255.0, (v >> 8 & 0xFF) / 255.0, (v & 0xFF) / 255.0)


def _parse_sequence(text, stride):
    """NumberSequence(t v env) / ColorSequence(t r g b env) 都是空白分隔的平坦數列。"""
    if not text:
        return []
    nums = [float(x) for x in text.split()]
    out = []
    for i in range(0, len(nums) - stride + 1, stride):
        chunk = nums[i : i + stride]
        if stride == 3:
            out.append((chunk[0], chunk[1]))
        else:
            out.append((chunk[0], (chunk[1], chunk[2], chunk[3])))
    return out


def _content_url(el):
    for tag in ("url", "uri"):
        sub = el.find(tag)
        if sub is not None and sub.text:
            return sub.text.strip()
    if el.text and el.text.strip():
        return el.text.strip()
    return ""


def _parse_font(el):
    """<Font><Family><url>…SourceSansPro.json</url></Family><Weight>700</Weight><Style>Italic</Style></Font>"""
    family = "SourceSansPro"
    fam_el = el.find("Family")
    if fam_el is not None:
        url = _content_url(fam_el)
        if url:
            base = url.rsplit("/", 1)[-1]
            family = base[:-5] if base.endswith(".json") else base
    weight = 400
    w_el = el.find("Weight")
    if w_el is not None and w_el.text:
        try:
            weight = int(float(w_el.text))
        except ValueError:
            pass
    style = "Normal"
    s_el = el.find("Style")
    if s_el is not None and s_el.text:
        style = s_el.text.strip()
    return (family, weight, style)


def _parse_rect(el):
    """rbx_xml 寫成 <min><X/><Y/></min><max>…</max>;舊格式是扁平四個值。"""
    mn, mx = el.find("min"), el.find("max")
    if mn is not None and mx is not None:
        return (_f(mn, "X"), _f(mn, "Y"), _f(mx, "X"), _f(mx, "Y"))
    return (_f(el, "X"), _f(el, "Y"), _f(el, "X2"), _f(el, "Y2"))


def parse_value(el):
    tag = el.tag
    text = (el.text or "").strip()

    if tag == "UDim2":
        return (_f(el, "XS"), _f(el, "XO"), _f(el, "YS"), _f(el, "YO"))
    if tag == "UDim":
        return (_f(el, "S"), _f(el, "O"))
    if tag in ("Vector2", "Vector2int16"):
        return (_f(el, "X"), _f(el, "Y"))
    if tag == "Color3":
        return (_f(el, "R"), _f(el, "G"), _f(el, "B"))
    if tag == "Color3uint8":
        return _color_from_uint32(text or "0")
    if tag == "Rect" or tag == "Rect2D":
        return _parse_rect(el)
    if tag == "Font":
        return _parse_font(el)
    if tag == "Content" or tag == "ContentId":
        return _content_url(el)
    if tag == "ColorSequence":
        return _parse_sequence(text, 5)
    if tag == "NumberSequence":
        return _parse_sequence(text, 3)
    if tag == "bool":
        return text == "true"
    if tag in ("int", "int64", "token", "SecurityCapabilities"):
        try:
            return int(text)
        except ValueError:
            return 0
    if tag in ("float", "double"):
        try:
            return float(text)
        except ValueError:
            return 0.0
    if tag in ("string", "ProtectedString"):
        return el.text if el.text is not None else ""
    if tag == "Ref":
        return None if text == "null" else text
    if tag == "BinaryString":
        return None  # 屬性序列化 blob,渲染用不到
    return text


def _parse_properties(item_el, detailed):
    """解析一個 <Item> 的 <Properties>。detailed=False 時只抓 Name,省時省記憶體。"""
    props = {}
    props_el = item_el.find("Properties")
    if props_el is None:
        return props
    for el in props_el:
        pname = el.get("name")
        if pname is None:
            continue
        if not detailed and pname != "Name":
            continue
        if el.tag == "BinaryString":
            continue
        value = parse_value(el)
        if value is None and el.tag == "BinaryString":
            continue
        # Color3uint8 的 name 也叫 Color3uint8(BrickColor 用),GUI 不會撞到
        if el.tag == "token":
            value = enums.name_of(pname, value)
        props[pname] = value
    return props


# --------------------------------------------------------------------------
# 檔案讀取
# --------------------------------------------------------------------------


def _find_engine():
    """保留舊名字給外部呼叫;實作已搬到 convert.py。"""
    return convert.find_engine()


def _to_xml(path):
    """binary .rbxl/.rbxm -> XML 檔路徑(走 convert 的快取)。

    以前這裡每次都轉一個暫存檔再刪掉 —— 對 38 MB 的 place 就是每次 preview 都
    重付十幾分鐘。現在交給 convert.to_xml(),同一個檔第二次起是零成本。
    """
    try:
        xml_path, _cached = convert.to_xml(path)
    except convert.ConvertError as exc:
        raise RuntimeError(str(exc)) from None
    return xml_path


def load(path, keep_all=False):
    """讀檔回傳虛擬 root Node(children 是 DataModel 的頂層服務)。

    keep_all=False 時會剪掉沒有 GUI 後代的子樹 —— 對 100 MB 的 place 是必要的。
    """
    src = _to_xml(path) if path.lower().endswith((".rbxl", ".rbxm")) else path

    root = Node("__root__")
    stack = [root]
    depth_of_detail = []  # 祖先鏈上有沒有人是 GUI(是的話後代全要 detail)

    for event, el in ET.iterparse(src, events=("start", "end")):
        if el.tag != "Item":
            continue
        if event == "start":
            cls = el.get("class") or "Instance"
            node = Node(cls, el.get("referent"))
            node.parent = stack[-1]
            stack[-1].children.append(node)
            stack.append(node)
            inherit = bool(depth_of_detail and depth_of_detail[-1])
            depth_of_detail.append(inherit or cls in DETAILED)
        else:
            node = stack.pop()
            detailed = depth_of_detail.pop()
            node.props = _parse_properties(el, detailed)
            if "Name" in node.props and node.props["Name"] is not None:
                node.name = node.props["Name"]
            el.clear()  # 這行是大檔能跑得動的關鍵

    if not keep_all:
        _prune(root)
    return root


def _prune(node):
    """回傳 True 表示這棵子樹要留下(自己是 GUI,或有 GUI 後代)。

    UICorner / UIListLayout 這些修飾物件要跟著父節點留下 —— 它們自己不是 GUI,
    但少了它們圓角、描邊、排版全部會失效。不過它們不算「有 GUI 後代」,
    免得一個只放著 UIListLayout 的 Folder 把整條路徑救活。
    """
    keep_children = []
    has_gui = False
    for child in node.children:
        child_has_gui = _prune(child)
        if child_has_gui or child.class_name in defaults.MODIFIER_CLASSES:
            keep_children.append(child)
        if child_has_gui:
            has_gui = True
    node.children = keep_children
    return has_gui or node.class_name in GUI_ROOTS


# --------------------------------------------------------------------------
# 路徑查找
# --------------------------------------------------------------------------


def resolve(root, path):
    """用 `A.B.C` 找節點。找不到時回傳 None。

    路徑可以從任何一層開始 —— 先試絕對路徑,失敗再全樹搜尋第一個尾綴相符的。
    """
    if not path:
        return None
    parts = [p for p in path.split(".") if p]

    node = root
    for part in parts:
        nxt = node.find_child(part)
        if nxt is None:
            node = None
            break
        node = nxt
    if node is not None:
        return node

    # 尾綴比對:允許只給 "MechanicsFrame.QTE" 這種片段
    matches = []
    _collect_suffix(root, parts, matches)
    if matches:
        matches.sort(key=lambda n: len(n.path))
        return matches[0]
    return None


def _collect_suffix(node, parts, out):
    for child in node.children:
        if child.name == parts[0]:
            cursor = child
            ok = True
            for part in parts[1:]:
                cursor = cursor.find_child(part)
                if cursor is None:
                    ok = False
                    break
            if ok:
                out.append(cursor)
        _collect_suffix(child, parts, out)


def find_guis(root):
    """列出所有可以當預覽起點的節點:ScreenGui/SurfaceGui/BillboardGui,
    以及不在任何 GUI 底下的孤兒 GuiObject(抽出來的 UI 片段常是這樣)。"""
    out = []

    def walk(node, inside_gui):
        for child in node.children:
            cls = child.class_name
            if cls in ("ScreenGui", "SurfaceGui", "BillboardGui"):
                out.append(child)
                walk(child, True)
            elif cls in defaults.GUI_OBJECT_CLASSES:
                if not inside_gui:
                    out.append(child)
                walk(child, True)
            else:
                walk(child, inside_gui)

    walk(root, False)
    return out
