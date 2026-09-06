"""GUI 類別的屬性預設值。

**這張表是整個工具正確性的基礎。** Roblox 的 XML 序列化只寫「跟預設值不同」的屬性,
所以 `<Item class="UICorner">` 裡面沒有 CornerRadius **不代表半徑是 0**,
而是它就是預設的 `UDim(0, 8)`。少一條就會整片位移或整個元素消失。

值的表示法跟 parse.py 產出的一致:
  UDim2 -> (xs, xo, ys, yo)   UDim -> (s, o)   Vector2 -> (x, y)
  Color3 -> (r, g, b) 0..1    Rect  -> (x0, y0, x1, y1)
  enum   -> 名稱字串(不是 token 整數)
"""

WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)
# Color3.fromRGB(163, 162, 165) — GuiObject 的預設灰底
DEFAULT_BG = (163 / 255, 162 / 255, 165 / 255)
# Color3.fromRGB(27, 42, 53) — 預設邊框色 / 文字色
DEFAULT_BORDER = (27 / 255, 42 / 255, 53 / 255)

# 每個 GuiObject 都有的
GUI_OBJECT = {
    "AnchorPoint": (0.0, 0.0),
    "AutomaticSize": "None",
    "BackgroundColor3": DEFAULT_BG,
    "BackgroundTransparency": 0.0,
    "BorderColor3": DEFAULT_BORDER,
    "BorderMode": "Outline",
    "BorderSizePixel": 1,
    "ClipsDescendants": False,
    "LayoutOrder": 0,
    "Position": (0.0, 0.0, 0.0, 0.0),
    "Rotation": 0.0,
    "Size": (0.0, 0.0, 0.0, 0.0),
    "SizeConstraint": "RelativeXY",
    "Visible": True,
    "ZIndex": 1,
}

TEXT_COMMON = {
    "FontFace": ("SourceSansPro", 400, "Normal"),
    "LineHeight": 1.0,
    "MaxVisibleGraphemes": -1,
    "RichText": False,
    "TextColor3": DEFAULT_BORDER,
    "TextDirection": "Auto",
    "TextScaled": False,
    "TextSize": 14.0,
    "TextStrokeColor3": BLACK,
    "TextStrokeTransparency": 1.0,
    "TextTransparency": 0.0,
    "TextTruncate": "None",
    "TextWrapped": False,
    "TextXAlignment": "Center",
    "TextYAlignment": "Center",
}

IMAGE_COMMON = {
    "Image": "",
    "ImageColor3": WHITE,
    "ImageRectOffset": (0.0, 0.0),
    "ImageRectSize": (0.0, 0.0),
    "ImageTransparency": 0.0,
    "ScaleType": "Stretch",
    "SliceCenter": (0, 0, 0, 0),
    "SliceScale": 1.0,
    "TileSize": (1.0, 0.0, 1.0, 0.0),
}

