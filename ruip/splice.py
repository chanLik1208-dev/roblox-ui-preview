r"""byte 級的 XML 子樹手術。

雕刻既有檔案有個很煩的限制:**不能把整份 XML 讀進 ElementTree**。
真實 place 的 XML dump 可以到 200 MB / 100 萬 instance,`ET.parse` 會吃掉好幾 GB。
`parse.load()` 之所以能跑是因為它 iterparse + 邊走邊 clear,而且刻意丟掉大部分資訊 ——
它是**有損**的,拿它重建檔案會把 Workspace 的幾何全部弄不見。

所以改動既有檔案的作法是:

    1. `parse.load()` 找到目標,拿它的 referent(rbx_xml 保證唯一)
    2. 在原始位元組裡找 `referent="X"`,往前找到那個 `<Item`,
       再往後做深度計數找到配對的 `</Item>` —— 得到一段位元組區間
    3. 只把**那一段**(通常幾 KB)丟給 ElementTree,改完再序列化
    4. `前面 + 新片段 + 後面` 直接拼回去

好處是記憶體平坦,而且 `<Meta>`、`<External>`、SharedStrings、以及所有跟這次改動無關
的東西天然 byte 級保留 —— 不是「盡量保留」,是根本沒碰到。
"""

import io
import os
import re
import shutil

from . import convert, emit, parse

ITEM_OPEN = re.compile(rb"<Item\b")
ITEM_CLOSE = re.compile(rb"</Item>")
SELF_CLOSE = re.compile(rb"<Item\b[^>]*/>")
REFERENT_ATTR = re.compile(rb'referent="([^"]*)"')


class SpliceError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 定位
# --------------------------------------------------------------------------


def all_referents(data):
    """檔案裡所有 referent 字串。配新號時用來避開。"""
    return {m.group(1).decode("utf-8", "replace") for m in REFERENT_ATTR.finditer(data)}


def find_item_span(data, referent):
    """回 (start, end) —— 帶著這個 referent 的那個 `<Item …>…</Item>` 的位元組區間。"""
    needle = ('referent="%s"' % referent).encode("utf-8")
    pos = data.find(needle)
    if pos < 0:
        raise SpliceError("在檔案裡找不到 referent=%s" % referent)
    if data.find(needle, pos + 1) >= 0:
        raise SpliceError("referent=%s 出現不只一次,檔案有問題" % referent)

    start = data.rfind(b"<Item", 0, pos)
    if start < 0:
        raise SpliceError("referent=%s 前面找不到 <Item" % referent)

    return start, _matching_close(data, start)


def _matching_close(data, start):
    """從 `<Item` 起算,做深度計數找到配對的 `</Item>` 的結束位置。

    `<Item …/>` 自閉合是合法的(沒有 Properties 的空物件),要當成深度 0 處理。
    """
    # 目標本身就是自閉合的 `<Item …/>` —— 它沒有配對的 </Item>,直接就結束了。
    # 少了這一段的話 depth 永遠不會從 1 掉回 0,掃描會一路吃到某個祖先的收尾,
    # 於是 delete/replace/move 會把整個父子樹一起吃掉。
    first_end = data.find(b">", start)
    if first_end < 0:
        raise SpliceError("XML 不完整:<Item 沒有收尾的 >")
    if data[first_end - 1:first_end] == b"/":
        return first_end + 1

    depth = 0
    i = start
    n = len(data)
    while i < n:
        nxt_open = data.find(b"<Item", i)
        nxt_close = data.find(b"</Item>", i)
        if nxt_close < 0:
            raise SpliceError("XML 不完整:找不到配對的 </Item>")
        if nxt_open >= 0 and nxt_open < nxt_close:
            tag_end = data.find(b">", nxt_open)
            if tag_end < 0:
                raise SpliceError("XML 不完整:<Item 沒有收尾的 >")
            if data[tag_end - 1:tag_end] != b"/":     # 自閉合不增加深度
                depth += 1
            i = tag_end + 1
            continue
        depth -= 1
        i = nxt_close + len(b"</Item>")
        if depth == 0:
            return i
    raise SpliceError("XML 不完整:深度沒有回到 0")


