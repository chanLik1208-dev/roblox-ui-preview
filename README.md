# roblox-ui-preview / sculpt

Roblox 原生 GUI 的一對工具：**`preview.py` 讓 agent 看得到，`sculpt.py` 讓它改得動。**

兩支共用 `ruip/`，所以「改完馬上再看一次」是同一個程序裡的事 ——
不會有兩套對 Roblox 的理解在互相打架。

    看 → 改 → 再看

---

## preview.py — 看

把 Roblox 檔案裡的 GUI 渲染成 PNG，**讓 agent 真的看得到 UI 長什麼樣**。

開不了 Studio 的時候（SaveInstance dump 缺 ServerScriptService、遠端機器沒有圖形介面、
或者只是不想為了看一眼 UI 而開 25 MB 的 place），這個工具是唯一能確認
「我改的這個 Frame 到底跑到哪去了」的方法。

輸出的 PNG 用 Read 工具直接看；`--layout` 另外印出帶絕對座標的樹。
**兩個要一起看** —— 圖看得出「長什麼樣」，樹看得出「為什麼」。

---

## 當成 Claude Code skill 用

`skills/roblox-gui/SKILL.md` 教 agent 走「看 → 改 → 再看」的流程。裝法：

```bash
git clone https://github.com/chanLik1208-dev/roblox-ui-preview.git
pip install Pillow
# 複製到個人 skill 目錄（Windows：%USERPROFILE%\.claude\skills\）
cp -r roblox-ui-preview/skills/roblox-gui ~/.claude/skills/
```

再把 `SKILL.md` 裡的 `<repo>` 換成你 clone 的實際路徑。之後跟 Claude Code 說
「改 Roblox UI」「UI 沒出現」之類的話就會自動觸發，也可以直接打 `/roblox-gui`。

---

## 快速開始

```bash
# 1. 有哪些 UI 可以看
python preview.py place.rbxlx --list

# 2. 畫出來
python preview.py place.rbxlx --path StarterGui.Ingame.MechanicsFrame -o ui.png

# 3. 圖 + 座標樹一起看(最常用)
python preview.py place.rbxlx --path Ingame.Shop -o shop.png --layout

# 4. 連圖片一起(Roblox 的 UI 大半是 ImageLabel,沒圖等於沒看)
python preview.py place.rbxlx --path Ingame.Shop -o shop.png \
    --assets --place-id 13977939077
```

吃 `.rbxlx` / `.rbxmx`（XML）與 `.rbxl` / `.rbxm`（二進位，會自動叫
`rbxl-to-folder` 的 `rbxl-engine --to-xml` 轉檔）。

---

## 「UI 沒出現」怎麼查

這是這個工具真正要解決的問題。畫面空白幾乎一定是下面四種之一，
執行後的摘要會直接點名是哪一種：

| 症狀 | 摘要會說 | 意思 |
|---|---|---|
| 元素完全沒被畫 | `其中 N 個原本是隱藏的`（要加 `--show-hidden` 才看得到） | `Visible = false` |
| 有位置卻看不見 | `N 個元素 Visible=true 卻看不見` | 透明度被設成 1 |
| 空框打叉 | `N 個圖片沒抓到` | assetId 沒下載（加 `--assets`） |
| 位置對但被蓋住 | `--layout` 裡的 `Z=` | ZIndex 疊在別人下面 |

**第二種最陰險** —— `TextTransparency = 1` 在 Explorer 裡跟正常元素長得一模一樣，
但畫面上什麼都沒有。實測 QTE HUD 的 `TotalSlots` 就是這樣（dump 當下計數器是隱形的，
遊戲執行時才 tween 出來）。

`--show-hidden` 會把三種看不見的東西都用虛線框標出來：

- 🟡 黃色 = 自己 `Visible = false`
- 🟠 橘色 = 被父層關掉
- 🔵 青色 = 可見但全透明

---

## 選項

```
--path A.B.C        要畫哪個。可以只給尾段(Ingame.Shop),會自動比對
--list              列出所有可預覽的 GUI
--viewport WxH      畫布大小,或 1080p / 720p / phone / tablet
--scale N           輸出縮放(小元件用 --scale 4 放大來看)
--background        checker(預設) / black / white / transparent
--show-hidden       連隱藏的也畫,用虛線框標示
--outline           每個元素加粉紅除錯外框
--layout            印出帶絕對座標的樹
--depth N           限制 --layout 的深度
--json FILE         把樹連同全部屬性寫成 JSON
--no-image          只要文字樹,不輸出 PNG
--assets            下載 rbxassetid 圖片
--place-id N        配 --assets,見下面
--cookie            .ROBLOSECURITY 的值或檔案路徑
```