CLASS_DEFAULTS = {
    "Frame": {},
    "TextLabel": dict(TEXT_COMMON, Text="Label"),
    "TextButton": dict(TEXT_COMMON, Text="Button", AutoButtonColor=True),
    "TextBox": dict(
        TEXT_COMMON,
        Text="TextBox",
        PlaceholderText="",
        PlaceholderColor3=(178 / 255, 178 / 255, 178 / 255),
        ClearTextOnFocus=True,
    ),
    "ImageLabel": dict(IMAGE_COMMON),
    "ImageButton": dict(IMAGE_COMMON, AutoButtonColor=True, HoverImage="", PressedImage=""),
    "ScrollingFrame": {
        "CanvasSize": (0.0, 0.0, 2.0, 0.0),
        "CanvasPosition": (0.0, 0.0),
        "AutomaticCanvasSize": "None",
        "ScrollBarThickness": 12,
        "ScrollBarImageColor3": BLACK,
        "ScrollBarImageTransparency": 0.0,
        "ScrollingDirection": "XY",
        "ScrollingEnabled": True,
        "HorizontalScrollBarInset": "None",
        "VerticalScrollBarInset": "None",
        "VerticalScrollBarPosition": "Right",
        "MidImage": "rbxasset://textures/ui/Scroll/scroll-middle.png",
    },
    "CanvasGroup": {"GroupColor3": WHITE, "GroupTransparency": 0.0},
    "ViewportFrame": {
        "ImageColor3": WHITE,
        "ImageTransparency": 0.0,
        "Ambient": (0.78, 0.78, 0.78),
        "LightColor": WHITE,
    },
    "VideoFrame": {"ImageColor3": WHITE, "Volume": 1.0, "Looped": False, "Playing": False},
    # 容器 —— 沒有幾何屬性,但要有 Enabled/ZIndexBehavior
    "ScreenGui": {
        "Enabled": True,
        "IgnoreGuiInset": False,
        "ZIndexBehavior": "Sibling",
        "DisplayOrder": 0,
        "ScreenInsets": "CoreUISafeInsets",
        "ClipToDeviceSafeArea": True,
    },
    "BillboardGui": {"Enabled": True, "Size": (0.0, 0.0, 0.0, 0.0)},
    "SurfaceGui": {"Enabled": True, "ZIndexBehavior": "Sibling"},
    # 修飾物件
    # 現代 Roblox 序列化的是**四個角**,不是 CornerRadius —— 後者在 API dump 0.734
    # 已經是 `CanSave:false` 的 legacy 別名。實測 qte-trainer/QTE_Trainer.rbxlx:
    # TopLeftRadius 出現 28 次,CornerRadius 0 次。四條都要有,少了就整片圓角讀成 8px。
    "UICorner": {
        "CornerRadius": (0.0, 8.0),
        "TopLeftRadius": (0.0, 8.0),
        "TopRightRadius": (0.0, 8.0),
        "BottomLeftRadius": (0.0, 8.0),
        "BottomRightRadius": (0.0, 8.0),
    },
    "UIStroke": {
        "Color": BLACK,
        "Thickness": 1.0,
        "Transparency": 0.0,
        "ApplyStrokeMode": "Contextual",
        "LineJoinMode": "Round",
        "Enabled": True,
    },
    "UIGradient": {
        "Color": [(0.0, WHITE)],
        "Offset": (0.0, 0.0),
        "Rotation": 0.0,
        "Transparency": [(0.0, 0.0)],
        "Enabled": True,
    },
    "UIPadding": {
        "PaddingBottom": (0.0, 0.0),
        "PaddingLeft": (0.0, 0.0),
        "PaddingRight": (0.0, 0.0),
        "PaddingTop": (0.0, 0.0),
    },
    "UIListLayout": {
        "Padding": (0.0, 0.0),
        "FillDirection": "Vertical",
        "HorizontalAlignment": "Left",
        "VerticalAlignment": "Top",
        "SortOrder": "Name",
        "Wraps": False,
        "ItemLineAlignment": "Automatic",
        "HorizontalFlex": "None",
        "VerticalFlex": "None",
    },
    "UIGridLayout": {
        "CellPadding": (0.0, 5.0, 0.0, 5.0),
        "CellSize": (0.0, 100.0, 0.0, 100.0),
        "FillDirectionMaxCells": 0,
        "StartCorner": "TopLeft",
        "FillDirection": "Horizontal",
        "HorizontalAlignment": "Left",
        "VerticalAlignment": "Top",
        "SortOrder": "Name",
    },
    "UIPageLayout": {
        "Padding": (0.0, 0.0),
        "FillDirection": "Horizontal",
        "HorizontalAlignment": "Center",
        "VerticalAlignment": "Center",
        "SortOrder": "Name",
    },
    "UITableLayout": {
        "Padding": (0.0, 0.0, 0.0, 0.0),
        "FillDirection": "Horizontal",
        "HorizontalAlignment": "Left",
        "VerticalAlignment": "Top",
        "SortOrder": "Name",
        "FillEmptySpaceColumns": False,
        "FillEmptySpaceRows": False,
        "MajorAxis": "RowMajor",
    },
    "UIAspectRatioConstraint": {
        "AspectRatio": 1.0,
        "AspectType": "FitWithinMaxSize",
        "DominantAxis": "Width",
    },
    "UISizeConstraint": {"MinSize": (0.0, 0.0), "MaxSize": (float("inf"), float("inf"))},
    "UITextSizeConstraint": {"MinTextSize": 1, "MaxTextSize": 100},
    "UIScale": {"Scale": 1.0},
    "UIFlexItem": {"FlexMode": "None", "GrowRatio": 0.0, "ShrinkRatio": 1.0, "ItemLineAlignment": "Automatic"},
}

# 有幾何(Position/Size/…)的類別 —— 這些吃 GUI_OBJECT 那組預設
GUI_OBJECT_CLASSES = {
    "Frame",
    "TextLabel",
    "TextButton",
    "TextBox",
    "ImageLabel",
    "ImageButton",
    "ScrollingFrame",
    "CanvasGroup",
    "ViewportFrame",
    "VideoFrame",
}

TEXT_CLASSES = {"TextLabel", "TextButton", "TextBox"}
IMAGE_CLASSES = {"ImageLabel", "ImageButton"}
CONTAINER_CLASSES = {"ScreenGui", "SurfaceGui", "BillboardGui", "Folder", "GuiMain"}
# UI* 修飾物件 —— 不自己畫,只影響父物件
MODIFIER_CLASSES = {c for c in CLASS_DEFAULTS if c.startswith("UI")}


def defaults_for(class_name):
    """回傳該類別的完整預設屬性 dict(GuiObject 那組 + 類別自己那組)。"""
    out = {}
    if class_name in GUI_OBJECT_CLASSES:
        out.update(GUI_OBJECT)
    out.update(CLASS_DEFAULTS.get(class_name, {}))
    return out


def is_renderable(class_name):
    return class_name in GUI_OBJECT_CLASSES
