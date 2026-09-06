#!/usr/bin/env python3
"""雕刻端的正確性測試。

四層,由裡到外:

  1. coerce   —— 每種簡寫寫法解出來對不對;寫錯的時候有沒有當場報錯
  2. spec     —— .gui 讀寫來回、經過 XML 再回來,要逐字相同
  3. splice   —— 位元組手術:動到的範圍、沒動到的範圍、referent 唯一性、
                 **非 GUI 的子物件有沒有活下來**(這是最容易靜默壞掉的一條)
  4. 像素     —— 改完真的長那樣

    python test/run_sculpt.py
"""

import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ruip import (coerce, compare, emit, layout, ops, parse,  # noqa: E402
                  render, sculptor, spec, splice)

PASS = FAIL = 0
FAILURES = []
TMP = None


def check(label, got, want, tol=0.51):
    global PASS, FAIL
    if isinstance(want, (int, float)) and isinstance(got, (int, float)) \
            and not isinstance(want, bool) and not isinstance(got, bool):
        ok = abs(got - want) <= tol
    else:
        ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append("%s: 得到 %r,應該是 %r" % (label, got, want))


def check_raises(label, fn, *args, **kwargs):
    """該報錯的就要報錯 —— 靜默接受一個打錯的屬性名比報錯難查十倍。"""
    global PASS, FAIL
    try:
        got = fn(*args, **kwargs)
    except (coerce.CoerceError, spec.SpecError, ops.OpError, splice.SpliceError,
            sculptor.SculptError):
        PASS += 1
        return
    FAIL += 1
    FAILURES.append("%s: 應該要報錯,卻回了 %r" % (label, got))


def check_in(label, needle, haystack):
    global PASS, FAIL
    if needle in haystack:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append("%s: 找不到 %r" % (label, needle))


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------

# 刻意塞了三種「整段重寫會弄丟」的東西:
#   LocalScript(非 GUI,parse 會剪掉)、同名兄弟 Row、Meta 標頭
FIXTURE_XML = """<roblox version="4"><Meta name="ExplicitAutoJoints">true</Meta>
  <Item class="StarterGui" referent="T0">
    <Properties><string name="Name">StarterGui</string></Properties>
    <Item class="ScreenGui" referent="T1">
      <Properties><string name="Name">Shop</string><bool name="IgnoreGuiInset">true</bool></Properties>
      <Item class="LocalScript" referent="T2">
        <Properties><string name="Name">ShopClient</string><ProtectedString name="Source">print("keep me")</ProtectedString></Properties>
      </Item>
      <Item class="Frame" referent="T3">
        <Properties>
          <string name="Name">Panel</string>
          <UDim2 name="Size"><XS>0</XS><XO>400</XO><YS>0</YS><YO>300</YO></UDim2>
          <UDim2 name="Position"><XS>0</XS><XO>100</XO><YS>0</YS><YO>50</YO></UDim2>
          <Color3uint8 name="BackgroundColor3">4278190080</Color3uint8>
          <float name="BackgroundTransparency">0</float>
          <int name="BorderSizePixel">0</int>
        </Properties>
        <Item class="Frame" referent="T4">
          <Properties>
            <string name="Name">Row</string>
            <UDim2 name="Size"><XS>0</XS><XO>100</XO><YS>0</YS><YO>40</YO></UDim2>
            <float name="BackgroundTransparency">1</float>
            <int name="BorderSizePixel">0</int>
          </Properties>
        </Item>
        <Item class="Frame" referent="T5">
          <Properties>
            <string name="Name">Row</string>
            <UDim2 name="Size"><XS>0</XS><XO>100</XO><YS>0</YS><YO>40</YO></UDim2>
            <UDim2 name="Position"><XS>0</XS><XO>0</XO><YS>0</YS><YO>50</YO></UDim2>
            <float name="BackgroundTransparency">1</float>
            <int name="BorderSizePixel">0</int>
          </Properties>
        </Item>
      </Item>
    </Item>
  </Item>
</roblox>
"""


def write_fixture(name="fx.rbxlx", text=FIXTURE_XML):
    path = os.path.join(TMP, name)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return path


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 1. coerce —— 簡寫語法
# ---------------------------------------------------------------------------