def find_insert_point(data, parent_referent):
    """要把新子物件插進某個 `<Item>` 時的插入位置。

    回的是**收尾 `</Item>` 那一行的行首**,不是 `</Item>` 這個 tag 之前 ——
    後者的位置前面已經躺著那一行的縮排空白,插進去會多出一截,新節點看起來
    像是縮排壞掉。從行首插就乾淨:`pad + 內容 + "\\n"`,原本那行原封不動接在後面。
    """
    _start, end = find_item_span(data, parent_referent)
    close = end - len(b"</Item>")
    line_start = data.rfind(b"\n", 0, close)
    if line_start >= 0 and data[line_start + 1:close].strip() == b"":
        return line_start + 1
    return close


def find_properties_span(data, referent):
    """回這個 Item 自己的 `<Properties>…</Properties>` 的位元組區間。

    **只改屬性就只碰這一段** —— 這是整個設計最關鍵的一點。
    `parse.load()` 是有損的(會剪枝,非 GUI 的 class 只留 Name),拿它重建整棵子樹
    會把 ScreenGui 底下的 LocalScript 全部弄不見。所以改顏色就只換 Properties,
    子物件那幾千個位元組動都不動。
    """
    start, end = find_item_span(data, referent)
    ps = data.find(b"<Properties>", start, end)
    if ps < 0:
        # 沒有 <Properties> 的 Item(空物件)—— 插在開頭標籤後面
        tag_end = data.find(b">", start)
        return tag_end + 1, tag_end + 1
    pe = data.find(b"</Properties>", ps, end)
    if pe < 0:
        raise SpliceError("referent=%s 的 <Properties> 沒有收尾" % referent)
    return ps, pe + len(b"</Properties>")


def subtree_bytes(data, referent):
    """原封不動取出一棵子樹的位元組 —— 搬家時用,一個 bit 都不會變。"""
    start, end = find_item_span(data, referent)
    return data[start:end]


def direct_children_spans(data, parent_referent):
    """回 [(referent, start, end), …] —— 直接子物件,依檔案順序。

    走的是**檔案**而不是 `parse.load()` 的樹,所以連被剪枝掉的 LocalScript
    也會在裡面。重排子物件時這一點是對錯的分野。
    """
    p_start, p_end = find_item_span(data, parent_referent)
    body_start = data.find(b">", p_start) + 1
    out = []
    i = body_start
    limit = p_end - len(b"</Item>")
    while i < limit:
        nxt = data.find(b"<Item", i, limit)
        if nxt < 0:
            break
        end = _matching_close(data, nxt)
        m = REFERENT_ATTR.search(data, nxt, data.find(b">", nxt))
        out.append((m.group(1).decode("utf-8", "replace") if m else None, nxt, end))
        i = end
    return out


def _indent_of(data, pos):
    """pos 那一行的縮排空白。重排時用它讓輸出還是對齊的。"""
    ls = data.rfind(b"\n", 0, pos)
    return data[ls + 1:pos] if ls >= 0 and data[ls + 1:pos].strip() == b"" else b""


# --------------------------------------------------------------------------
# <Properties> 區塊的逐項合併
# --------------------------------------------------------------------------


def prop_span(block, name):
    """在一段 `<Properties>` 裡找某個屬性元素的位元組區間。找不到回 None。

    屬性元素的標籤名是型別(`<UDim2 name="Size">`、`<Ref name="X">`…),
    所以要先讀出標籤名再找對應的收尾。屬性值裡不會出現同名標籤
    (UDim2 裡是 `<XS>`、Content 裡是 `<url>`),所以直接找第一個收尾就對。
    """
    pat = re.compile(rb'<([A-Za-z0-9_]+)\s+name="' + re.escape(name.encode("utf-8"))
                     + rb'"\s*(/?)>')
    m = pat.search(block)
    if not m:
        return None
    if m.group(2) == b"/":                    # <Tag name="X"/>
        return m.start(), m.end()
    close = b"</" + m.group(1) + b">"
    end = block.find(close, m.end())
    if end < 0:
        return None
    return m.start(), end + len(close)


def _prop_indent(block):
    """區塊裡屬性行的縮排。抓第一個屬性元素那一行。"""
    m = re.search(rb"\n(\s*)<[A-Za-z0-9_]+\s+name=", block)
    return m.group(1) if m else b"      "


