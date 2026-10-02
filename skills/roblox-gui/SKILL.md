---
name: roblox-gui
description: 看得到、也改得動 Roblox 原生 GUI。用 roblox-ui-preview 把 rbxl/rbxlx 裡的 ScreenGui 渲染成 PNG（含「為什麼看不到」診斷），用 sculpt.py 以宣告式 spec 或 patch 操作改它，改完自動出前後對照圖。使用者說「改 Roblox UI / GUI」「調版面」「UI 沒出現」「看不到 ScreenGui」「rbxl 的介面」「做一個商店介面」，或你要動任何 .rbxl/.rbxlx/.rbxmx 裡的 GUI 實例時使用。
---

# Roblox GUI —— 看 → 改 → 再看

工具在你 clone 下來的 `roblox-ui-preview` 目錄（以下寫作 `<repo>`，用之前換成實際路徑）。兩支 CLI 共用同一套對 Roblox 的理解：

| | |
|---|---|
| `preview.py` | 渲染成 PNG ＋ 說出「為什麼看不到」 |
| `sculpt.py` | 改屬性、加刪物件、從零建 UI |

**不要用 Luau `Instance.new` 來做 UI 改動。** 執行期生成的 UI 這套工具看不到，
驗證迴圈會直接斷掉 —— 你會變成在盲改。原生實例才看得到、改得動、驗得了。

## 1. 先看，再改

任何改動之前先看一眼。沒看過就改 = 瞎改。

```bash
cd <repo>
python preview.py <檔> --list                              # 有哪些 GUI
python preview.py <檔> --path Ingame.Shop -o shop.png --layout
```

**PNG 和 `--layout` 的樹要一起看** —— 圖看得出「長什麼樣」，樹看得出「為什麼」。
用 Read 工具真的把 PNG 打開，不要只看檔案有沒有產生出來。

圖片沒抓到就加 `--assets --place-id <該遊戲的 place id>`。
Roblox 的 UI 大半是 ImageLabel，沒圖等於沒看。

## 2. 選路

| 情況 | 怎麼做 |
|---|---|
| 只動幾個屬性 | `--ops`（patch），最省事也最精準 |
| 整段版面重做 | `dump` → 編輯 `.gui` → `apply --spec` |
| 從零做一個新介面 | 手寫 `.gui` → `sculpt.py new` |

### 只動幾個屬性

```bash
python sculpt.py apply game.rbxl --ops tweak.json -o out.rbxl --verify --diff
```

```json
[
  {"op":"set",    "path":"Shop.Panel", "props":{"BackgroundColor3":"#1B3A5C"}},
  {"op":"insert", "parent":"Shop.Panel", "class":"UIStroke",
                  "props":{"Color":"#66CCFF","Thickness":3}},
  {"op":"delete", "path":"Shop.OldBtn"}
]
```
op 有 `set` / `insert` / `delete` / `rename` / `move` / `reorder`。

### 改既有版面

```bash
python sculpt.py dump game.rbxl --path Ingame.Shop -o shop.gui
#   ... 用 Edit 工具改 shop.gui ...
python sculpt.py apply game.rbxl --spec shop.gui -o out.rbxl --verify
```

`dump` 吐出來的是完整的，所以 dump → 編輯 → apply 不會掉東西。

### 從零

```
ScreenGui Shop
  ResetOnSpawn: false

  Frame Panel
    Size: {0.5,0}{0.6,0}
    Position: {0.5,0}{0.5,0}
    AnchorPoint: 0.5,0.5
    BackgroundColor3: #1E1E28
    UICorner
      CornerRadius: 12px
    TextLabel Title
      Size: {1,0}{0,48}
      BackgroundTransparency: 1
      Text: 商店
      FontFace: BuilderSans:700
      TextSize: 28
      TextColor3: #FFFFFF
```

```bash
python sculpt.py check shop.gui          # 先驗語法／屬性名／型別
python sculpt.py new shop.gui -o Shop.rbxmx --verify
```

## 3. 改完一定 `--verify`，而且要真的看那張圖

`--verify` 會產出 `<輸出>_compare.png`（左 BEFORE ／右 AFTER，加 `--diff` 多一格熱區）。
**用 Read 工具打開它。** 不看圖就宣稱改好了，是這個流程唯一不能省的一步。

摘要裡這兩句要當真：

- `畫面完全沒變` → 你改到的屬性不影響外觀，或者改錯物件了。回頭查路徑。
- `N 個元素 Visible=true 卻看不見` → 剛改壞的東西會在這裡被點名。

## 地雷清單

1. **Roblox XML 只寫「跟預設值不同」的屬性。** 屬性不在檔案裡 ≠ 值是 0。
   `<Item class="UICorner">` 裡沒有半徑 = 預設的 8px，不是 0。
2. **圓角是四個角**（`TopLeftRadius` 等），不是 `CornerRadius` ——
   後者在現代 Roblox 已是不存檔的 legacy 別名。工具會自動處理，
   但你自己讀 XML 時別找錯名字。
3. **enum 用名稱字串**（`Vertical`），不要用數字。打錯會報錯並列出合法值。
4. **同名兄弟要指定第幾個**：`Shop.Panel.Row[1]`。寫入時命中多個會直接報錯，
   工具不猜 —— 這是刻意的。
5. **`--at` 指錯層級**是最常見的錯：新的 ScreenGui 要掛在 `StarterGui`，
   不是掛在某個 Frame 底下。
6. **預設是合併不是取代。** 想整段換掉要明寫 `--replace`，而且它會弄丟
   非 GUI 的子物件（LocalScript…）—— 警告會告訴你。
7. **二進位 `.rbxl` 第一次轉檔很慢**（38 MB 的 place 可能十幾分鐘），
   但會快取，第二次起免費。手上有 `.rbxlx` 就直接用 `.rbxlx`。
8. **腳本內容不歸這裡管。** 要改 Luau 用 `rbxl-to-folder` / `folder-to-rbxl`。

## 收工前

```bash
cd <repo>
python test/run.py && python test/run_sculpt.py
```

兩個都要綠（60 ＋ 113 條斷言）。改過 `ruip/` 裡任何東西就一定要跑。