def test_coerce():
    v = coerce.value
    check("UDim2 大括號", v("Frame", "Size", "{0.5,10}{0,100}"), (0.5, 10.0, 0.0, 100.0))
    check("UDim2 逗號", v("Frame", "Size", "0.5,10,0,100"), (0.5, 10.0, 0.0, 100.0))
    check("UDim2 px", v("Frame", "Size", "100px"), (0.0, 100.0, 0.0, 100.0))
    check("UDim2 %", v("Frame", "Size", "50%"), (0.5, 0.0, 0.5, 0.0))
    check("UDim px", v("UICorner", "CornerRadius", "12px"), (0.0, 12.0))
    check("UDim 純數字", v("UICorner", "CornerRadius", 8), (0.0, 8.0))
    check("UDim %", v("UICorner", "CornerRadius", "50%"), (0.5, 0.0))
    check("Vector2", v("Frame", "AnchorPoint", "0.5,0.5"), (0.5, 0.5))

    hexed = v("Frame", "BackgroundColor3", "#1E1E28")
    check("Color3 hex", [round(x, 6) for x in hexed],
          [round(30 / 255, 6), round(30 / 255, 6), round(40 / 255, 6)])
    check("Color3 rgb()", v("Frame", "BackgroundColor3", "rgb(30,30,40)"), hexed)
    check("Color3 短 hex", v("Frame", "BackgroundColor3", "#fff"), (1.0, 1.0, 1.0))
    check("Color3 名稱", v("Frame", "BackgroundColor3", "white"), (1.0, 1.0, 1.0))
    check("Color3 0..255 自動降", v("Frame", "BackgroundColor3", [255, 0, 0]), (1.0, 0.0, 0.0))

    check("Font 只給家族", v("TextLabel", "FontFace", "BuilderSans"),
          ("BuilderSans", 400, "Normal"))
    check("Font 數字粗細", v("TextLabel", "FontFace", "BuilderSans:700"),
          ("BuilderSans", 700, "Normal"))
    check("Font 名稱粗細+斜體", v("TextLabel", "FontFace", "BuilderSans:bold:italic"),
          ("BuilderSans", 700, "Italic"))

    check("enum 名稱", v("UIListLayout", "FillDirection", "Vertical"), "Vertical")
    check("enum 大小寫不拘", v("UIListLayout", "FillDirection", "vertical"), "Vertical")
    check("enum 吃 Enum.X.Y", v("UIListLayout", "FillDirection",
                                "Enum.FillDirection.Horizontal"), "Horizontal")
    check("bool", v("ScreenGui", "ResetOnSpawn", "false"), False)
    check("Content 純數字補前綴", v("ImageLabel", "Image", "123456789"),
          "rbxassetid://123456789")
    check("ColorSequence", v("UIGradient", "Color", "0 #FF0000, 1 #0000FF"),
          [(0.0, (1.0, 0.0, 0.0)), (1.0, (0.0, 0.0, 1.0))])

    # 該擋的要擋
    check_raises("Frame 沒有 Text", v, "Frame", "Text", "hi")
    check_raises("enum 打錯", v, "UIListLayout", "FillDirection", "Vertikal")
    check_raises("UDim2 亂寫", v, "Frame", "Size", "abc")
    check_raises("屬性名打錯", v, "Frame", "BackgroudColor3", "#fff")

    # 打錯時要給得出建議,不然報錯也沒用
    check_in("漏字有建議", "TextSize", coerce.suggest("TextLabel", "TxtSize"))
    check_in("拼錯有建議", "BackgroundColor3", coerce.suggest("Frame", "BackgroudColor3"))
    try:
        v("UIListLayout", "FillDirection", "Vertikal")
    except coerce.CoerceError as exc:
        check_in("enum 錯誤訊息列出合法值", "Vertical", str(exc))


# ---------------------------------------------------------------------------
# 2. spec —— .gui 讀寫來回
# ---------------------------------------------------------------------------

SPEC_TEXT = """ScreenGui Shop
  IgnoreGuiInset: true
  ResetOnSpawn: false
  Frame Panel
    AnchorPoint: 0.5,0.5
    BackgroundColor3: #1E1E28
    BorderSizePixel: 0
    Position: {0.5,0}{0.5,0}
    Size: {0.5,0}{0.6,0}
    UICorner
      CornerRadius: {0,12}
    TextLabel Title
      BackgroundTransparency: 1
      FontFace: BuilderSans:700
      Size: {1,0}{0,48}
      Text: SHOP
      TextColor3: #FFFFFF
      TextSize: 28
      TextXAlignment: Left
"""


