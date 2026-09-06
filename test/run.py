#!/usr/bin/env python3
"""正確性測試 —— 用手工組出來的 rbxmx 驗 layout 與繪製。

複雜的 place dump 只能看出「像不像」,看不出「對不對」。
這裡每個案例的正確答案都是可以手算的,座標與像素都直接斷言。

    python test/run.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ruip import layout, parse, render  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_fixture.rbxmx")

PASS = FAIL = 0
FAILURES = []


def check(label, got, want, tol=0.51):
    global PASS, FAIL
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        ok = abs(got - want) <= tol
    else:
        ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{label}: 得到 {got!r},應該是 {want!r}")


def check_rect(label, box, x, y, w, h):
    check(f"{label}.x", box.x, x)
    check(f"{label}.y", box.y, y)
    check(f"{label}.w", box.w, w)
    check(f"{label}.h", box.h, h)


# ---------------------------------------------------------------------------
# fixture 生成 —— 純字串拼 XML,跟 Roblox 自己序列化的格式一致
# ---------------------------------------------------------------------------

_ref = [0]


def item(cls, props=None, children="", name=None):
    _ref[0] += 1
    p = []
    if name is not None:
        p.append(f"<string name=\"Name\">{name}</string>")
    for k, v in (props or {}).items():
        p.append(prop(k, v))
    return (f'<Item class="{cls}" referent="RBX{_ref[0]}">'
            f'<Properties>{"".join(p)}</Properties>{children}</Item>')


def prop(name, v):
    kind, val = v
    if kind == "UDim2":
        return (f'<UDim2 name="{name}"><XS>{val[0]}</XS><XO>{val[1]}</XO>'
                f'<YS>{val[2]}</YS><YO>{val[3]}</YO></UDim2>')
    if kind == "UDim":
        return f'<UDim name="{name}"><S>{val[0]}</S><O>{val[1]}</O></UDim>'
    if kind == "Vector2":
        return f'<Vector2 name="{name}"><X>{val[0]}</X><Y>{val[1]}</Y></Vector2>'
    if kind == "Color3":
        return (f'<Color3 name="{name}"><R>{val[0]}</R><G>{val[1]}</G>'
                f'<B>{val[2]}</B></Color3>')
    if kind == "bool":
        return f'<bool name="{name}">{"true" if val else "false"}</bool>'
    if kind == "int":
        return f'<int name="{name}">{val}</int>'
    if kind == "float":
        return f'<float name="{name}">{val}</float>'
    if kind == "token":
        return f'<token name="{name}">{val}</token>'
    if kind == "string":
        return f'<string name="{name}">{val}</string>'
    raise ValueError(kind)


U2 = lambda *a: ("UDim2", a)          # noqa: E731
UD = lambda s, o: ("UDim", (s, o))    # noqa: E731
V2 = lambda x, y: ("Vector2", (x, y))  # noqa: E731
C3 = lambda r, g, b: ("Color3", (r, g, b))  # noqa: E731
B = lambda v: ("bool", v)             # noqa: E731
I = lambda v: ("int", v)              # noqa: E731
F = lambda v: ("float", v)            # noqa: E731
T = lambda v: ("token", v)            # noqa: E731
S = lambda v: ("string", v)           # noqa: E731

RED = C3(1, 0, 0)
GREEN = C3(0, 1, 0)
BLUE = C3(0, 0, 1)
OPAQUE = {"BackgroundTransparency": F(0), "BorderSizePixel": I(0)}


def build_fixture():
    _ref[0] = 0

    # 1. 基本 UDim2 + AnchorPoint
    basic = item("Frame", dict(OPAQUE, Name=S("Basic"),
                               BackgroundColor3=RED,
                               Position=U2(0.5, 10, 0.25, -5),
                               Size=U2(0.25, 20, 0, 100),
                               AnchorPoint=V2(0.5, 0.5)), name="Basic")

    # 2. UIListLayout 垂直 + 置中 + padding 8
    list_kids = "".join(
        item("Frame", dict(OPAQUE, BackgroundColor3=GREEN,
                           Size=U2(0, 60, 0, 30),
                           LayoutOrder=I(3 - i)), name=f"Item{i}")
        for i in range(3))
    listframe = item("Frame", dict(OPAQUE, BackgroundColor3=BLUE,
                                   Position=U2(0, 0, 0, 0),
                                   Size=U2(0, 200, 0, 200)),
                     children=item("UIListLayout", {
                         "Padding": UD(0, 8),
                         "FillDirection": T(1),          # Vertical
                         "HorizontalAlignment": T(0),    # Center
                         "VerticalAlignment": T(0),      # Center
                         "SortOrder": T(2),              # LayoutOrder
                     }) + list_kids,
                     name="ListFrame")

    # 3. UIPadding + 子元素填滿
    padded = item("Frame", dict(OPAQUE, BackgroundColor3=RED,
                                Position=U2(0, 300, 0, 0),
                                Size=U2(0, 100, 0, 100)),
                  children=item("UIPadding", {
                      "PaddingLeft": UD(0, 10), "PaddingTop": UD(0, 20),
                      "PaddingRight": UD(0, 30), "PaddingBottom": UD(0, 40),
                  }) + item("Frame", dict(OPAQUE, BackgroundColor3=GREEN,
                                          Size=U2(1, 0, 1, 0)), name="Inner"),
                  name="Padded")

    # 4. UICorner 不給 CornerRadius —— 應該吃預設的 8px
    corner = item("Frame", dict(OPAQUE, BackgroundColor3=GREEN,
                                Position=U2(0, 450, 0, 0),
                                Size=U2(0, 100, 0, 100)),
                  children=item("UICorner"), name="Corner")

    # 5. ClipsDescendants
    clipped = item("Frame", dict(OPAQUE, BackgroundColor3=BLUE,
                                 Position=U2(0, 600, 0, 0),
                                 Size=U2(0, 100, 0, 100),
                                 ClipsDescendants=B(True)),
                   children=item("Frame", dict(OPAQUE, BackgroundColor3=RED,
                                               Position=U2(0, 50, 0, 50),
                                               Size=U2(0, 200, 0, 200)),
                                 name="Overflow"),
                   name="Clipped")

    # 6. ZIndex —— 文件順序在前但 ZIndex 高,應該蓋在上面
    zorder = item("Frame", dict(OPAQUE, BackgroundColor3=C3(0, 0, 0),
                                Position=U2(0, 750, 0, 0),
                                Size=U2(0, 100, 0, 100)),
                  children=item("Frame", dict(OPAQUE, BackgroundColor3=RED,
                                              Size=U2(1, 0, 1, 0),
                                              ZIndex=I(5)), name="Top")
                  + item("Frame", dict(OPAQUE, BackgroundColor3=GREEN,
                                       Size=U2(1, 0, 1, 0),
                                       ZIndex=I(2)), name="Bottom"),
                  name="ZOrder")

    # 7. UIAspectRatioConstraint 2:1
    aspect = item("Frame", dict(OPAQUE, BackgroundColor3=RED,
                                Position=U2(0, 0, 0, 300),
                                Size=U2(0, 200, 0, 200)),
                  children=item("UIAspectRatioConstraint", {
                      "AspectRatio": F(2.0)}),
                  name="Aspect")

    # 8. UIScale 0.5
    scaled = item("Frame", dict(OPAQUE, BackgroundColor3=GREEN,
                                Position=U2(0, 250, 0, 300),
                                Size=U2(0, 200, 0, 100)),
                  children=item("UIScale", {"Scale": F(0.5)}), name="Scaled")

    # 9. SizeConstraint RelativeYY(父 400x200 -> 兩軸都用 200)
    relyy = item("Frame", dict(OPAQUE, BackgroundColor3=BLUE,
                               Position=U2(0, 0, 0, 450),
                               Size=U2(0, 400, 0, 200)),
                 children=item("Frame", dict(OPAQUE, BackgroundColor3=RED,
                                             Size=U2(0.5, 0, 0.5, 0),
                                             SizeConstraint=T(2)), name="YY"),
                 name="RelYY")

    # 10. ScrollingFrame:CanvasPosition 會把子元素往上推
    scroll = item("ScrollingFrame", dict(OPAQUE, BackgroundColor3=C3(.2, .2, .2),
                                         Position=U2(0, 450, 0, 450),
                                         Size=U2(0, 200, 0, 200),
                                         CanvasSize=U2(0, 0, 0, 600),
                                         CanvasPosition=V2(0, 150),
                                         ScrollBarThickness=I(0)),
                  children=item("Frame", dict(OPAQUE, BackgroundColor3=GREEN,
                                              Position=U2(0, 0, 0, 200),
                                              Size=U2(1, 0, 0, 50)),
                                name="Row"),
                  name="Scroll")

    # 11. 文字對齊
    text = item("TextLabel", {
        "BackgroundTransparency": F(1), "BorderSizePixel": I(0),
        "Position": U2(0, 700, 0, 300), "Size": U2(0, 200, 0, 100),
        "Text": S("Hi"), "TextSize": F(20),
        "TextXAlignment": T(0),   # Left
        "TextYAlignment": T(0),   # Top
        "TextColor3": C3(1, 1, 1),
    }, name="TextTL")

    # 12. Visible=false 與「透明度=1」兩種看不見
    hidden = item("Frame", dict(OPAQUE, BackgroundColor3=RED,
                                Position=U2(0, 700, 0, 450),
                                Size=U2(0, 50, 0, 50),
                                Visible=B(False)), name="Hidden")
    ghost = item("TextLabel", {
        "BackgroundTransparency": F(1), "BorderSizePixel": I(0),
        "Position": U2(0, 800, 0, 450), "Size": U2(0, 50, 0, 50),
        "Text": S("ghost"), "TextTransparency": F(1),
        "TextColor3": C3(1, 1, 1)}, name="Ghost")

    # 13. UIGridLayout 3 欄
    grid_kids = "".join(
        item("Frame", dict(OPAQUE, BackgroundColor3=GREEN), name=f"Cell{i}")
        for i in range(5))
    grid = item("Frame", dict(OPAQUE, BackgroundColor3=C3(0, 0, 0),
                              Position=U2(0, 900, 0, 300),
                              Size=U2(0, 200, 0, 200)),
                children=item("UIGridLayout", {
                    "CellSize": U2(0, 60, 0, 60),
                    "CellPadding": U2(0, 10, 0, 10),
                    "SortOrder": T(2),
                }) + grid_kids, name="Grid")

    # 14. Rotation 90° —— 100x20 轉完視覺上要變成 20x100
    rotated = item("Frame", dict(OPAQUE, BackgroundColor3=RED,
                                 Position=U2(0, 1100, 0, 500),
                                 Size=U2(0, 100, 0, 20),
                                 Rotation=F(90)), name="Rotated")

    # 15. UIStroke 畫在框線外側
    stroked = item("Frame", dict(OPAQUE, BackgroundColor3=C3(0, 0, 0),
                                 Position=U2(0, 1100, 0, 200),
                                 Size=U2(0, 100, 0, 50)),
                   children=item("UIStroke", {"Color": C3(1, 1, 1),
                                              "Thickness": F(4)}),
                   name="Stroked")

    # 16. TextScaled:框放不下原本的 TextSize,要自動縮小
    tiny = item("TextLabel", {
        "BackgroundTransparency": F(1), "BorderSizePixel": I(0),
        "Position": U2(0, 1100, 0, 300), "Size": U2(0, 60, 0, 14),
        "Text": S("VERY LONG TEXT"), "TextSize": F(48),
        "TextScaled": B(True), "TextColor3": C3(1, 1, 1)}, name="TinyText")

    body = (basic + listframe + padded + corner + clipped + zorder + aspect
            + scaled + relyy + scroll + text + hidden + ghost + grid
            + rotated + stroked + tiny)
    gui = item("ScreenGui", {"Name": S("Test"), "IgnoreGuiInset": B(True),
                             "ZIndexBehavior": T(1)}, children=body)
    xml = '<roblox version="4">' + gui + "</roblox>"
    with open(FIXTURE, "w", encoding="utf-8") as fh:
        fh.write(xml)


# ---------------------------------------------------------------------------
def main():
    build_fixture()
    root = parse.load(FIXTURE)
    gui = parse.resolve(root, "Test")
    assert gui is not None, "fixture 解析失敗"

    eng = layout.Engine(viewport=(1280, 720), show_hidden=True)
    boxes = eng.run(gui)
    by = {}
    for b in boxes:
        by.setdefault(b.node.name, b)

    # --- 1. UDim2 + AnchorPoint -------------------------------------------
    # x = 0.5*1280 + 10 - 0.5*(0.25*1280+20) = 650 - 170 = 480
    # y = 0.25*720 - 5 - 0.5*100 = 175 - 50 = 125
    check_rect("Basic", by["Basic"], 480, 125, 340, 100)

    # --- 2. UIListLayout ---------------------------------------------------
    # 三個 60x30,padding 8 -> 總高 106,置中於 200 -> 起點 y=47
    # LayoutOrder 3,2,1 -> 反序:Item2, Item1, Item0
    check("List 順序", [by[f"Item{i}"].y for i in range(3)],
          [47.0 + 2 * 38, 47.0 + 38, 47.0])
    check("List 水平置中", by["Item0"].x, (200 - 60) / 2)

    # --- 3. UIPadding ------------------------------------------------------
    # 父 (300,0) 100x100,padding L10 T20 R30 B40 -> 內容區 (310,20) 60x40
    check_rect("Inner", by["Inner"], 310, 20, 60, 40)

    # --- 4. UICorner 預設值 -------------------------------------------------
    corner_node = by["Corner"].node.first_of_class("UICorner")
    check("UICorner 預設半徑", corner_node.get("CornerRadius"), (0.0, 8.0))

    # --- 5. ClipsDescendants ------------------------------------------------
    check_rect("Overflow", by["Overflow"], 650, 50, 200, 200)
    check("Overflow 有 clip", len(by["Overflow"].clips), 1)

    # --- 6. ZIndex ---------------------------------------------------------
    check("ZIndex 排序", by["Top"].order > by["Bottom"].order, True)

    # --- 7. AspectRatio 2:1 -------------------------------------------------
    check_rect("Aspect", by["Aspect"], 0, 300, 200, 100)

    # --- 8. UIScale ---------------------------------------------------------
    check_rect("Scaled", by["Scaled"], 250, 300, 100, 50)

    # --- 9. SizeConstraint RelativeYY ---------------------------------------
    check("RelativeYY 寬", by["YY"].w, 100)
    check("RelativeYY 高", by["YY"].h, 100)

    # --- 10. ScrollingFrame CanvasPosition ----------------------------------
    # 子元素在 canvas y=200,CanvasPosition.Y=150 -> 螢幕 y = 450+200-150 = 500
    check("Scroll 子元素 y", by["Row"].y, 500)
    check("Scroll 子元素寬", by["Row"].w, 200)

    # --- 11. 文字對齊 --------------------------------------------------------
    tl = by["TextTL"]
    check("文字有排版", tl.lines is not None and len(tl.lines) == 1, True)
    check("TextSize", tl.text_size, 20)

    # --- 12. 看不見的兩種 -----------------------------------------------------
    check("Visible=false", by["Hidden"].hidden_by, "self")
    check("透明度=1", by["Ghost"].invisible, "文字全透明")

    # --- 13. UIGridLayout ----------------------------------------------------
    # cell 60,pad 10 -> 每欄 70。200 寬放得下 3 欄(60+10+60+10+60=200)
    check("Grid Cell0", (by["Cell0"].x, by["Cell0"].y), (900.0, 300.0))
    check("Grid Cell1 同列", by["Cell1"].y, 300.0)
    check("Grid Cell1 右移", by["Cell1"].x, 970.0)
    check("Grid Cell3 換列", by["Cell3"].y, 370.0)
    check("Grid cell 大小", (by["Cell0"].w, by["Cell0"].h), (60.0, 60.0))

    # ---------------------------------------------------------------------
    # 像素層級:實際畫出來的顏色
    # ---------------------------------------------------------------------
    eng2 = layout.Engine(viewport=(1280, 720))
    boxes2 = eng2.run(gui)
    r = render.Renderer((1280, 720), fetcher=None, background="black")
    img = r.render(boxes2).convert("RGB")
    px = img.load()

    check("Basic 是紅的", px[600, 170], (255, 0, 0))
    check("Padded 內層是綠的", px[340, 40], (0, 255, 0))
    check("Padded 邊緣是紅的", px[305, 40], (255, 0, 0))
    check("ZIndex 高的在上面", px[800, 50], (255, 0, 0))
    check("Clip 內是紅的", px[680, 80], (255, 0, 0))
    check("Clip 外沒東西", px[720, 120], (0, 0, 0))
    # 圓角處只剩抗鋸齒的殘留,不會是純黑
    check("UICorner 角落被切掉", sum(px[451, 1]) < 40, True)
    check("UICorner 中間還在", px[500, 50], (0, 255, 0))
    check("Visible=false 沒畫", px[720, 470], (0, 0, 0))
    check("透明度=1 沒畫", px[820, 470], (0, 0, 0))
    check("Grid Cell0 是綠的", px[930, 330], (0, 255, 0))
    check("Grid 格間距是黑的", px[965, 330], (0, 0, 0))
    check("Scroll 子元素被推上去", px[550, 510], (0, 255, 0))
    # 捲動後那一列讓出來的位置,露出 ScrollingFrame 自己的底色
    check("Scroll 其餘露出底色", px[550, 640], (51, 51, 51))

    def has_ink(x0, y0, x1, y1):
        return any(px[x, y] != (0, 0, 0)
                   for y in range(y0, y1) for x in range(x0, x1))

    # --- 14. Rotation ------------------------------------------------------
    # 100x20 繞中心 (1150,510) 轉 90° -> 視覺上佔 x 1140-1160 / y 460-560
    check("旋轉後長邊變直的", px[1150, 470], (255, 0, 0))
    check("旋轉後原本的橫向位置空了", px[1110, 510], (0, 0, 0))

    # --- 15. UIStroke ------------------------------------------------------
    check("UIStroke 畫在外側", px[1098, 225], (255, 255, 255))
    check("UIStroke 內部維持底色", px[1150, 225], (0, 0, 0))

    # --- 16. TextScaled ----------------------------------------------------
    check("TextScaled 有縮小", by["TinyText"].text_size < 48, True)
    check("TextScaled 塞得進框", by["TinyText"].text_h <= 14 + 0.5, True)

    # --- 17. 文字對齊(Left/Top)---------------------------------------------
    # TextTL 在 (700,300) 200x100,對齊左上 -> 墨跡只該出現在左上角
    check("文字靠左上", has_ink(700, 300, 740, 324), True)
    check("文字沒跑到右下", has_ink(850, 370, 900, 400), False)

    if r.warnings:
        print("繪製警告:")
        for w in r.warnings:
            print("   ", w)

    # ---------------------------------------------------------------------
    print(f"\n{PASS} 過 / {FAIL} 敗")
    if FAILURES:
        print("\n失敗項目:")
        for f in FAILURES:
            print("  ✗ " + f)
        return 1
    print("全綠。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