def _merge_props_block(block, fragments):
    """把 fragments 併進既有的 `<Properties>` 區塊,其餘位元組原樣保留。"""
    pad = _prop_indent(block)
    close = b"</Properties>"
    for name, frag in fragments.items():
        span = prop_span(block, name)
        if frag is None:                       # 刪掉這個屬性
            if span:
                s, e = span
                ls = block.rfind(b"\n", 0, s)
                if ls >= 0 and block[ls + 1:s].strip() == b"":
                    s = ls
                block = block[:s] + block[e:]
            continue
        fb = frag.encode("utf-8")
        if span:
            block = block[:span[0]] + fb + block[span[1]:]
        else:
            at = block.rfind(close)
            if at < 0:
                block = block + fb
                continue
            # 插在 `</Properties>` **那一行的行首**,用屬性行的縮排;
            # 直接插在 tag 前面的話會沿用收尾那一行的縮排(少兩格)。
            ls = block.rfind(b"\n", 0, at)
            if ls >= 0 and block[ls + 1:at].strip() == b"":
                close_pad = block[ls + 1:at]
                block = (block[:ls + 1] + pad + fb.lstrip() + b"\n"
                         + close_pad + block[at:])
            else:
                block = block[:at] + fb.lstrip() + b"\n" + block[at:]
    return block


def _new_properties_block(fragments, pad):
    """這個 Item 本來連 `<Properties>` 都沒有的時候,從頭生一個。

    第一行不加縮排 —— 它是就地插在已經有縮排的位置上。
    """
    p = pad.encode("utf-8") if isinstance(pad, str) else pad
    out = [b"<Properties>"]
    for frag in fragments.values():
        if frag is not None:
            out.append(p + b"  " + frag.encode("utf-8").lstrip())
    out.append(p + b"</Properties>")
    return b"\n".join(out)


# --------------------------------------------------------------------------
# 讀出 / 寫回
# --------------------------------------------------------------------------


