"""把 ops.Change 翻成 splice.Document 的位元組操作,再寫檔。

這裡是「樹的世界」與「位元組的世界」交界的地方。紀律只有一條:
**用最小的位元組動作達成目的**。

  改屬性  -> 只換 <Properties>            子物件一個 byte 不動
  加東西  -> 插在父節點 </Item> 之前       兄弟不動
  刪東西  -> 剪掉那一段
  搬家    -> 原位元組剪下貼上              零損耗
  整段換  -> 只有使用者明說 --replace 才做,而且會警告

會這樣是因為 `parse.load()` 刻意有損(剪枝 + 只細解 GUI class)。
拿它重建整棵子樹,ScreenGui 底下的 LocalScript 會全部消失 —— 而且**畫面看起來
一模一樣**,要等到進 Studio 按下 Play 才會發現 UI 沒反應。
"""

import os

from . import emit, splice


class SculptError(RuntimeError):
    pass


def prop_fragments(node, names, pad):
    """要改的那幾個屬性 -> `{屬性名: XML 片段}`,交給 splice 逐項併回去。

    **只產出這次真的改了的那幾個。** 整塊重寫 `<Properties>` 是不行的:
    `node.props` 來自刻意有損的 `parse.load()` —— `<BinaryString>`(Attributes、
    Tags)整個被跳過、`<Ref>` 只剩字串、`ProtectedString` 分不出來。實測過:
    只改一個背景色,結果 `AttributesSerialize` 整個消失、`NextSelectionUp` 從
    `<Ref>` 變成 `<string>`(指標壞掉),而畫面看起來一模一樣。

    值給 None 代表把那個屬性從檔案裡刪掉 —— `CornerRadius` 展開成四個角之後
    就得把 legacy 的那個拿掉,不然檔案裡兩種寫法並存。
    """
    normalized = emit.normalize_props(node.class_name, dict(node.props))
    normalized.setdefault("Name", node.name)

    wanted = set(names)
    # 正規化會把 CornerRadius 換成四個角、Image 補上 ImageContent。
    # 使用者說要改 CornerRadius,實際要寫的是那四個。
    for name in list(wanted):
        if name not in normalized:
            for k in normalized:
                if k in emit.CORNER_PROPS and name == "CornerRadius":
                    wanted.add(k)
        twin = name + "Content" if not name.endswith("Content") else name[:-7]
        if twin in normalized and twin not in wanted:
            wanted.add(twin)

    out = {}
    for name in sorted(wanted):
        if name in normalized:
            out[name] = emit.prop_xml(name, normalized[name])
        else:
            out[name] = None            # 正規化之後不該存在了,刪掉
    return out


def _reindent(text, pad):
    """把 emit 產出的片段整段推到指定縮排 —— 純美觀,但 diff 要有人看得下去。"""
    if not pad:
        return text
    return "\n".join((pad + ln) if ln.strip() else ln for ln in text.split("\n"))


def apply_changes(doc, changes, verbose=True):
    """把 changes 套到 doc 上。回 (套用數, [警告, …])。"""
    warnings = []
    applied = 0

    for ch in changes:
        if ch.kind == "props":
            ref = _need_ref(ch.node, "改屬性")
            names = ch.props or [k for k in ch.node.props if k != "Name"]
            doc.merge_properties(
                ref, prop_fragments(ch.node, names, doc.properties_indent(ref)))

        elif ch.kind == "insert":
            parent_ref = _need_ref(ch.parent, "插入")
            alloc = doc.ref_alloc()
            pad = doc.child_indent(parent_ref)
            xml = emit.node_xml(ch.node, alloc, indent=0).rstrip("\n")
            doc.insert_children(parent_ref, _reindent(xml, pad) + "\n")

        elif ch.kind == "delete":
            doc.delete_subtree(_need_ref(ch.node, "刪除"))

        elif ch.kind == "move":
            doc.move_subtree(_need_ref(ch.node, "搬移"),
                             _need_ref(ch.parent, "搬移的目的地"))

        elif ch.kind == "reorder":
            parent_ref = _need_ref(ch.node, "重排")
            refs = [c.referent for c in (ch.order or []) if c.referent]
            doc.reorder_children(parent_ref, refs)

        elif ch.kind == "subtree":
            ref = _need_ref(ch.node, "整段取代")
            alloc = doc.ref_alloc()
            xml = emit.node_xml(ch.node, alloc, indent=0).rstrip("\n")
            doc.replace_subtree(ref, _reindent(xml, doc.indent_for(ref)).lstrip())
            warnings.append(
                "整段取代了 %s —— 它底下不是 GUI 的東西(LocalScript、Folder…)"
                "不會被保留,因為讀取端看不到它們。要保留就別用 --replace。"
                % ch.node.path)

        else:
            raise SculptError("不認得的改動類型 %r" % ch.kind)
        applied += 1

    return applied, warnings


def _need_ref(node, what):
    if node is None:
        raise SculptError("%s 少了目標節點" % what)
    if not node.referent:
        raise SculptError(
            "%s [%s] 沒有 referent —— 它不是從檔案讀出來的,%s 不知道要動哪裡。"
            % (node.name, node.class_name, what))
    return node.referent


def write(doc, out_path, verbose=True):
    return doc.save(out_path, verbose=verbose)


def new_document(nodes, out_path, verbose=True):
    """從零建一個新檔(不需要既有檔案)。"""
    xml = emit.document_xml(nodes)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if out_path.lower().endswith((".rbxlx", ".rbxmx")):
        with open(out_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(xml)
        return out_path

    from . import convert
    tmp = out_path + ".sculpt.rbxlx"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(xml)
    try:
        convert.to_binary(tmp, out_path, verbose=verbose)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return out_path


def open_document(path, verbose=True):
    return splice.Document.open(path, verbose=verbose)
