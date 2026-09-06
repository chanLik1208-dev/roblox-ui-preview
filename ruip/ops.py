"""指令式 patch 操作 —— 對既有 GUI 做外科手術。

spec 適合「整段重做」,ops 適合「只動這三個屬性」。兩者共用 coerce 的型別系統
與 splice 的寫入路徑,差別只在前端。

    [{"op":"set",    "path":"Shop.Panel", "props":{"BackgroundTransparency":0.2}},
     {"op":"insert", "parent":"Shop.Panel", "class":"UIStroke",
                     "props":{"Color":"#FFAA00","Thickness":2}},
     {"op":"delete", "path":"Shop.OldBtn"},
     {"op":"rename", "path":"Shop.Btn1", "to":"BuyButton"},
     {"op":"move",   "path":"Shop.Title", "to":"Shop.Panel"},
     {"op":"reorder","parent":"Shop.Panel", "order":["Title","Body","Footer"]}]

路徑寫法 `A.B.C`。同名兄弟用 `A.B[2]`(0-based),要指定類別用 `A.B#TextLabel`。
**寫入時要求唯一命中** —— 多重命中就報錯並列出候選。`parse.resolve()` 那種
「猜最短的」在唯讀渲染是體貼,在寫入是災難。
"""

import json

from . import coerce, defaults, emit, parse, spec

OPS = ("set", "insert", "delete", "rename", "move", "reorder")


class OpError(ValueError):
    def __init__(self, msg, index=None):
        if index is not None:
            msg = "第 %d 個操作: %s" % (index + 1, msg)
        super().__init__(msg)


# --------------------------------------------------------------------------
# 路徑定址
# --------------------------------------------------------------------------


def _split_step(step):
    """`Name[2]#Class` -> (name, index|None, class|None)"""
    cls = None
    if "#" in step:
        step, cls = step.split("#", 1)
    idx = None
    if step.endswith("]") and "[" in step:
        step, rest = step.rsplit("[", 1)
        try:
            idx = int(rest[:-1])
        except ValueError:
            raise OpError("路徑的 [n] 要是數字,不是 %r" % rest[:-1]) from None
    return step, idx, cls


def resolve_one(root, path):
    """路徑 -> 唯一的一個 Node。找不到或不唯一都丟 OpError。"""
    if not path:
        raise OpError("路徑不能是空的")
    steps = path.split(".")

    # 先當絕對路徑走(從 root 的孩子開始)
    hits = _walk(root, steps)
    if not hits:
        # 再試尾綴比對 —— 使用者常常只寫 "Shop.Panel" 而不寫完整的
        # "StarterGui.Ingame.Shop.Panel"
        hits = _suffix_match(root, steps)
    if not hits:
        raise OpError("路徑找不到:%s%s" % (path, _nearby(root, steps[-1])))
    if len(hits) > 1:
        listing = "\n".join("      " + n.path for n in hits[:8])
        more = "" if len(hits) <= 8 else "\n      …還有 %d 個" % (len(hits) - 8)
        hint = ("改用完整路徑,或 %s[0] 指定第幾個" % path) if "#" in path else (
            "改用完整路徑、%s#ClassName 指定類別,或 %s[0] 指定第幾個" % (path, path))
        raise OpError(
            "路徑 %s 命中 %d 個物件,不知道要改哪一個。\n    %s。候選:\n%s%s"
            % (path, len(hits), hint, listing, more)
        )
    return hits[0]


def _match(node, name, cls):
    return node.name == name and (cls is None or node.class_name == cls)


def _walk(root, steps):
    """從 root 開始逐層往下,回所有走得通的終點。"""
    level = [root]
    for step in steps:
        name, idx, cls = _split_step(step)
        nxt = []
        for parent in level:
            kids = [c for c in parent.children if _match(c, name, cls)]
            if idx is not None:
                kids = kids[idx:idx + 1]
            nxt.extend(kids)
        if not nxt:
            return []
        level = nxt
    return level


