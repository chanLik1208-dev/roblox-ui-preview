#!/usr/bin/env python3
"""roblox-ui-preview —— 把 Roblox 檔案裡的 GUI 渲染成 PNG,讓 agent 看得到 UI。

    python preview.py <place.rbxlx> --list
    python preview.py <place.rbxlx> --path Ingame.MechanicsFrame.QTE -o qte.png
    python preview.py <model.rbxmx> -o out.png --layout --show-hidden

輸出的 PNG 用 Read 工具就能看;--layout 另外印出帶絕對座標的樹,
兩者搭配才能判斷「這個元素為什麼沒出現」。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ruip import assets, defaults, fonts, layout, parse, render, tree  # noqa: E402


def parse_viewport(s):
    s = s.lower().replace("×", "x")
    presets = {
        "1080p": (1920, 1080), "720p": (1280, 720), "1440p": (2560, 1440),
        "4k": (3840, 2160), "phone": (896, 414), "phone-portrait": (414, 896),
        "tablet": (1112, 834), "ipad": (1112, 834),
    }
    if s in presets:
        return presets[s]
    if "x" in s:
        a, b = s.split("x", 1)
        return (int(a), int(b))
    raise argparse.ArgumentTypeError(f"看不懂的視窗尺寸: {s}")


def cmd_list(root, args):
    guis = parse.find_guis(root)
    if not guis:
        print("找不到任何 GUI(ScreenGui / Frame / …)。")
        print("提示:如果檔案裡的 UI 藏在非標準位置,加 --keep-all 重跑。")
        return 1
    print(f"可預覽的 GUI 共 {len(guis)} 個:\n")
    for g in guis:
        count = _count(g)
        extra = ""
        if g.class_name == "ScreenGui":
            if not g.get("Enabled", True):
                extra += "  [Enabled=false]"
            if g.get("IgnoreGuiInset"):
                extra += "  [IgnoreGuiInset]"
        elif not g.get("Visible", True):
            extra += "  [Visible=false]"
        print(f"  {g.path}")
        print(f"      [{g.class_name}]  {count} 個元素{extra}")
    print("\n用 --path <上面的路徑> 指定要畫哪一個。")
    return 0


def _count(node):
    n = 1 if defaults.is_renderable(node.class_name) else 0
    for c in node.children:
        n += _count(c)
    return n


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="preview.py",
        description="把 Roblox 檔案裡的 GUI 渲染成 PNG(給 agent 看的 UI 預覽)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 2)[2],
    )
    p.add_argument("file", help=".rbxlx / .rbxmx / .rbxl / .rbxm")
    p.add_argument("--path", help="要畫的 GUI 路徑,例如 Ingame.MechanicsFrame.QTE。"
                                  "可以只給尾段,會自動比對")
    p.add_argument("--list", action="store_true", help="列出所有可預覽的 GUI 後結束")
    p.add_argument("-o", "--out", help="輸出 PNG(預設 <路徑名>.png)")
    p.add_argument("--viewport", type=parse_viewport, default=(1280, 720),
                   metavar="WxH", help="畫布大小,或 1080p/720p/phone 等預設值")
    p.add_argument("--scale", type=float, default=1.0, help="輸出縮放倍率")
    p.add_argument("--background", default="checker",
                   choices=["checker", "black", "white", "transparent"],
                   help="底色。棋盤格(預設)最容易看出哪裡是空的")

    p.add_argument("--show-hidden", action="store_true",
                   help="連 Visible=false 的元素也畫出來,用虛線框標示")
    p.add_argument("--outline", action="store_true", help="每個元素加除錯外框")

    p.add_argument("--layout", action="store_true", help="印出帶絕對座標的樹")
    p.add_argument("--depth", type=int, help="--layout 的最大深度")
    p.add_argument("--json", metavar="FILE", help="把樹連同屬性寫成 JSON")
    p.add_argument("--no-image", action="store_true", help="不輸出 PNG(只要文字樹時用)")

    p.add_argument("--assets", action="store_true",
                   help="下載 rbxassetid 圖片(需要 cookie;沒有的話只用快取)")
    p.add_argument("--place-id", help="配 --assets 用。資產權限綁 universe,"
                                      "帶上該遊戲任一 place id 就能抓到別人的圖")
    p.add_argument("--cookie", help=".ROBLOSECURITY 內容或存放它的檔案路徑。"
                                    "預設讀環境變數 ROBLOSECURITY")
    p.add_argument("--keep-all", action="store_true",
                   help="不剪掉沒有 GUI 的子樹(除錯用,大檔會很慢)")
    args = p.parse_args(argv)

    if not os.path.isfile(args.file):
        print(f"找不到檔案: {args.file}", file=sys.stderr)
        return 2

    try:
        root = parse.load(args.file, keep_all=args.keep_all)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.list:
        return cmd_list(root, args)

    # ---- 挑出要畫的節點 ------------------------------------------------
    if args.path:
        target = parse.resolve(root, args.path)
        if target is None:
            print(f"路徑找不到: {args.path}\n", file=sys.stderr)
            guis = parse.find_guis(root)[:15]
            if guis:
                print("這個檔案裡有的是:", file=sys.stderr)
                for g in guis:
                    print("  " + g.path, file=sys.stderr)
            return 2
    else:
        guis = parse.find_guis(root)
        if not guis:
            print("檔案裡找不到任何 GUI。", file=sys.stderr)
            return 2
        target = guis[0]
        if len(guis) > 1:
            print(f"沒給 --path,自動選了第一個:{target.path}")
            print(f"(另外還有 {len(guis) - 1} 個,用 --list 看完整清單)\n")

    if not defaults.is_renderable(target.class_name) and \
            target.class_name not in ("ScreenGui", "SurfaceGui", "BillboardGui"):
        print(f"{target.path} 是 {target.class_name},不是可以畫的 GUI。",
              file=sys.stderr)
        return 2

    # ---- layout ---------------------------------------------------------
    engine = layout.Engine(viewport=args.viewport, show_hidden=args.show_hidden)
    boxes = engine.run(target)

    if not boxes:
        print("這個節點底下沒有畫得出來的元素。", file=sys.stderr)
        if not args.show_hidden:
            print("如果是整棵樹 Visible=false,加 --show-hidden 再試一次。",
                  file=sys.stderr)
        return 1

    # ---- 輸出 -----------------------------------------------------------
    if args.layout:
        print(tree.render_tree(target, boxes, args.depth))
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(tree.to_json(target, boxes))
        print(f"JSON -> {args.json}")

    if args.no_image:
        return 0

    fetcher = assets.AssetFetcher(
        cookie=assets.load_cookie(args.cookie),
        place_id=args.place_id,
        enabled=args.assets,
    )
    r = render.Renderer(args.viewport, fetcher=fetcher,
                        background=args.background,
                        show_hidden=args.show_hidden,
                        outline=args.outline, scale=args.scale)
    img = r.render(boxes)

    out = args.out
    if not out:
        safe = target.path.replace(".", "_").replace("/", "_") or "preview"
        out = safe + ".png"
    out_dir = os.path.dirname(os.path.abspath(out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    img.save(out)

    # ---- 摘要(agent 靠這段判斷結果可不可信) ---------------------------
    hidden = sum(1 for b in boxes if b.hidden_by)
    invisible = [b for b in boxes if not b.hidden_by and b.invisible]
    print(f"已輸出 {out}  {img.width}x{img.height}")
    print(f"  {target.path} [{target.class_name}] — 畫了 {len(boxes)} 個元素"
          + (f",其中 {hidden} 個原本是隱藏的" if hidden else ""))

    if invisible:
        print(f"  ⚠ {len(invisible)} 個元素 Visible=true 卻看不見(這通常才是"
              f"「UI 沒出現」的真正原因):")
        for b in invisible[:5]:
            print(f"      {b.node.name} [{b.node.class_name}] — {b.invisible}")
        if len(invisible) > 5:
            print(f"      …還有 {len(invisible) - 5} 個,--layout 看完整清單")

    if r.missing_images:
        n = len(r.missing_images)
        print(f"  ⚠ {n} 個圖片沒抓到,畫成打叉的空框:")
        for u in sorted(r.missing_images)[:5]:
            print(f"      {u}")
        if n > 5:
            print(f"      …還有 {n - 5} 個")
        if not args.assets:
            print("      加 --assets --place-id <該遊戲的 place id> 可以下載")
    st = assets.stats()
    if st["downloaded"] or st["hit"]:
        print(f"  圖片:下載 {st['downloaded']} / 快取 {st['hit']} / "
              f"本機 {st['local']} / 失敗 {st['failed']}")
    if fonts.missing_families():
        print(f"  ⚠ 找不到字型,已用系統字型頂替:"
              f"{', '.join(fonts.missing_families())}")
    if not fonts.roblox_available():
        print("  ⚠ 沒找到 Roblox 安裝目錄,文字寬度會跟 Studio 有落差")
    for w in r.warnings[:10]:
        print(f"  ⚠ {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