### 圖片下載

資產權限綁在 **universe** 上，但 `assetdelivery` 這支 API 是看 **place**，
所以只要帶上該遊戲底下任一個 place id 當 header 就能下載別人的圖：

```
GET https://assetdelivery.roblox.com/v1/asset?id=<assetId>
    Cookie: .ROBLOSECURITY=…
    Roblox-Place-Id: 13977939077      ← 一定要是 header,寫成 query 參數無效
```

cookie 找的順序：`--cookie` > `ROBLOSECURITY` 環境變數 > `~/.roblosecurity` >
`D:\Download\Ase\cookie.txt`。抓下來的檔案快取在
`%LOCALAPPDATA%\roblox-ui-preview\assets\`，之後不重抓。

---

## 為什麼結果可信

- **完整的預設值表**（`ruip/defaults.py`）。Roblox 的 XML **只序列化跟預設值不同的屬性** ——
  `<Item class="UICorner">` 裡沒有 `CornerRadius` 不代表半徑是 0，而是預設的 `UDim(0, 8)`。
  少一條就整片位移。
- **用 Roblox 原廠字型**。本機裝了 Roblox 客戶端就有 `content/fonts` 全套與
  `families/*.json`（weight/style 對應表），文字寬度跟 Studio 一致；
  拿 Arial 頂替會讓整排文字跑掉。找不到字型時會明講。
- **60 條斷言**（`python test/run.py`），拿手工組出來、答案可以手算的 rbxmx 驗
  UDim2、AnchorPoint、UIListLayout 排序與對齊、UIGridLayout 換列、UIPadding、
  UICorner 預設半徑、ClipsDescendants、ZIndex、AspectRatio、UIScale、
  SizeConstraint、ScrollingFrame 的 CanvasPosition、Rotation、UIStroke、
  TextScaled、文字對齊 —— 座標和像素都直接比對。

## sculpt.py — 改

`preview.py` 的反向。四個子命令：

```bash
# 把既有 GUI 倒成可編輯的 .gui spec（改既有 UI 就從這裡開始）
python sculpt.py dump game.rbxl --path Ingame.Shop -o shop.gui

# 套用 spec —— 改完自動渲染 before/after 對照圖
python sculpt.py apply game.rbxl --spec shop.gui -o out.rbxl --verify

# 只動幾個屬性就用 patch 操作
python sculpt.py apply game.rbxl --ops tweak.json -o out.rbxl --verify --diff

# 從零生一個新的（可直接拖進 Studio）
python sculpt.py new shop.gui -o Shop.rbxmx --verify

# 只驗證 spec 不寫檔
python sculpt.py check shop.gui
```

### `.gui` 格式

長得像 Studio 的 Explorer。標頭行是 `ClassName 名字`，屬性行是 `Key: 值`，縮排決定巢狀。

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
      Text: 商店
      FontFace: BuilderSans:700
      TextSize: 28
      TextColor3: #FFFFFF
```

省略名字時 `Name = ClassName`（跟 Roblox 一致）。名字含空白就加引號。
`.json` 也吃（`{"class","name","props","children"}`），給程式產生用。

**`dump` 吐出來的一定是完整的**（所有非預設屬性都寫），而且檔頭會記著
`# @path …`，apply 就知道要改回哪裡 —— 真實 place 裡叫 `Header` 的東西
可能有九個，靠名字自動比對一定會撞。

有一條測試專門守著這件事：**dump 出來、一個字都不改、再 apply，改動數必須是 0**。
聽起來很無聊，但它一次抓到四個 bug（浮點被 round、Color3 的 float32 誤差、
同名兄弟全併進第一個、圓角兩種表示法沒正規化）。
如果「什麼都沒改」都會冒出假改動，使用者就永遠分不清哪些改動是自己要的。

### 值可以怎麼寫

| 型別 | 寫法 |
|---|---|
| UDim2 | `{0.5,10}{0,100}` · `0.5,10,0,100` · `100px` · `50%` |
| UDim | `{0,8}` · `8px` · `50%` · `8`（純數字＝offset） |
| Color3 | `#1E1E28` · `#fff` · `rgb(30,30,40)` · `0.1,0.1,0.16` · `white` |
| Vector2 / Rect | `0.5,0.5` / `x0,y0,x1,y1` |
| Enum | 名稱字串（`Vertical`），也吃 `Enum.FillDirection.Vertical` |
| Font | `BuilderSans` · `BuilderSans:700` · `BuilderSans:bold:italic` |
| Content | 完整 URL，或純數字（自動補 `rbxassetid://`） |
| ColorSequence | `0 #FF0000, 1 #0000FF` |

**屬性名和型別會當場驗證。** `Frame` 沒有 `Text`、`FillDirection: Vertikal`
都是立刻報錯 ＋ 給建議，不會靜默忽略 —— 靜默忽略比報錯難查十倍
（改完渲染出來一模一樣，然後開始懷疑人生）。

### patch 操作

```json
[
  {"op":"set",    "path":"Shop.Panel", "props":{"BackgroundTransparency":0.2}},
  {"op":"insert", "parent":"Shop.Panel", "class":"UIStroke",
                  "props":{"Color":"#FFAA00","Thickness":2}},
  {"op":"delete", "path":"Shop.OldBtn"},
  {"op":"rename", "path":"Shop.Btn1", "to":"BuyButton"},
  {"op":"move",   "path":"Shop.Title", "to":"Shop.Panel"},
  {"op":"reorder","parent":"Shop.Panel", "order":["Title","Body"]}
]
```

路徑 `A.B.C`；同名兄弟用 `A.B[2]`，指定類別用 `A.B#TextLabel`。
**寫入時要求唯一命中** —— 命中多個會報錯並列出候選，不猜。

### 合併 vs 取代

預設是 **合併**：spec 沒提到的屬性與子物件原封不動留著。
`--replace` 才會整棵換掉，而且會警告「非 GUI 的子物件會不見」。

AI 常常只寫它想改的那幾行，整段取代會**靜默地**把沒提到的東西清光 ——
所以安全的那個才是預設值。

## 它怎麼保證不弄壞你的檔案

改既有檔案時**不重建 XML**，而是做位元組手術：

```
1. parse.load() 找到目標，拿它的 referent
2. 在原始位元組裡定位 <Item …>…</Item>
3. 只把那一段（幾 KB）丟給 ElementTree，改完再序列化
4. 前面 ＋ 新片段 ＋ 後面 拼回去
```

動作的粒度是「能多小就多小」：

| 改什麼 | 動到的位元組 |
|---|---|
| 改屬性 | 只換 `<Properties>`，子物件一個 byte 不碰 |
| 加東西 | 插在父節點 `</Item>` 之前，兄弟不動 |
| 刪東西 | 剪掉那一段 |
| 搬家 | 原位元組剪下、原位元組貼上 |
| 整段換 | 只有 `--replace` 才做，而且會警告 |

實測（30 MB 的真實 place，改 3 個地方）：**99.5% 的位元組完全沒動**，
instance 數 35600 → 35601（就是新增的那個 UIStroke），150 個腳本一個不少。

`<Meta>`、`<External>`、SharedStrings、所有無關屬性都天然保留 ——
不是「盡量保留」，是根本沒碰到。

**為什麼要這麼小心**：`parse.load()` 是刻意有損的（剪枝 ＋ 只細解 GUI class）。
拿它重建整棵子樹，`ScreenGui` 底下的 `LocalScript` 會全部消失 ——
而且**畫面看起來一模一樣**，要等到進 Studio 按下 Play 才會發現 UI 沒反應。

## 二進位 `.rbxl` 的轉檔與快取

`.rbxl/.rbxm` 會借 `rbxl-to-folder` 的 `rbxl-engine`（rbx-dom）轉成 XML。實測：

| 轉換 | 耗時 |
|---|---|
| 30 MB XML → 2.4 MB binary | 4 秒 |
| 2.4 MB binary → 50 MB XML | 1 分 41 秒 |
| 38 MB binary → 200 MB+ XML | 超過 13 分鐘、吃掉 6 GB RAM |

**寫 XML 是慢的那一邊，而且慢得不成比例。** 所以轉出來的 XML 會快取在
`%LOCALAPPDATA%` 底下的 `roblox-ui-preview/xml/`，以（路徑, 大小, mtime）當鍵 ——
同一個檔第二次起是零成本，原檔一改快取自然失效。`preview.py` 也跟著受惠
（以前它每跑一次都要重轉一遍）。

保真度已驗：35600 instances / 6 ScreenGui / 82 UICorner / 150 腳本進出一趟完全一致。
唯一的差別是 rbx_xml 不做差異序列化 —— 它把每個屬性都寫出來，所以檔案會變胖。

## 已知限制

誠實列出來，免得把近似值當成真相：

- **只讀檔案裡已經存在的 GUI 實例。** Luau 在執行期用 `Instance.new` 生出來的 UI
  這裡看不到（例如全程式碼定義的 place，要先打包成含實例樹的檔案才行）。
- **CanvasGroup 的 `GroupTransparency` 是近似** —— 直接讓子樹整體變淡，
  而不是「先合成再套 alpha」，子元素互相重疊處會跟實際有些微差異。
- **`UITableLayout` 用 UIListLayout 的規則近似**，欄寬不會對齊。
- **RichText** 支援 `<b> <i> <u> <s> <br/> <font color size> <stroke>`，其餘標籤剝除。
- **ViewportFrame / VideoFrame** 畫成打叉的佔位框（3D 內容不在這個工具的範圍）。
- **`AutomaticSize`** 只算子元素的 offset 部分；scale 尺寸的子元素不回頭撐大父容器
  （跟 Roblox 一樣會有循環依賴，這裡用兩趟近似）。
- **開發者自己上傳的字型**（`FontFace` 指向 `rbxassetid://`）本機沒有，會 fallback
  並在摘要裡點名 —— 那種情況下文字寬度只是估計值。
- 動畫、Tween、`AutoButtonColor` 的 hover/press 狀態都不模擬，畫的是靜態的當下。
- **中日韓文字用系統字型頂替。** Roblox 內建字型只涵蓋拉丁/希臘/西里爾，CJK 在真正的
  Roblox 客戶端是靠引擎的 fallback 鏈補的；這裡照做（優先用微軟正黑體），
  所以字寬跟 Studio 會有一點差異，但至少不會是一排豆腐。
- **雕刻端只碰 GUI 屬性。** 腳本內容請用 `rbxl-to-folder` / `folder-to-rbxl`。

## 架構

```
preview.py          CLI —— 看
sculpt.py           CLI —— 改（dump / apply / new / check）
ruip/
  ── 共用 ──────────────────────────────────────────────────
  parse.py          rbxlx/rbxmx -> 輕量樹。iterparse 邊走邊 clear,
                    只有 GUI 相關 class 才解析屬性,110 MB 的 dump 也吃得下
  defaults.py       ★ 預設值表 —— 正確性的基礎
  enums.py          token 整數 <-> enum 名稱
  apidump.py        Roblox API dump:屬性存不存在、什麼型別、是不是 Hidden
  convert.py        二進位 <-> XML 轉檔 + 快取（慢的那一邊只付一次）
  ── 看 ────────────────────────────────────────────────────
  fonts.py          FontFace -> 本機 Roblox 字型檔（含 CJK fallback）
  text.py           換行 / TextScaled / RichText
  layout.py         UDim2 / 約束 / UIListLayout / 旋轉矩陣 / ZIndex 排序
  render.py         Pillow 繪製:圓角、漸層、9-slice、裁切、旋轉
  assets.py         圖片下載 + 快取
  tree.py           文字樹 / JSON
  ── 改 ────────────────────────────────────────────────────
  coerce.py         ★ 字串 -> 值。屬性名／型別／enum 當場驗證並給建議
  spec.py           .gui 縮排 DSL 的 parser 與 dumper
  ops.py            patch 操作、路徑定址、spec 合併
  emit.py           樹 -> XML（parse.parse_value 的鏡像 + 差異序列化）
  splice.py         ★ byte 級子樹手術 —— 不重建 XML
  sculptor.py       Change -> 位元組操作。紀律:能多小就多小
  compare.py        before/after 並排 PNG + 差異熱區
test/run.py         60 條斷言（看）
test/run_sculpt.py 113 條斷言（改）
skills/roblox-gui/  Claude Code skill —— 教 agent 怎麼用上面兩支
```

相依：只有 **Pillow**。圖片下載走標準庫 `urllib`；
二進位轉檔借 `rbxl-to-folder` 的 `rbxl-engine`（只有 `.rbxl/.rbxm` 才需要）。

收工前兩個都要跑：

```bash
python test/run.py && python test/run_sculpt.py
```