def test_spec():
    nodes = spec.parse_text(SPEC_TEXT)
    check("spec 頂層數", len(nodes), 1)
    check("spec 根 class", nodes[0].class_name, "ScreenGui")
    check("spec 根名字", nodes[0].name, "Shop")
    check("省略名字時 Name = ClassName",
          nodes[0].children[0].children[0].name, "UICorner")

    d1 = spec.dump(nodes)
    check("dump 冪等", spec.dump(spec.parse_text(d1)), d1)

    # 繞一圈 XML 再回來,要逐字相同 —— 這條顧住的是 emit/parse 兩邊的型別對稱
    path = os.path.join(TMP, "spec_rt.rbxmx")
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(emit.document_xml(nodes))
    back = spec.dump(parse.load(path).children)
    check("經過 XML 後逐字相同", back, d1)

    # 差異序列化:預設值不該被寫出來
    check("預設值不寫進 spec", "FillDirection: Vertical" in
          spec.dump(spec.parse_text("UIListLayout\n  FillDirection: Vertical\n")), False)

    # 語法錯誤要指出行號
    check_raises("屬性沒有所屬物件", spec.parse_text, "  Size: 100px\n")
    check_raises("tab 縮排", spec.parse_text, "Frame A\n\tSize: 100px\n")
    check_raises("不存在的 class", spec.parse_text, "Fram A\n")

    # 引號名字與特殊字元
    n = spec.parse_text('Frame "My Panel"\n  Size: 100px\n')[0]
    check("引號名字", n.name, "My Panel")
    esc = spec.parse_text('TextLabel A\n  Text: "a & b < c"\n')[0]
    check("特殊字元讀進來", esc.props["Text"], "a & b < c")
    check_in("特殊字元寫出去有跳脫", "&amp;", emit.prop_xml("Text", "a & b < c"))
    check_in("角括號有跳脫", "&lt;", emit.prop_xml("Text", "a & b < c"))


# ---------------------------------------------------------------------------
# 3. splice —— 位元組手術
# ---------------------------------------------------------------------------


def test_splice_props_only():
    """改屬性只能碰 <Properties>,子物件一個 byte 都不准動。"""
    src = write_fixture("fx_props.rbxlx")
    before = read_bytes(src)

    root = parse.load(src, keep_all=True)
    changes = ops.apply_ops(root, [
        {"op": "set", "path": "Shop.Panel", "props": {"BackgroundColor3": "#FF0000"}},
    ])
    doc = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc, changes)
    after = doc.rendered()

    check("只有一個改動", len(doc._edits), 1)
    s, e, _p = doc._edits[0]
    check("動到的是 Properties 而不是整個 Item",
          before[s:s + 12], b"<Properties>")
    check("改動範圍外的位元組沒變",
          splice.untouched_outside(before, after, [(s, e)]), True)
    check_in("LocalScript 還在", b'print("keep me")', after)
    check_in("Meta 還在", b'<Meta name="ExplicitAutoJoints">true</Meta>', after)
    check("Item 數不變", after.count(b"<Item class="), before.count(b"<Item class="))


def test_splice_insert_delete():
    src = write_fixture("fx_ins.rbxlx")
    before = read_bytes(src)

    root = parse.load(src, keep_all=True)
    changes = ops.apply_ops(root, [
        {"op": "insert", "parent": "Shop.Panel", "class": "UICorner",
         "props": {"CornerRadius": "16px"}},
        {"op": "insert", "parent": "Shop.Panel", "class": "UIStroke",
         "props": {"Color": "#FFAA00", "Thickness": 2}},
    ])
    doc = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc, changes)
    after = doc.rendered()

    check("插入後 Item +2",
          after.count(b"<Item class="), before.count(b"<Item class=") + 2)
    check_in("LocalScript 還在", b'print("keep me")', after)

    refs = splice.all_referents(after)
    check("referent 沒撞號", len(refs), after.count(b"referent=\""))
    check_in("新節點有拿到號", "RUIS1", refs)
    check_in("第二個新節點號不一樣", "RUIS2", refs)
    check_in("圓角寫成四個角", b'name="TopLeftRadius"', after)
    check("不寫 legacy 的 CornerRadius", b'name="CornerRadius"' in after, False)

    # 刪除
    root2 = parse.load(src, keep_all=True)
    ch2 = ops.apply_ops(root2, [{"op": "delete", "path": "Shop.Panel.Row[1]"}])
    doc2 = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc2, ch2)
    after2 = doc2.rendered()
    check("刪掉後 Item -1",
          after2.count(b"<Item class="), before.count(b"<Item class=") - 1)
    check("同名兄弟只刪掉一個", after2.count(b">Row<"), 1)


