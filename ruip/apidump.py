"""Roblox API dump 查詢 —— 屬性存不存在、是什麼型別。

`defaults.py` 那張手工表涵蓋了 GUI 渲染會用到的屬性,但**雕刻的人想設的東西比渲染
需要的多**(ScreenGui.ResetOnSpawn、TextButton.Modal、Selectable…)。少一條就會變成
「AI 設了但工具默默忽略」——比報錯難查十倍。

所以型別查詢是兩層的:先問 defaults(快、值的表示法保證跟 parse.py 一致),
問不到再翻 API dump(全,4020 個屬性)。

API dump 的兩個坑:
1. **屬性定義在祖先 class 上。** `Frame` 的 Members 裡**沒有** Size/BackgroundColor3,
   它們在 `GuiObject`。一定要沿 Superclass 鏈往上走,不然 GUI 屬性全部查不到。
2. **Tags 陣列裡會混 dict**(deprecated alias 會帶 `{"PreferredDescriptorName": …}`),
   直接 `"ReadOnly" in tags` 不會炸但語意會歪,要先濾掉非字串。
"""

import json
import os

# Xeno 會在 workspace 放一份完整 dump;沒有的話整個模組降級成「查不到」,
# 由 defaults.py 獨力支撐(GUI 常用屬性都在裡面)。
DUMP_CANDIDATES = [
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Xeno", "workspace", "API_DUMP.json"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "API_DUMP.json"),
]

# API dump 的型別名 -> parse.py / defaults.py 用的內部型別名。
# 左邊是 Roblox 的說法,右邊是這個專案的說法。
VALUE_TYPE_MAP = {
    "bool": "bool",
    "int": "int", "int64": "int",
    "float": "float", "double": "float",
    "string": "string",
    "Content": "Content", "ContentId": "Content",
    "UDim": "UDim", "UDim2": "UDim2",
    "Vector2": "Vector2", "Vector2int16": "Vector2",
    "Color3": "Color3",
    "Rect": "Rect",
    "Font": "Font",
    "ColorSequence": "ColorSequence",
    "NumberSequence": "NumberSequence",
    "NumberRange": "NumberRange",
    "BrickColor": "BrickColor",
}

_dump = None          # {class_name: class_entry}
_prop_cache = {}      # (class, prop) -> descriptor | None
_loaded = False


def _load():
    global _dump, _loaded
    if _loaded:
        return _dump
    _loaded = True
    for path in DUMP_CANDIDATES:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            continue
        # 這份 dump 的包裝是 {"<版本字串>": [classes…]},不是官方的 {"Classes": …}
        classes = None
        if isinstance(raw, dict):
            if isinstance(raw.get("Classes"), list):
                classes = raw["Classes"]
            elif len(raw) == 1:
                only = next(iter(raw.values()))
                if isinstance(only, list):
                    classes = only
        elif isinstance(raw, list):
            classes = raw
        if not classes:
            continue
        _dump = {c["Name"]: c for c in classes if isinstance(c, dict) and "Name" in c}
        return _dump
    return None


def available():
    return _load() is not None


def dump_path():
    for path in DUMP_CANDIDATES:
        if path and os.path.isfile(path):
            return path
    return None


def _str_tags(entry):
    """Tags 裡可能混 dict,只留字串。"""
    return [t for t in entry.get("Tags", []) or [] if isinstance(t, str)]


def class_exists(class_name):
    d = _load()
    return d is not None and class_name in d


def creatable(class_name):
    """能不能 Instance.new / 出現在檔案裡。dump 不在時一律放行。"""
    d = _load()
    if d is None or class_name not in d:
        return True
    return "NotCreatable" not in _str_tags(d[class_name])


def superclasses(class_name):
    """自己 + 所有祖先,由近而遠。"""
    d = _load()
    if d is None:
        return [class_name]
    chain, seen, cur = [], set(), class_name
    while cur and cur in d and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = d[cur].get("Superclass")
    return chain or [class_name]


def find_property(class_name, prop_name):
    """沿 Superclass 鏈找屬性描述,找不到回 None。"""
    key = (class_name, prop_name)
    if key in _prop_cache:
        return _prop_cache[key]
    d = _load()
    found = None
    if d is not None:
        for cls in superclasses(class_name):
            for m in d.get(cls, {}).get("Members", []):
                if m.get("MemberType") == "Property" and m.get("Name") == prop_name:
                    found = m
                    break
            if found:
                break
    _prop_cache[key] = found
    return found


def type_of(class_name, prop_name):
    """屬性的內部型別名(見 VALUE_TYPE_MAP);enum 回 ("enum", <enum 型別名>)。"""
    m = find_property(class_name, prop_name)
    if m is None:
        return None
    vt = m.get("ValueType", {})
    if vt.get("Category") == "Enum":
        return ("enum", vt.get("Name", ""))
    return VALUE_TYPE_MAP.get(vt.get("Name"))


def writable(class_name, prop_name):
    """能不能寫進檔案。

    判準用 **CanLoad** 而不是 CanSave —— UICorner.CornerRadius 在 0.734 已經是
    `CanSave:false, CanLoad:true` 的 legacy 別名(真正存檔的是四個角),
    用 CanSave 當判準會把 AI 最常寫的那個名字擋掉。
    """
    m = find_property(class_name, prop_name)
    if m is None:
        return True
    if "ReadOnly" in _str_tags(m):
        return False
    return m.get("Serialization", {}).get("CanLoad", True)


def hidden(class_name, prop_name):
    """Studio 屬性面板看不到的東西 —— dump 成 spec 時該濾掉。

    判準是 dump 自己的 `Hidden` / `NotScriptable` tag,不是寫死的黑名單。
    最典型的是 `DefinesCapabilities`:每個 Item 都有,對 GUI 毫無意義,
    但真實 place dump 出來會是 440 行裡的 440 行雜訊。
    """
    m = find_property(class_name, prop_name)
    if m is None:
        return False
    tags = _str_tags(m)
    return "Hidden" in tags or "NotScriptable" in tags


def content_twin(class_name, prop_name):
    """`Image` <-> `ImageContent` 這種新舊並存的成對屬性,回另一半的名字。

    新版 Roblox 把 `Image`(ContentId) 換成了 `ImageContent`(Content),但兩個
    都還會序列化。只改一邊會讓檔案自相矛盾,而且**畫面看起來還是對的** ——
    要進 Studio 才發現圖不對。所以一律成對寫。
    """
    if prop_name.endswith("Content"):
        other = prop_name[: -len("Content")]
    else:
        other = prop_name + "Content"
    if find_property(class_name, prop_name) and find_property(class_name, other):
        return other
    return None


def legacy_alias(class_name, prop_name):
    """True 代表「寫得進去但 Studio 存檔後會被正規屬性取代」,用來出提示。"""
    m = find_property(class_name, prop_name)
    if m is None:
        return False
    ser = m.get("Serialization", {})
    return ser.get("CanLoad", True) and not ser.get("CanSave", True)


def properties_of(class_name, limit=None):
    """這個 class(含繼承)所有可寫屬性名,排序後回傳。用來對打錯的名字給建議。"""
    d = _load()
    if d is None:
        return []
    names = set()
    for cls in superclasses(class_name):
        for m in d.get(cls, {}).get("Members", []):
            if m.get("MemberType") != "Property":
                continue
            n = m.get("Name", "")
            if n and "ReadOnly" not in _str_tags(m):
                names.add(n)
    out = sorted(names)
    return out[:limit] if limit else out