class Document:
    """一份可雕刻的 XML 檔。

    所有改動先記在 `self._edits`(位元組區間 -> 新內容),`save()` 時一次套用。
    這樣多個改動之間的偏移量不會互相影響 —— 從後往前套就好。
    """

    def __init__(self, path, source_path=None):
        self.path = path                    # 實際讀的 XML(可能是快取)
        self.source_path = source_path or path   # 使用者給的原始檔
        with open(path, "rb") as fh:
            self.data = fh.read()
        self._edits = []                    # [(start, end, bytes)]
        self._refs = None
        self._alloc = None

    @classmethod
    def open(cls, path, verbose=True):
        """吃 .rbxl/.rbxlx/.rbxm/.rbxmx;二進位會先(快取地)轉成 XML。"""
        xml_path, _cached = convert.to_xml(path, verbose=verbose)
        return cls(xml_path, source_path=path)

    # -- referent 配號 --------------------------------------------------
    def ref_alloc(self):
        """整份文件共用**同一個**配號器。

        每次 insert 都重建一個的話,每個新節點都會拿到 RUIS1 —— 撞號會讓
        `find_item_span` 找不到唯一目標,`<Ref>` 屬性也可能指到錯的物件。
        """
        if self._alloc is None:
            if self._refs is None:
                self._refs = all_referents(self.data)
            self._alloc = emit.make_ref_alloc(self._refs)
        return self._alloc

    def indent_for(self, referent):
        """這個 Item 在檔案裡的縮排(字串)。splice 進去的內容跟著對齊。"""
        start, _end = find_item_span(self.data, referent)
        return _indent_of(self.data, start).decode("utf-8", "replace")

    def properties_indent(self, referent):
        """這個 Item 的 `<Properties>` 那一行的縮排。

        直接從檔案量,不要用「Item 縮排 + 2」去猜 —— 不同來源產出的 XML
        縮排習慣不一樣(rbx_xml 用 2 格,手寫的檔案什麼都有),猜錯就會越縮越深。
        """
        ps, _pe = find_properties_span(self.data, referent)
        return _indent_of(self.data, ps).decode("utf-8", "replace")

    def child_indent(self, parent_referent):
        """新子物件該用的縮排:跟既有的第一個子物件對齊,沒有子物件就父層加兩格。"""
        spans = direct_children_spans(self.data, parent_referent)
        if spans:
            return _indent_of(self.data, spans[0][1]).decode("utf-8", "replace")
        return self.indent_for(parent_referent) + "  "

    # -- 待套改動的管理 --------------------------------------------------
    def _overlaps(self, start, end):
        for s, e, _p in self._edits:
            if s == e == start == end:     # 同一點的兩次插入不算衝突
                continue                   # ← 是 continue 不是 return:
                                           #   還有別的待辦要檢查
            if start < e and s < end:
                return True
        return False

    def rebase(self):
        """把目前累積的改動先套進 data,清空待辦。

        為什麼需要:reorder 這種粗粒度操作會涵蓋整個子物件區,跟同一批裡的
        insert / 改屬性必然重疊。與其報錯要人重排指令順序,不如**分批套用** ——
        referent 在套用前後是穩定的,所以第二批重新定位一定找得到。
        """
        if not self._edits:
            return False
        self.data = self.rendered()
        self._edits = []
        self._refs = None
        return True

    def _stage(self, span_fn, payload_fn):
        """算出位元組區間 -> 有衝突就先 rebase 再重算 -> 排進待辦。"""
        start, end = span_fn()
        if self._overlaps(start, end):
            self.rebase()
            start, end = span_fn()
        self._edits.append((start, end, payload_fn()))

    # -- 改動 ------------------------------------------------------------
    def merge_properties(self, referent, fragments):
        """把幾個屬性併進既有的 `<Properties>` —— **沒提到的原樣保留**。

        fragments 是 `{屬性名: XML 片段}`;值給 None 代表把那個屬性刪掉。

        為什麼不能整塊重寫:`node.props` 來自刻意有損的 `parse.load()`。
        `<BinaryString>`(Attributes、Tags)整個被跳過,`<Ref>` 只留字串,
        `ProtectedString` 分不出來。拿它重建 `<Properties>` 的話,
        改一個背景色會順手把 Attributes 刪掉、把 `<Ref>` 寫成 `<string>` ——
        指標壞掉,而且畫面看起來一模一樣。實測過,不是理論風險。
        """
        def payload():
            ps, pe = find_properties_span(self.data, referent)
            block = self.data[ps:pe]
            if ps == pe:                      # 這個 Item 本來沒有 <Properties>
                return _new_properties_block(fragments,
                                             self.indent_for(referent) + "  ")
            return _merge_props_block(block, fragments)

        self._stage(lambda: find_properties_span(self.data, referent), payload)

    def replace_properties(self, referent, xml_text):
        """整塊換掉 `<Properties>`。只有 emit 出完整內容時才該用(例如新節點)。

        改既有節點的屬性請用 `merge_properties` —— 見它的 docstring。
        """
        self._stage(lambda: find_properties_span(self.data, referent),
                    lambda: xml_text.encode("utf-8"))

    def replace_subtree(self, referent, xml_text):
        """整棵換掉。**會連同不是 GUI 的子物件(LocalScript…)一起沒掉**,
        只在使用者明說 --replace 時用,而且要在摘要裡講清楚。"""
        self._stage(lambda: find_item_span(self.data, referent),
                    lambda: xml_text.encode("utf-8"))

    def move_subtree(self, referent, new_parent_referent):
        """搬家:原地剪掉,原封不動貼到新父節點裡。位元組完全一致,零損耗。"""
        payload = subtree_bytes(self.data, referent)
        self.delete_subtree(referent)
        # 剪完先定案再算貼的位置 —— 不然「貼」的座標算在還沒剪的 data 上,
        # 目的地如果在來源後面,偏移量就會差一整棵子樹。
        self.rebase()
        pad = self.child_indent(new_parent_referent).encode("utf-8")
        self._stage(lambda: (find_insert_point(self.data, new_parent_referent),) * 2,
                    lambda: pad + payload + b"\n")

    def reorder_children(self, parent_referent, child_referents):
        """依 child_referents 的順序重排直接子物件。

        關鍵:順序由**檔案裡實際有的**子物件決定,不是由 `parse.load()` 的樹決定 ——
        後者剪掉了 LocalScript 這類非 GUI 的東西,照它重排會把它們弄不見。
        沒被列到的子物件照原順序接在後面。
        """
        self.rebase()          # 這是粗粒度操作,跟同一批的其他改動必然重疊
        spans = direct_children_spans(self.data, parent_referent)
        if not spans:
            return

        # 用**索引**排順序,不是用 referent。手寫的 XML 可能有 Item 沒寫
        # referent=,那些會全部撞成同一個 None 鍵 —— 結果是某個子物件被複製兩次、
        # 另一個消失。索引一定唯一。
        idx_of = {}
        for i, (ref, _s, _e) in enumerate(spans):
            if ref is not None:
                idx_of.setdefault(ref, i)
        wanted = []
        seen = set()
        for r in child_referents:
            i = idx_of.get(r)
            if i is not None and i not in seen:
                wanted.append(i)
                seen.add(i)
        order = wanted + [i for i in range(len(spans)) if i not in seen]

        lo = min(s for _r, s, _e in spans)
        hi = max(e for _r, _s, e in spans)
        sep = b"\n" + _indent_of(self.data, lo)
        joined = sep.join(self.data[spans[i][1]:spans[i][2]] for i in order)
        self._edits.append((lo, hi, joined))

    def delete_subtree(self, referent):
        def span():
            start, end = find_item_span(self.data, referent)
            # 順手把前面的縮排空白一起吃掉,不然會留下一行空白
            line_start = self.data.rfind(b"\n", 0, start)
            if line_start >= 0 and self.data[line_start + 1:start].strip() == b"":
                start = line_start + 1
                if self.data[end:end + 1] == b"\n":
                    end += 1
            return start, end
        self._stage(span, lambda: b"")

    def insert_children(self, parent_referent, xml_text):
        self._stage(lambda: (find_insert_point(self.data, parent_referent),) * 2,
                    lambda: xml_text.encode("utf-8"))

    def insert_roots(self, xml_text):
        """插到 `</roblox>` 之前 —— 給沒有父節點的頂層物件用。"""
        at = self.data.rfind(b"</roblox>")
        if at < 0:
            raise SpliceError("這不是 Roblox XML(找不到 </roblox>)")
        self._edits.append((at, at, xml_text.encode("utf-8")))

    # -- 產出 -------------------------------------------------------------
    @property
    def dirty(self):
        return bool(self._edits)

    def rendered(self):
        """套用所有改動後的位元組。從後往前套,前面的偏移就不會被影響。"""
        if not self._edits:
            return self.data
        edits = sorted(self._edits, key=lambda e: (e[0], e[1]))
        for a, b in zip(edits, edits[1:]):
            if b[0] < a[1]:
                raise SpliceError("兩個改動的範圍重疊了 —— 同一個物件被改了兩次?")
        out = bytearray(self.data)
        for start, end, payload in reversed(edits):
            out[start:end] = payload
        return bytes(out)

    def save(self, out_path, verbose=True):
        """寫出。副檔名決定格式:.rbxlx/.rbxmx 直接寫,其餘走 rbxl-engine 打包成二進位。"""
        data = self.rendered()
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        if out_path.lower().endswith(convert.XML_EXTS):
            with open(out_path, "wb") as fh:
                fh.write(data)
            return out_path

        tmp = out_path + ".sculpt.rbxlx"
        with open(tmp, "wb") as fh:
            fh.write(data)
        try:
            convert.to_binary(tmp, out_path, verbose=verbose)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return out_path


def default_output(src, suffix="_sculpted"):
    base, ext = os.path.splitext(src)
    return base + suffix + ext


def untouched_outside(before, after, spans):
    """驗證用:改動只發生在 spans 涵蓋的範圍內。

    spans 是 before 座標系的 [(start, end), …]。檢查方式是最保守的:
    第一個改動點**之前**的位元組要逐一相同,最後一個改動點**之後**的也要 ——
    中間那段長度會變,不比。這對「splice 有沒有誤傷別人」這個問題已經足夠。
    """
    if not spans:
        return before == after
    lo = min(s for s, _ in spans)
    hi = max(e for _, e in spans)
    tail = len(before) - hi
    return before[:lo] == after[:lo] and (tail == 0 or before[hi:] == after[len(after) - tail:])