def test_splice_move_reorder():
    """搬家是原位元組搬運;重排要看得到被剪枝的 LocalScript。"""
    src = write_fixture("fx_mv.rbxlx")

    root = parse.load(src, keep_all=True)
    changes = ops.apply_ops(root, [
        {"op": "move", "path": "Shop.ShopClient", "to": "Shop.Panel"},
    ])
    doc = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc, changes)
    after = doc.rendered()
    check_in("搬家後 Source 完好", b'print("keep me")', after)
    check("搬家後 Item 數不變", after.count(b"<Item class="),
          read_bytes(src).count(b"<Item class="))
    # 真的換了父節點:LocalScript 現在在 Panel 裡面
    panel_start = after.index(b'referent="T3"')
    check("LocalScript 跑到 Panel 底下", after.index(b"ShopClient") > panel_start, True)

    # 重排:只點名 GUI 子物件,LocalScript 沒被點到也不能消失
    root2 = parse.load(src, keep_all=True)
    ch2 = ops.apply_ops(root2, [
        {"op": "move", "path": "Shop.ShopClient", "to": "Shop.Panel"},
        {"op": "reorder", "parent": "Shop.Panel", "order": ["Row"]},
    ])
    doc2 = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc2, ch2)
    after2 = doc2.rendered()
    check_in("重排後 LocalScript 還在", b'print("keep me")', after2)
    check("重排後 Item 數不變", after2.count(b"<Item class="),
          read_bytes(src).count(b"<Item class="))


def test_replace_warns():
    """--replace 會弄丟非 GUI 子物件 —— 至少要警告。"""
    src = write_fixture("fx_rep.rbxlx")
    root = parse.load(src, keep_all=True)
    nodes = spec.parse_text("ScreenGui Shop\n  IgnoreGuiInset: true\n")
    changes = ops.merge_spec(root, nodes, at="StarterGui", replace=True)
    doc = sculptor.open_document(src, verbose=False)
    _n, warns = sculptor.apply_changes(doc, changes)
    check("整段取代有警告", len(warns) >= 1, True)


def test_path_addressing():
    src = write_fixture("fx_path.rbxlx")
    root = parse.load(src, keep_all=True)

    check("絕對路徑", ops.resolve_one(root, "StarterGui.Shop.Panel").class_name, "Frame")
    check("尾綴比對", ops.resolve_one(root, "Shop.Panel").name, "Panel")
    check("[n] 選同名兄弟",
          ops.resolve_one(root, "Shop.Panel.Row[1]").props.get("Position"),
          (0.0, 0.0, 0.0, 50.0))
    check("#Class 限定",
          ops.resolve_one(root, "Shop.Panel#Frame").name, "Panel")
    check_raises("同名兄弟不指定就報錯", ops.resolve_one, root, "Shop.Panel.Row")
    check_raises("路徑不存在", ops.resolve_one, root, "Shop.NoSuchThing")

    try:
        ops.resolve_one(root, "Shop.Panel.Row")
    except ops.OpError as exc:
        check_in("命中多個時列出候選", "Row", str(exc))


def test_merge_keeps_unmentioned():
    """預設是合併:spec 沒提到的屬性不能被清掉。"""
    src = write_fixture("fx_merge.rbxlx")
    root = parse.load(src, keep_all=True)
    nodes = spec.parse_text(
        "Frame Panel\n  BackgroundColor3: #00FF00\n")
    ops.merge_spec(root, nodes, at="Shop")
    panel = ops.resolve_one(root, "Shop.Panel")
    check("有提到的改了", panel.props["BackgroundColor3"], (0.0, 1.0, 0.0))
    check("沒提到的還在", panel.props["Size"], (0.0, 400.0, 0.0, 300.0))
    check("子物件沒被清掉", len(panel.children), 2)


# ---------------------------------------------------------------------------
# 4. 像素 —— 改完真的長那樣
# ---------------------------------------------------------------------------