def _suffix_match(root, steps):
    """全樹找「路徑尾巴長這樣」的節點。"""
    name, idx, cls = _split_step(steps[-1])
    out = []

    def visit(node):
        if _match(node, name, cls) and _ends_with(node, steps):
            out.append(node)
        for c in node.children:
            visit(c)

    for c in root.children:
        visit(c)
    if idx is not None:
        out = out[idx:idx + 1]
    return out


def _ends_with(node, steps):
    n = node
    for step in reversed(steps):
        if n is None:
            return False
        name, _idx, cls = _split_step(step)
        if not _match(n, name, cls):
            return False
        n = n.parent
    return True


def _nearby(root, name):
    """路徑找不到時,列幾個名字相近的,省得 agent 亂猜。"""
    cands = []

    def visit(node):
        if name.lower() in node.name.lower() or node.name.lower() in name.lower():
            cands.append(node.path)
        for c in node.children:
            visit(c)

    for c in root.children:
        visit(c)
    if not cands:
        return ""
    return "\n    名字相近的有:\n" + "\n".join("      " + p for p in cands[:8])


# --------------------------------------------------------------------------
# 套用
# --------------------------------------------------------------------------


class Change:
    """一次改動的紀錄。sculpt.py 靠它印摘要,splice 靠它決定怎麼動位元組。

    kind 決定要動多少位元組,由小到大:

      props    只換這個節點的 <Properties>,子物件一個 byte 都不碰(改屬性走這條)
      insert   把一棵新子樹插進 parent 的 </Item> 之前
      delete   剪掉這個節點的 <Item>…</Item>
      move     原位元組剪下、原位元組貼上到新 parent
      reorder  依檔案裡實際的子物件重排 parent 的直接子物件
      subtree  整棵換掉 —— **會連非 GUI 的子物件一起沒掉**,只有 --replace 才用

    「能用 props 就不要用 subtree」是這個檔案的核心紀律:`parse.load()` 是有損的,
    拿它重建子樹會把 ScreenGui 底下的 LocalScript 弄不見。
    """

    __slots__ = ("kind", "node", "parent", "detail", "order", "props")

    def __init__(self, kind, node=None, parent=None, detail="", order=None,
                 props=None):
        self.kind = kind
        self.node = node
        self.parent = parent
        self.detail = detail
        self.order = order        # reorder 用:新順序的 Node 串列
        # props 用:**這次真的改了哪幾個屬性**。只寫這幾個,其餘的 XML 原樣保留 ——
        # node.props 來自有損的 parse.load(),整塊重寫會把 BinaryString、Ref
        # 這類它讀不回來的屬性弄壞(見 splice.merge_properties)。
        self.props = list(props or ())

    def __repr__(self):
        return "<Change %s %s>" % (self.kind, self.detail)


