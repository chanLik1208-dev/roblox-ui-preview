#!/usr/bin/env python3
"""sculpt.py —— 讓 agent 雕刻 Roblox 原生 GUI。

`preview.py` 讓 agent 看得到 UI,這支讓它改得動。兩支共用 `ruip/`,
所以「改完馬上再看一次」是同一個程序裡的事,不會有兩套對 Roblox 的理解。

    python sculpt.py dump  game.rbxl --path Ingame.Shop -o shop.gui
    python sculpt.py apply game.rbxl --spec shop.gui -o out.rbxl --verify
    python sculpt.py apply game.rbxl --ops tweak.json -o out.rbxl --verify
    python sculpt.py new   shop.gui -o Shop.rbxmx
    python sculpt.py check shop.gui
"""

import argparse
import os
import sys

from ruip import (compare, convert, coerce, defaults, layout, ops, parse,
                 render, sculptor, spec, tree)

try:
    from ruip import assets as assets_mod
except ImportError:                          # pragma: no cover
    assets_mod = None


# --------------------------------------------------------------------------
# 共用
# --------------------------------------------------------------------------


def parse_viewport(s):
    presets = {
        "1080p": (1920, 1080), "720p": (1280, 720), "1440p": (2560, 1440),
        "4k": (3840, 2160), "phone": (896, 414), "phone-portrait": (414, 896),
        "tablet": (1112, 834), "ipad": (1112, 834),
    }
    key = s.lower().replace("×", "x")
    if key in presets:
        return presets[key]
    try:
        w, h = key.split("x")
        return (int(w), int(h))
    except ValueError:
        raise argparse.ArgumentTypeError("viewport 要寫成 1280x720 或 720p") from None