def test_pixels():
    src = write_fixture("fx_px.rbxlx")
    out = os.path.join(TMP, "fx_px_out.rbxlx")

    root = parse.load(src, keep_all=True)
    changes = ops.apply_ops(root, [
        {"op": "set", "path": "Shop.Panel", "props": {"BackgroundColor3": "#FF0000"}},
        {"op": "insert", "parent": "Shop.Panel", "class": "UICorner",
         "props": {"CornerRadius": "20px"}},
    ])
    doc = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc, changes)
    doc.save(out, verbose=False)

    img_before = _render(src)
    img_after = _render(out)

    # Panel 在 (100,50) 400x300;ScreenGui IgnoreGuiInset=true 所以沒有 36px 位移
    check("改之前是黑的", img_before.getpixel((300, 200)), (0, 0, 0))
    check("改之後是紅的", img_after.getpixel((300, 200)), (255, 0, 0))
    check("圓角把左上角切掉了", sum(img_after.getpixel((101, 51))) < 60, True)
    check("沒切到的邊還在", img_after.getpixel((300, 51)), (255, 0, 0))

    changed, total = compare.changed_pixels(img_before, img_after)
    check("變動像素數合理(400x300 的框)", 100000 < changed < 130000, True)

    side = compare.side_by_side(img_before, img_after, diff=True)
    check("對照圖是三格寬", side.width, img_before.width * 3 + 16 * 2)


def _render(path):
    root = parse.load(path)
    gui = parse.find_guis(root)[0]
    boxes = layout.Engine(viewport=(1280, 720)).run(gui)
    img = render.Renderer((1280, 720), background="black").render(boxes)
    return img.convert("RGB")      # 背景是 black 時 alpha 恆為 255,比對用不到


def test_props_merge_preserves_unreadable():
    """★ 回歸:改一個屬性不能弄壞 parse.load() 讀不回來的那些屬性。

    `parse.load()` 刻意有損:`<BinaryString>`(Attributes、Tags)整個跳過、
    `<Ref>` 只留字串、`ProtectedString` 跟 `string` 分不出來。
    以前 sculptor 是整塊重寫 `<Properties>`,結果:
      改一個背景色 -> AttributesSerialize 整個消失、NextSelectionUp 從
      `<Ref>` 變成 `<string>`(指標壞掉)、腳本 Source 的 ProtectedString
      被降級成 string。而且**畫面看起來一模一樣**。
    現在改成逐項併回既有位元組。
    """
    src = write_fixture("fx_lossy.rbxlx", LOSSY_FIXTURE)
    before = read_bytes(src)

    root = parse.load(src, keep_all=True)
    changes = ops.apply_ops(root, [
        {"op": "set", "path": "Shop.Panel", "props": {"BackgroundColor3": "#FF0000"}},
    ])
    doc = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc, changes)
    after = doc.rendered()

    check_in("BinaryString 屬性活著", b'<BinaryString name="AttributesSerialize">', after)
    check_in("BinaryString 的內容沒變", b"AQAAAAYAAABNeUtleQMAAAAA4HNA", after)
    check_in("Ref 還是 Ref", b'<Ref name="NextSelectionUp">A3</Ref>', after)
    check("沒有把 Ref 寫成 string", b'<string name="NextSelectionUp"' in after, False)
    check_in("要改的那個真的改了", b'name="BackgroundColor3">4294901760<', after)
    check("原本就有的屬性數量沒少",
          after.count(b" name=\"") >= before.count(b" name=\""), True)

    # 改腳本的名字不能動到 Source,連序列化型別都要保住
    root2 = parse.load(src, keep_all=True)
    ch2 = ops.apply_ops(root2, [{"op": "rename", "path": "Shop.Client", "to": "Renamed"}])
    doc2 = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc2, ch2)
    after2 = doc2.rendered()
    check_in("改名後 Source 還在", b'print("keep me")', after2)
    check_in("Source 還是 ProtectedString", b'<ProtectedString name="Source">', after2)
    check_in("名字真的改了", b">Renamed<", after2)


