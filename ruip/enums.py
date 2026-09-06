"""Roblox Enum token 值 -> 名稱。

XML 裡 enum 一律序列化成 `<token name="X">整數</token>`,所以要有這張對照表
才能把數字翻回語意。只收 GUI 渲染會用到的。
"""

TEXT_X_ALIGNMENT = {0: "Left", 1: "Right", 2: "Center"}
TEXT_Y_ALIGNMENT = {0: "Top", 1: "Center", 2: "Bottom"}
TEXT_TRUNCATE = {0: "None", 1: "AtEnd", 2: "SplitWord"}
TEXT_DIRECTION = {0: "Auto", 1: "LeftToRight", 2: "RightToLeft"}

AUTOMATIC_SIZE = {0: "None", 1: "X", 2: "Y", 3: "XY"}
BORDER_MODE = {0: "Outline", 1: "Middle", 2: "Inset"}
SIZE_CONSTRAINT = {0: "RelativeXY", 1: "RelativeXX", 2: "RelativeYY"}
SCALE_TYPE = {0: "Stretch", 1: "Slice", 2: "Tile", 3: "Fit", 4: "Crop"}
Z_INDEX_BEHAVIOR = {0: "Global", 1: "Sibling"}

FILL_DIRECTION = {0: "Horizontal", 1: "Vertical"}
HORIZONTAL_ALIGNMENT = {0: "Center", 1: "Left", 2: "Right"}
VERTICAL_ALIGNMENT = {0: "Center", 1: "Top", 2: "Bottom"}
SORT_ORDER = {0: "Name", 1: "Custom", 2: "LayoutOrder"}
START_CORNER = {0: "TopLeft", 1: "TopRight", 2: "BottomLeft", 3: "BottomRight"}

APPLY_STROKE_MODE = {0: "Contextual", 1: "Border"}
LINE_JOIN_MODE = {0: "Round", 1: "Bevel", 2: "Miter"}
ASPECT_TYPE = {0: "FitWithinMaxSize", 1: "ScaleWithParentSize"}
DOMINANT_AXIS = {0: "Width", 1: "Height"}

SCROLLING_DIRECTION = {1: "X", 2: "Y", 4: "XY"}
SCROLL_BAR_INSET = {0: "None", 1: "Always", 2: "ScrollBar"}
VERTICAL_SCROLL_BAR_POSITION = {0: "Right", 1: "Left"}

UI_FLEX_MODE = {0: "None", 1: "Grow", 2: "Shrink", 3: "Fill", 4: "Custom"}
ITEM_LINE_ALIGNMENT = {0: "Automatic", 1: "Start", 2: "Center", 3: "End", 4: "Stretch"}

SCREEN_INSETS = {0: "None", 1: "DeviceSafeInsets", 2: "CoreUISafeInsets", 3: "TopbarSafeInsets"}

# 每個 GUI 屬性名 -> 它是哪個 enum。翻譯 token 時查這張表。
PROPERTY_ENUM = {
    "TextXAlignment": TEXT_X_ALIGNMENT,
    "TextYAlignment": TEXT_Y_ALIGNMENT,
    "TextTruncate": TEXT_TRUNCATE,
    "TextDirection": TEXT_DIRECTION,
    "AutomaticSize": AUTOMATIC_SIZE,
    "BorderMode": BORDER_MODE,
    "SizeConstraint": SIZE_CONSTRAINT,
    "ScaleType": SCALE_TYPE,
    "ZIndexBehavior": Z_INDEX_BEHAVIOR,
    "FillDirection": FILL_DIRECTION,
    "HorizontalAlignment": HORIZONTAL_ALIGNMENT,
    "VerticalAlignment": VERTICAL_ALIGNMENT,
    "SortOrder": SORT_ORDER,
    "StartCorner": START_CORNER,
    "ApplyStrokeMode": APPLY_STROKE_MODE,
    "LineJoinMode": LINE_JOIN_MODE,
    "AspectType": ASPECT_TYPE,
    "DominantAxis": DOMINANT_AXIS,
    "ScrollingDirection": SCROLLING_DIRECTION,
    "HorizontalScrollBarInset": SCROLL_BAR_INSET,
    "VerticalScrollBarInset": SCROLL_BAR_INSET,
    "VerticalScrollBarPosition": VERTICAL_SCROLL_BAR_POSITION,
    "HorizontalFlex": UI_FLEX_MODE,
    "VerticalFlex": UI_FLEX_MODE,
    "FlexMode": UI_FLEX_MODE,
    "ItemLineAlignment": ITEM_LINE_ALIGNMENT,
    "ScreenInsets": SCREEN_INSETS,
    "AutomaticCanvasSize": AUTOMATIC_SIZE,
}