def load_ops(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise OpError("ops 檔要是一個陣列")
    return data


def apply_ops(root, ops):
    """在樹上套用 ops,回 [Change, …]。**只改記憶體裡的樹**,不碰檔案。"""
    changes = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise OpError("每個操作要是一個物件", i)
        kind = op.get("op")
        if kind not in OPS:
            raise OpError("不認得的 op %r,只有:%s" % (kind, "、".join(OPS)), i)
        try:
            changes.extend(_APPLY[kind](root, op))
        except (OpError, coerce.CoerceError) as exc:
            raise OpError(str(exc), i) from None
    return changes


def _op_set(root, op):
    node = resolve_one(root, op.get("path", ""))
    props = op.get("props") or {}
    if not props:
        raise OpError("set 要給 props")
    touched = []
    for k, v in props.items():
        if k == "Name":
            node.name = v
            node.props["Name"] = v
        else:
            node.props[k] = coerce.value(node.class_name, k, v)
        touched.append(k)
    return [Change("props", node=node, props=touched,
                   detail="%s ← %s" % (node.path, ", ".join(sorted(touched))))]


def _op_insert(root, op):
    parent_path = op.get("parent")
    cls = op.get("class")
    if not cls:
        raise OpError("insert 要給 class")
    parent = resolve_one(root, parent_path) if parent_path else None
    name = op.get("name") or cls

    node = parse.Node(cls)
    node.name = name
    node.props["Name"] = name
    for k, v in (op.get("props") or {}).items():
        if k == "Name":
            node.name = v
            node.props["Name"] = v
        else:
            node.props[k] = coerce.value(cls, k, v)

    if parent is None:
        raise OpError("insert 要給 parent(頂層新增請用 spec + --at)")
    node.parent = parent
    at = op.get("index")
    if at is None:
        parent.children.append(node)
    else:
        parent.children.insert(int(at), node)
    return [Change("insert", node=node, parent=parent,
                   detail="%s ＋ %s %s" % (parent.path, cls, name))]


def _op_delete(root, op):
    node = resolve_one(root, op.get("path", ""))
    if node.parent is None:
        raise OpError("刪不掉頂層節點")
    node.parent.children.remove(node)
    return [Change("delete", node=node, parent=node.parent,
                   detail="刪掉 %s [%s]" % (node.path, node.class_name))]


def _op_rename(root, op):
    node = resolve_one(root, op.get("path", ""))
    to = op.get("to")
    if not to:
        raise OpError("rename 要給 to")
    old = node.name
    node.name = to
    node.props["Name"] = to
    return [Change("props", node=node, props=["Name"],
                   detail="%s 改名成 %s" % (old, to))]


def _op_move(root, op):
    node = resolve_one(root, op.get("path", ""))
    new_parent = resolve_one(root, op.get("to", ""))
    if node.parent is None:
        raise OpError("移不動頂層節點")
    if _is_ancestor(node, new_parent):
        raise OpError("不能把物件搬進自己的後代裡")
    old_parent = node.parent
    old_parent.children.remove(node)
    node.parent = new_parent
    new_parent.children.append(node)
    return [Change("move", node=node, parent=new_parent,
                   detail="%s 從 %s 搬到 %s"
                          % (node.name, old_parent.path, new_parent.path))]


def _is_ancestor(node, maybe_descendant):
    n = maybe_descendant
    while n is not None:
        if n is node:
            return True
        n = n.parent
    return False


def _op_reorder(root, op):
    parent = resolve_one(root, op.get("parent", ""))
    order = op.get("order") or []
    if not order:
        raise OpError("reorder 要給 order")
    by_name = {}
    for c in parent.children:
        by_name.setdefault(c.name, []).append(c)
    ordered, used = [], set()
    for name in order:
        bucket = by_name.get(name)
        if not bucket:
            raise OpError("%s 底下沒有叫 %s 的東西" % (parent.path, name))
        for c in bucket:
            ordered.append(c)
            used.add(id(c))
    ordered += [c for c in parent.children if id(c) not in used]
    parent.children = ordered
    return [Change("reorder", node=parent, order=list(ordered),
                   detail="%s 重排子物件" % parent.path)]


_APPLY = {
    "set": _op_set,
    "insert": _op_insert,
    "delete": _op_delete,
    "rename": _op_rename,
    "move": _op_move,
    "reorder": _op_reorder,
}


# --------------------------------------------------------------------------
# spec 合併
# --------------------------------------------------------------------------


def merge_spec(root, spec_nodes, at=None, replace=False, target_path=None):
    """把 spec 併進既有樹。

    `replace=False`(預設):依 name+class upsert —— spec 沒提到的屬性與子物件
    原封不動留著。這是安全的預設值,因為 AI 常常只寫它想改的那幾行,
    整段取代會**靜默地**把沒提到的東西清光。
    `replace=True`:同名同類的節點整棵換掉。
    """
    changes = []
    parent = resolve_one(root, at) if at else None

    for i, node in enumerate(spec_nodes):
        existing = None

        # dump 出來的 spec 檔頭記著它從哪來(`# @path …`),優先照它走 ——
        # 真實 place 裡同名節點滿天飛,靠名字比對必撞。
        if parent is None and target_path and i == 0:
            existing = resolve_one(root, target_path)

        pool = parent.children if parent is not None else root.children
        if existing is None:
            for c in pool:
                if c.name == node.name and c.class_name == node.class_name:
                    existing = c
                    break

        if existing is None and parent is None:
            # 沒給 --at 時,在整棵樹裡找同名同類的 —— 這是 dump -> 編輯 -> apply
            # 這條主要流程能成立的關鍵:dump 出來的是深處的某個節點,
            # 使用者不該還要自己把 --at 抄一遍。找不到才要求 --at。
            try:
                existing = resolve_one(root, "%s#%s" % (node.name, node.class_name))
            except OpError as exc:
                if "命中" in str(exc):      # 找到多個 —— 讓使用者看候選,不要亂猜
                    raise
                existing = None

        if existing is None:
            if parent is None:
                raise OpError(
                    "整個檔案裡找不到 %s [%s],所以不知道要改哪個;\n"
                    "    要新增的話請用 --at 指定放在哪個節點底下"
                    "(例如 --at StarterGui)。" % (node.name, node.class_name))
            node.parent = parent
            parent.children.append(node)
            changes.append(Change("insert", node=node, parent=parent,
                                  detail="%s ＋ %s %s"
                                         % (parent.path, node.class_name, node.name)))
            continue

        if replace:
            wiped = _wiped_props(existing, node)
            existing.props = dict(node.props)
            existing.children = []
            for c in node.children:
                c.parent = existing
                existing.children.append(c)
            detail = "%s 整段取代" % existing.path
            if wiped:
                detail += "(清掉了 %s)" % ", ".join(sorted(wiped))
            changes.append(Change("subtree", node=existing, detail=detail))
        else:
            changes.extend(_merge_into(existing, node))
    return changes


def _wiped_props(existing, incoming):
    """整段取代時,原本有值但新的沒提到的屬性。摘要要點名,不能默默清掉。"""
    base = defaults.defaults_for(existing.class_name)
    out = set()
    for k, v in existing.props.items():
        if k == "Name" or k in incoming.props:
            continue
        if k in base and base[k] == v:
            continue
        out.add(k)
    return out


def _merge_into(dst, src):
    touched = []
    # 先正規化再比:spec 裡寫 `CornerRadius: 12px`,檔案裡存的是四個角
    # (Image / ImageContent 同理)。不正規化的話兩邊永遠不相等,
    # 「什麼都沒改」也會被判定成改了。
    src_props = emit.normalize_props(src.class_name, src.props)
    for k, v in src_props.items():
        if k == "Name":
            continue
        # 容差比較,不是 ==。Roblox 用 float32,dump 再讀回來會有 ~1e-8 的差 ——
        # 用 == 的話「什麼都沒改就 apply」會產生一堆假改動(見 emit.values_equal)。
        if not emit.values_equal(dst.props.get(k), v):
            dst.props[k] = v
            touched.append(k)
    changes = []
    if touched:
        changes.append(Change("props", node=dst, props=touched,
                              detail="%s ← %s" % (dst.path, ", ".join(sorted(touched)))))

    # 同名同類的兄弟要**依序**配對,不能每次都抓第一個。
    # Roblox 裡同名兄弟很常見(一排 Slot、一堆 Sound),抓第一個的話
    # spec 裡 N 個節點會全部併進同一個,其餘 N-1 個的內容被丟掉,
    # 而且第一個會被最後一份覆蓋 —— 靜默的資料損毀。
    pool = {}
    for c in dst.children:
        pool.setdefault((c.name, c.class_name), []).append(c)
    taken = {}

    for child in src.children:
        key = (child.name, child.class_name)
        i = taken.get(key, 0)
        bucket = pool.get(key, [])
        match = bucket[i] if i < len(bucket) else None
        taken[key] = i + 1

        if match is None:
            child.parent = dst
            dst.children.append(child)
            changes.append(Change("insert", node=child, parent=dst,
                                  detail="%s ＋ %s %s"
                                         % (dst.path, child.class_name, child.name)))
        else:
            changes.extend(_merge_into(match, child))
    return changes


def load_spec(path, strict=True):
    return spec.parse_file(path, strict=strict)