LOSSY_FIXTURE = """<roblox version="4">
  <Item class="StarterGui" referent="A0">
    <Properties><string name="Name">StarterGui</string></Properties>
    <Item class="ScreenGui" referent="A1">
      <Properties><string name="Name">Shop</string></Properties>
      <Item class="LocalScript" referent="A4">
        <Properties><string name="Name">Client</string><ProtectedString name="Source">print("keep me")</ProtectedString></Properties>
      </Item>
      <Item class="Frame" referent="A2">
        <Properties>
          <string name="Name">Panel</string>
          <BinaryString name="AttributesSerialize">AQAAAAYAAABNeUtleQMAAAAA4HNA</BinaryString>
          <Ref name="NextSelectionUp">A3</Ref>
          <UDim2 name="Size"><XS>0</XS><XO>400</XO><YS>0</YS><YO>300</YO></UDim2>
          <int name="BorderSizePixel">0</int>
        </Properties>
      </Item>
      <Item class="Frame" referent="A3">
        <Properties><string name="Name">Other</string><int name="BorderSizePixel">0</int></Properties>
      </Item>
    </Item>
  </Item>
</roblox>
"""


def test_self_closing_item():
    """回歸:自閉合的 `<Item …/>` 沒有配對的 </Item>,深度計數會一路吃到祖先。"""
    src = write_fixture("fx_selfclose.rbxlx", SELF_CLOSE_FIXTURE)
    data = read_bytes(src)

    s, e = splice.find_item_span(data, "S2")
    seg = data[s:e]
    check("自閉合 Item 的區間只有它自己", seg.endswith(b"/>"), True)
    check("沒有吃到父節點", b"</Item>" in seg, False)
    check_in("抓到的就是那個 Item", b'referent="S2"', seg)

    # 刪掉它不能連父節點一起刪
    root = parse.load(src, keep_all=True)
    changes = ops.apply_ops(root, [{"op": "delete", "path": "Shop.Folder"}])
    doc = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc, changes)
    after = doc.rendered()
    check("刪掉自閉合 Item 後只少一個",
          after.count(b"<Item"), data.count(b"<Item") - 1)
    check_in("兄弟還在", b'referent="S3"', after)
    check_in("父節點還在", b'referent="S1"', after)


SELF_CLOSE_FIXTURE = """<roblox version="4">
  <Item class="StarterGui" referent="S0">
    <Properties><string name="Name">StarterGui</string></Properties>
    <Item class="ScreenGui" referent="S1">
      <Properties><string name="Name">Shop</string></Properties>
      <Item class="Folder" referent="S2"/>
      <Item class="Frame" referent="S3">
        <Properties>
          <string name="Name">Panel</string>
          <UDim2 name="Size"><XS>0</XS><XO>400</XO><YS>0</YS><YO>300</YO></UDim2>
          <int name="BorderSizePixel">0</int>
        </Properties>
      </Item>
    </Item>
  </Item>
</roblox>
"""


def test_overlap_detection_scans_all():
    """回歸:`_overlaps` 碰到「同一點的零寬插入」時是 `return False` 而不是
    `continue`,於是**整個迴圈提早結束**,排在後面的待辦根本沒被檢查到。

    要踩到它,查詢本身也得是零寬、而且跟第一筆待辦同點,同時另有一筆
    範圍待辦真的包住那個點。
    """
    src = write_fixture("fx_ovl.rbxlx")
    doc = sculptor.open_document(src, verbose=False)
    a, b = splice.find_properties_span(doc.data, "T3")
    point = (a + b) // 2                       # 落在那段範圍**裡面**

    doc._edits.append((point, point, b""))     # 同點的零寬插入,排在最前面
    doc._edits.append((a, b, b"X"))            # 真正會撞的那一筆,排在後面
    check("零寬插入不能讓後面的待辦被跳過檢查",
          doc._overlaps(point, point), True)


def test_reorder_without_referents():
    """回歸:沒有 referent= 的子物件會全部撞成同一個 None 鍵,複製一個、弄丟其他。"""
    src = write_fixture("fx_noref.rbxlx", NO_REF_FIXTURE)
    data = read_bytes(src)
    spans = splice.direct_children_spans(data, "R1")
    check("三個直接子物件", len(spans), 3)
    check("其中兩個沒有 referent",
          sum(1 for r, _s, _e in spans if r is None), 2)

    doc = splice.Document(src)
    doc.reorder_children("R1", ["R2"])
    after = doc.rendered()
    check("重排後 Item 數不變", after.count(b"<Item"), data.count(b"<Item"))
    check("沒有名字被複製", after.count(b">NoRefA<"), 1)
    check_in("另一個沒有被弄丟", b">NoRefB<", after)