# 舊的 GuiObject.Font (Enum.Font) -> (family json 名, weight, italic)。
# 新版 Roblox 已改用 FontFace,但大量舊 UI 仍序列化 Font token。
LEGACY_FONT = {
    0: ("LegacyArial", 400, False),   # Legacy
    1: ("LegacyArial", 400, False),   # Arial
    2: ("LegacyArial", 700, False),   # ArialBold
    3: ("SourceSansPro", 400, False),  # SourceSans
    4: ("SourceSansPro", 700, False),  # SourceSansBold
    5: ("SourceSansPro", 300, False),  # SourceSansLight
    6: ("SourceSansPro", 400, True),   # SourceSansItalic
    7: ("AccanthisADFStd", 400, False),  # Bodoni
    8: ("Guru", 400, False),          # Garamond
    9: ("ComicNeueAngular", 700, False),  # Cartoon
    10: ("Inconsolata", 400, False),  # Code
    11: ("HighwayGothic", 400, False),  # Highway
    12: ("Zekton", 400, False),       # SciFi
    13: ("PressStart2P", 400, False),  # Arcade
    14: ("Balthazar", 400, False),    # Fantasy
    15: ("RomanAntique", 400, False),  # Antique
    16: ("SourceSansPro", 600, False),  # SourceSansSemibold
    17: ("BuilderSans", 400, False),  # Gotham (現已對應 BuilderSans)
    18: ("BuilderSans", 500, False),  # GothamMedium
    19: ("BuilderSans", 700, False),  # GothamBold
    20: ("BuilderSans", 800, False),  # GothamBlack
    21: ("AmaticSC", 400, False),
    22: ("Bangers", 400, False),
    23: ("Creepster", 400, False),
    24: ("DenkOne", 400, False),
    25: ("Fondamento", 400, False),
    26: ("FredokaOne", 400, False),
    27: ("GrenzeGotisch", 400, False),
    28: ("IndieFlower", 400, False),
    29: ("JosefinSans", 400, False),
    30: ("Jura", 400, False),
    31: ("Kalam", 400, False),
    32: ("LuckiestGuy", 400, False),
    33: ("Merriweather", 400, False),
    34: ("Michroma", 400, False),
    35: ("Nunito", 400, False),
    36: ("Oswald", 400, False),
    37: ("PatrickHand", 400, False),
    38: ("PermanentMarker", 400, False),
    39: ("Roboto", 400, False),
    40: ("RobotoCondensed", 400, False),
    41: ("RobotoMono", 400, False),
    42: ("Sarpanch", 400, False),
    43: ("SpecialElite", 400, False),
    44: ("TitilliumWeb", 400, False),
    45: ("Ubuntu", 400, False),
    46: ("SourceSansPro", 400, False),  # Unknown
    47: ("BuilderSans", 400, False),   # BuilderSans
    48: ("BuilderSans", 500, False),
    49: ("BuilderSans", 700, False),
    50: ("BuilderSans", 800, False),
    51: ("BuilderMono", 400, False),
    52: ("BuilderExtended", 400, False),
    53: ("BuilderExtended", 600, False),
    54: ("BuilderExtended", 700, False),
}


def name_of(prop, value, default=None):
    """把 token 整數翻成 enum 名稱;翻不出來就原樣回傳。"""
    table = PROPERTY_ENUM.get(prop)
    if table is None:
        return value if default is None else default
    if isinstance(value, str):
        return value
    return table.get(value, value)