def _load(path, keep_all=False):
    if not os.path.isfile(path):
        print("找不到檔案: %s" % path, file=sys.stderr)
        raise SystemExit(2)
    try:
        return parse.load(path, keep_all=keep_all)
    except (RuntimeError, convert.ConvertError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None


def _resolve_gui(root, path):
    """挑出要處理的 GUI。沒給 --path 就自動選第一個。"""
    if path:
        try:
            return ops.resolve_one(root, path)
        except ops.OpError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from None
    guis = parse.find_guis(root)
    if not guis:
        print("檔案裡找不到任何 GUI。", file=sys.stderr)
        raise SystemExit(2)
    if len(guis) > 1:
        print("沒給 --path,自動選了第一個:%s" % guis[0].path)
        print("(另外還有 %d 個,用 preview.py --list 看完整清單)\n" % (len(guis) - 1))
    return guis[0]


def _render(node, viewport, show_hidden=False):
    """一個節點 -> PIL 圖 + 診斷。跟 preview.py 走同一條路,所以兩邊的判斷一致。"""
    engine = layout.Engine(viewport=viewport, show_hidden=show_hidden)
    boxes = engine.run(node)
    if not boxes:
        return None, [], None
    fetcher = assets_mod.AssetFetcher(enabled=False) if assets_mod else None
    r = render.Renderer(viewport, fetcher=fetcher, background="black",
                        show_hidden=show_hidden)
    return r.render(boxes), boxes, r


# --------------------------------------------------------------------------
# dump
# --------------------------------------------------------------------------


def cmd_dump(args):
    root = _load(args.file, keep_all=args.keep_all)
    target = _resolve_gui(root, args.path)

    text = spec.dump(target, include_defaults=args.all_props,
                     source_path=target.path)
    if args.out:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        n = sum(1 for _ in _walk(target))
        print("已輸出 %s  —— %s [%s],%d 個物件"
              % (args.out, target.path, target.class_name, n))
        print("  改完之後:python sculpt.py apply %s --spec %s -o <輸出> --verify"
              % (args.file, args.out))
    else:
        sys.stdout.write(text)
    return 0


def _walk(node):
    yield node
    for c in node.children:
        yield from _walk(c)


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------


def cmd_apply(args):
    if not args.spec and not args.ops:
        print("要給 --spec 或 --ops 其中之一。", file=sys.stderr)
        return 2

    root = _load(args.file, keep_all=True)

    try:
        if args.ops:
            changes = ops.apply_ops(root, ops.load_ops(args.ops))
        else:
            directives = {}
            nodes = spec.parse_file(args.spec, directives=directives)
            changes = ops.merge_spec(root, nodes, at=args.at, replace=args.replace,
                                     target_path=directives.get("path"))
    except (ops.OpError, spec.SpecError, coerce.CoerceError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not changes:
        print("沒有任何改動 —— spec 跟檔案裡的內容已經一樣了。")
        return 0

    out = args.out or _default_out(args.file)

    # before 的圖要**重新載入一次**才畫。
    # apply_ops / merge_spec 是就地改 root 的,拿它畫出來的是 after 不是 before ——
    # 症狀是對照圖左右一模一樣、變動像素數少得離譜。
    before_img = None
    target_path = None
    if args.verify:
        target = _verify_target(root, args, changes)
        target_path = target.path if target is not None else None
        if target_path:
            fresh = parse.load(args.file, keep_all=True)
            try:
                before_node = ops.resolve_one(fresh, target_path)
            except ops.OpError:
                before_node = None
            if before_node is not None:
                before_img, _b, _r = _render(before_node, args.viewport, args.show_hidden)

    try:
        doc = sculptor.open_document(args.file)
        applied, warns = sculptor.apply_changes(doc, changes)
        sculptor.write(doc, out)
    except (sculptor.SculptError, convert.ConvertError, Exception) as exc:
        if isinstance(exc, (sculptor.SculptError, convert.ConvertError)):
            print(str(exc), file=sys.stderr)
            return 2
        raise

    print("已寫出 %s" % out)
    print("  %d 項改動:" % applied)
    for ch in changes[:12]:
        print("    %s" % ch.detail)
    if len(changes) > 12:
        print("    …還有 %d 項" % (len(changes) - 12))
    for w in warns:
        print("  ⚠ %s" % w)

    if args.check_count:
        _check_counts(args.file, out)

    if args.verify:
        _do_verify(out, args, before_img, target_path)
    return 0


def _default_out(src):
    base, ext = os.path.splitext(src)
    return base + "_sculpted" + ext


def _verify_target(root, args, changes):
    """要拿哪個 GUI 來畫對照圖 —— 改動所在的那個 ScreenGui。"""
    if args.path:
        try:
            return ops.resolve_one(root, args.path)
        except ops.OpError:
            return None
    for ch in changes:
        n = ch.node or ch.parent
        while n is not None:
            if n.class_name in ("ScreenGui", "SurfaceGui", "BillboardGui"):
                return n
            n = n.parent
    guis = parse.find_guis(root)
    return guis[0] if guis else None


def _check_counts(src, out):
    try:
        a = convert.instance_count(src)
        b = convert.instance_count(out)
    except convert.ConvertError as exc:
        print("  (instance 數比對跳過:%s)" % exc)
        return
    mark = "✓" if a == b else "⚠"
    print("  %s instance 數 %d → %d" % (mark, a, b))


def _do_verify(out, args, before_img, target_path):
    root2 = _load(out)
    path = target_path or args.path
    try:
        target2 = ops.resolve_one(root2, path) if path else None
    except ops.OpError:
        target2 = None
    if target2 is None:
        target2 = _resolve_gui(root2, None)

    after_img, boxes, renderer = _render(target2, args.viewport, args.show_hidden)
    if after_img is None:
        print("  ⚠ 這個 GUI 畫不出任何東西。")
        if not args.show_hidden:
            print("    多半是整棵 Visible=false(很多 UI 平常就是關著的,"
                  "執行時才打開)。加 --show-hidden 再跑一次就看得到了。")
        return

    cmp_path = os.path.splitext(out)[0] + "_compare.png"
    if before_img is not None:
        img = compare.side_by_side(before_img, after_img, diff=args.diff)
        changed, total = compare.changed_pixels(before_img, after_img)
        img.save(cmp_path)
        pct = (changed / total * 100) if total and changed >= 0 else -1
        print("  對照圖 %s" % cmp_path)
        if changed == 0:
            print("    ⚠ 畫面**完全沒變** —— 改到的屬性可能不影響外觀,"
                  "或是改錯物件了。")
        elif changed > 0:
            print("    畫面有 %d 個像素不同(%.1f%%)" % (changed, pct))
    else:
        after_img.save(cmp_path)
        print("  結果圖 %s" % cmp_path)

    _diagnose(target2, boxes, renderer)


def _diagnose(target, boxes, renderer):
    """沿用 preview.py 那套「為什麼看不到」—— 剛改壞的東西當場點名。"""
    hidden = sum(1 for b in boxes if b.hidden_by)
    invisible = [b for b in boxes if not b.hidden_by and b.invisible]
    print("    %s [%s] — 畫了 %d 個元素%s"
          % (target.path, target.class_name, len(boxes),
             (",其中 %d 個原本是隱藏的" % hidden) if hidden else ""))
    if invisible:
        print("    ⚠ %d 個元素 Visible=true 卻看不見:" % len(invisible))
        for b in invisible[:5]:
            print("        %s [%s] — %s" % (b.node.name, b.node.class_name, b.invisible))
        if len(invisible) > 5:
            print("        …還有 %d 個" % (len(invisible) - 5))
    if renderer is not None and renderer.missing_images:
        print("    ⚠ %d 個圖片沒抓到(對照圖裡是打叉的框)" % len(renderer.missing_images))


# --------------------------------------------------------------------------
# new / check
# --------------------------------------------------------------------------


def cmd_new(args):
    try:
        nodes = spec.parse_file(args.spec)
    except (spec.SpecError, coerce.CoerceError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    out = args.out or (os.path.splitext(args.spec)[0] + ".rbxmx")
    sculptor.new_document(nodes, out)
    n = sum(len(list(_walk(x))) for x in nodes)
    print("已建立 %s —— %d 個物件" % (out, n))

    if args.verify:
        root = _load(out)
        target = _resolve_gui(root, None)
        img, boxes, r = _render(target, args.viewport, args.show_hidden)
        if img is None:
            print("  ⚠ 這個 spec 畫不出任何東西。")
            return 1
        png = os.path.splitext(out)[0] + ".png"
        img.save(png)
        print("  預覽圖 %s" % png)
        _diagnose(target, boxes, r)
    return 0


def cmd_check(args):
    try:
        nodes = spec.parse_file(args.spec)
    except (spec.SpecError, coerce.CoerceError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    total = sum(len(list(_walk(n))) for n in nodes)
    print("OK —— %d 個物件,屬性名／型別／enum 值都合法。" % total)
    if args.layout:
        for n in nodes:
            img_engine = layout.Engine(viewport=args.viewport, show_hidden=True)
            boxes = img_engine.run(n)
            print()
            print(tree.render_tree(n, boxes))
    return 0


# --------------------------------------------------------------------------


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="sculpt.py",
        description="雕刻 Roblox 原生 GUI —— preview.py 的反向工具。")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, viewport=True):
        if viewport:
            p.add_argument("--viewport", type=parse_viewport, default=(1280, 720),
                           help="預設 720p;也吃 1080p / phone / 1280x720")
            p.add_argument("--show-hidden", action="store_true",
                           help="連隱藏元素也畫出來")
        return p

    p = sub.add_parser("dump", help="把既有 GUI 倒成可編輯的 .gui spec")
    p.add_argument("file")
    p.add_argument("--path", help="要倒哪一個 GUI(可只給尾段)")
    p.add_argument("-o", "--out", help="輸出 .gui;不給就印到 stdout")
    p.add_argument("--all-props", action="store_true",
                   help="連跟預設值相同的屬性也寫出來")
    p.add_argument("--keep-all", action="store_true", help="不剪枝")
    p.set_defaults(func=cmd_dump)

    p = common(sub.add_parser("apply", help="把 spec 或 ops 套到既有檔案"))
    p.add_argument("file")
    p.add_argument("--spec", help=".gui 或 .json spec")
    p.add_argument("--ops", help=".json patch 操作")
    p.add_argument("--at", help="spec 要掛在哪個節點底下(新增時必給)")
    p.add_argument("--replace", action="store_true",
                   help="同名節點整棵取代(預設是合併)。會清掉沒提到的屬性與子物件")
    p.add_argument("-o", "--out", help="輸出檔;預設 <輸入>_sculpted<副檔名>")
    p.add_argument("--path", help="對照圖要畫哪個 GUI(預設自動找改動所在的)")
    p.add_argument("--verify", action="store_true", help="改完渲染 before/after 對照圖")
    p.add_argument("--diff", action="store_true", help="對照圖多一格差異熱區")
    p.add_argument("--check-count", action="store_true",
                   help="比對前後的 instance 總數(大檔會慢)")
    p.set_defaults(func=cmd_apply)

    p = common(sub.add_parser("new", help="從 spec 建一個全新的檔"))
    p.add_argument("spec")
    p.add_argument("-o", "--out", help="輸出;預設 <spec>.rbxmx")
    p.add_argument("--verify", action="store_true", help="建完渲染一張預覽圖")
    p.set_defaults(func=cmd_new)

    p = common(sub.add_parser("check", help="只驗證 spec,不寫任何檔"))
    p.add_argument("spec")
    p.add_argument("--layout", action="store_true", help="順便印出算好的座標樹")
    p.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