NO_REF_FIXTURE = """<roblox version="4">
  <Item class="ScreenGui" referent="R1">
    <Properties><string name="Name">Shop</string></Properties>
    <Item class="Frame">
      <Properties><string name="Name">NoRefA</string><int name="BorderSizePixel">0</int></Properties>
    </Item>
    <Item class="Frame" referent="R2">
      <Properties><string name="Name">Tagged</string><int name="BorderSizePixel">0</int></Properties>
    </Item>
    <Item class="Frame">
      <Properties><string name="Name">NoRefB</string><int name="BorderSizePixel">0</int></Properties>
    </Item>
  </Item>
</roblox>
"""


def test_dump_apply_is_noop():
    """★ 核心不變式:dump 出來、一個字都不改、再 apply,改動數必須是 0。

    這條看起來很無聊,但它是整個 dump -> 編輯 -> apply 流程可不可信的基礎 ——
    如果「什麼都沒改」都會產生假改動,那使用者就永遠分不清哪些改動是自己要的。
    實際上它一次抓到四個 bug:
      1. dump 把浮點 round 到 6 位(0.0641666… -> 0.064167),讀回來就不等了
      2. Color3 用 float32 存,== 比較會被 3.6e-8 的差判成「改了」
      3. 同名兄弟(一排 Slot)全部併進第一個,其餘的內容被丟掉
      4. UICorner 的 CornerRadius 與四角兩種表示法沒有先正規化就比
    """
    src = write_fixture("fx_noop.rbxlx", NOOP_FIXTURE)

    root = parse.load(src, keep_all=True)
    tgt = ops.resolve_one(root, "Shop")
    text = spec.dump(tgt, source_path=tgt.path)
    check_in("dump 有寫上來源路徑", "# @path ", text)

    directives = {}
    nodes = spec.parse_text(text, directives=directives)
    check("@path 被讀出來", directives.get("path"), tgt.path)

    root2 = parse.load(src, keep_all=True)
    changes = ops.merge_spec(root2, nodes, target_path=directives.get("path"))
    check("dump -> 原封不動 apply = 零改動", len(changes), 0)
    if changes:
        for c in changes[:5]:
            FAILURES.append("    多出來的改動: " + c.detail)

    # 只改一個屬性,就應該只有一項改動
    text2 = text.replace("BackgroundColor3: #000000", "BackgroundColor3: #FF0000", 1)
    root3 = parse.load(src, keep_all=True)
    ch3 = ops.merge_spec(root3, spec.parse_text(text2),
                         target_path=directives.get("path"))
    check("改一個屬性就只有一項改動", len(ch3), 1)


# 同名兄弟 + 四角圓角 + 難搞的浮點,三個坑各一個
NOOP_FIXTURE = """<roblox version="4">
  <Item class="StarterGui" referent="N0">
    <Properties><string name="Name">StarterGui</string></Properties>
    <Item class="ScreenGui" referent="N1">
      <Properties><string name="Name">Shop</string></Properties>
      <Item class="Frame" referent="N2">
        <Properties>
          <string name="Name">Panel</string>
          <Color3uint8 name="BackgroundColor3">4278190080</Color3uint8>
          <UDim2 name="Position"><XS>0.49878</XS><XO>0</XO><YS>0.0641666</YS><YO>0</YO></UDim2>
          <UDim2 name="Size"><XS>0.425631</XS><XO>0</XO><YS>0.742835</YS><YO>0</YO></UDim2>
          <int name="BorderSizePixel">0</int>
        </Properties>
        <Item class="UICorner" referent="N3">
          <Properties>
            <string name="Name">UICorner</string>
            <UDim name="TopLeftRadius"><S>0</S><O>3</O></UDim>
            <UDim name="TopRightRadius"><S>0</S><O>3</O></UDim>
            <UDim name="BottomLeftRadius"><S>0</S><O>3</O></UDim>
            <UDim name="BottomRightRadius"><S>0</S><O>3</O></UDim>
          </Properties>
        </Item>
        <Item class="Frame" referent="N4">
          <Properties>
            <string name="Name">Slot</string>
            <Color3 name="BackgroundColor3"><R>0.2352941334247589</R><G>0.41568630933761597</G><B>1</B></Color3>
            <int name="BorderSizePixel">0</int>
          </Properties>
        </Item>
        <Item class="Frame" referent="N5">
          <Properties>
            <string name="Name">Slot</string>
            <Color3 name="BackgroundColor3"><R>1</R><G>0.41568630933761597</G><B>0.2352941334247589</B></Color3>
            <int name="BorderSizePixel">0</int>
          </Properties>
        </Item>
        <Item class="Frame" referent="N6">
          <Properties>
            <string name="Name">Slot</string>
            <float name="BackgroundTransparency">0.35</float>
            <int name="BorderSizePixel">0</int>
          </Properties>
        </Item>
      </Item>
    </Item>
  </Item>
</roblox>
"""


def test_cjk_text():
    """回歸:Roblox 內建字型沒有中日韓字符,不 fallback 的話中文全是豆腐。"""
    from ruip import fonts, text as textmod

    check("認得中文", fonts.has_cjk("商店"), True)
    check("認得日文", fonts.has_cjk("ショップ"), True)
    check("純英文不誤判", fonts.has_cjk("SHOP"), False)

    face = ("BuilderSans", 400, "Normal")
    latin = fonts.get_for_text(face, 28, "SHOP")
    cjk = fonts.get_for_text(face, 28, "商店")
    check("中文換了別的字型", latin.path != cjk.path, True)

    # 真的畫出來要有墨:豆腐也有墨,所以比對「寬度不是 .notdef 的等寬」
    runs = textmod.runs_from("商店", False)
    _lines, w, _h = textmod.layout(runs, face, 28, 1000, False)
    check("中文有量到寬度", w > 20, True)

    src = write_fixture("fx_cjk.rbxlx")
    root = parse.load(src, keep_all=True)
    changes = ops.apply_ops(root, [
        {"op": "insert", "parent": "Shop.Panel", "class": "TextLabel", "name": "CN",
         "props": {"Size": "{1,0}{0,40}", "Text": "商店 & <特價>",
                   "TextColor3": "white", "TextSize": 24, "BackgroundTransparency": 1}},
    ])
    doc = sculptor.open_document(src, verbose=False)
    sculptor.apply_changes(doc, changes)
    out = os.path.join(TMP, "fx_cjk_out.rbxlx")
    doc.save(out, verbose=False)
    back = parse.load(out, keep_all=True)
    check("中文與特殊字元 round-trip",
          ops.resolve_one(back, "Shop.Panel.CN").props["Text"], "商店 & <特價>")


def test_corner_radius_reads_four_corners():
    """回歸:現代 Roblox 寫的是四個角,只讀 CornerRadius 會全部變成預設 8px。"""
    xml = FIXTURE_XML.replace(
        '<Item class="Frame" referent="T4">\n          <Properties>\n'
        '            <string name="Name">Row</string>',
        '<Item class="Frame" referent="T4">\n          <Properties>\n'
        '            <string name="Name">Row</string>')
    path = write_fixture("fx_corner.rbxlx", xml)
    root = parse.load(path, keep_all=True)
    panel = ops.resolve_one(root, "Shop.Panel")

    corner = parse.Node("UICorner")
    corner.name = "UICorner"
    corner.props = {"TopLeftRadius": (0.0, 16.0), "TopRightRadius": (0.0, 16.0),
                    "BottomLeftRadius": (0.0, 16.0), "BottomRightRadius": (0.0, 16.0)}
    corner.parent = panel
    panel.children.append(corner)

    eng = layout.Engine(viewport=(1280, 720))
    check("四角寫 16 就要算成 16(不是預設的 8)",
          eng._corner_radius(panel, 400, 300), 16.0)

    corner.props = {"CornerRadius": (0.0, 4.0)}
    check("只有 legacy CornerRadius 時也要讀得到",
          eng._corner_radius(panel, 400, 300), 4.0)


# ---------------------------------------------------------------------------


def main():
    global TMP
    TMP = tempfile.mkdtemp(prefix="ruis_test_")
    try:
        test_coerce()
        test_spec()
        test_splice_props_only()
        test_splice_insert_delete()
        test_splice_move_reorder()
        test_replace_warns()
        test_path_addressing()
        test_merge_keeps_unmentioned()
        test_pixels()
        test_props_merge_preserves_unreadable()
        test_self_closing_item()
        test_overlap_detection_scans_all()
        test_reorder_without_referents()
        test_dump_apply_is_noop()
        test_cjk_text()
        test_corner_radius_reads_four_corners()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

    print("%d 過 / %d 敗" % (PASS, FAIL))
    if FAILURES:
        for f in FAILURES:
            print("  " + f)
        return 1
    print("全綠。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
