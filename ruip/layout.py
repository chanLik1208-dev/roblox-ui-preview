"""把 GUI 樹算成一串「絕對矩形 + 變換矩陣」的繪製清單。

計算順序刻意跟 Roblox 一致:
    base size(UDim2 相對父內容區) -> UIScale -> AutomaticSize
        -> UIAspectRatioConstraint -> UISizeConstraint -> 位置(Position/AnchorPoint)
        -> 若父有 UIListLayout/UIGridLayout 則位置改由 layout 決定

AutomaticSize 天生是循環依賴(父的大小取決於子,子的 scale 大小又取決於父),
處理方式是跑兩趟:先用暫定大小排一次子元素,量出來後改寫父的大小,再排第二趟。
"""

import math

from . import defaults, text as textmod

TOPBAR_INSET = 36  # IgnoreGuiInset = false 時上方讓出的高度


class Box:
    __slots__ = (
        "node", "x", "y", "w", "h", "matrix", "clips", "order", "depth",
        "text_size", "lines", "text_w", "text_h", "content_origin",
        "content_size", "hidden_by", "invisible", "parent",
    )

    def __init__(self, node):
        self.node = node
        self.x = self.y = self.w = self.h = 0.0
        self.matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self.clips = []
        self.order = ()
        self.depth = 0
        self.text_size = None
        self.lines = None
        self.text_w = self.text_h = 0.0
        self.content_origin = (0.0, 0.0)
        self.content_size = (0.0, 0.0)
        self.hidden_by = None  # 「自己 Visible=false」還是「祖先關掉」
        self.invisible = None  # Visible=true 但透明度讓它其實看不見
        self.parent = None

    @property
    def rect(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def to_canvas(self, px, py):
        a, b, c, d, e, f = self.matrix
        return (a * px + c * py + e, b * px + d * py + f)

    def corners(self):
        return [self.to_canvas(*p) for p in (
            (self.x, self.y), (self.x + self.w, self.y),
            (self.x + self.w, self.y + self.h), (self.x, self.y + self.h))]

    @property
    def rotated(self):
        a, b, c, d = self.matrix[:4]
        return abs(b) > 1e-6 or abs(c) > 1e-6 or abs(a - 1) > 1e-6 or abs(d - 1) > 1e-6


def _mat_mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _rotation_about(deg, cx, cy):
    r = math.radians(deg)
    cos, sin = math.cos(r), math.sin(r)
    # T(c) · R · T(-c)
    return (cos, sin, -sin, cos,
            cx - cos * cx + sin * cy,
            cy - sin * cx - cos * cy)


def _udim(u, parent):
    return u[0] * parent + u[1]


def _udim2(u, pw, ph):
    return (u[0] * pw + u[1], u[2] * ph + u[3])


class Engine:
    def __init__(self, viewport=(1280, 720), show_hidden=False, guides=False):
        self.viewport = viewport
        self.show_hidden = show_hidden
        self.guides = guides
        self.boxes = []
        self._doc_index = 0
        self.global_z = False

    # ------------------------------------------------------------------
    def run(self, root_node):
        """root_node 可以是 ScreenGui,也可以是任何 GuiObject(單獨預覽某個 Frame)。"""
        vw, vh = self.viewport
        self.boxes = []
        self._doc_index = 0

        if root_node.class_name in ("ScreenGui", "SurfaceGui", "BillboardGui"):
            self.global_z = root_node.get("ZIndexBehavior") == "Global"
            inset = 0
            if root_node.class_name == "ScreenGui" and not root_node.get("IgnoreGuiInset"):
                inset = TOPBAR_INSET
            origin = (0.0, float(inset))
            size = (float(vw), float(vh - inset))
            base = _mat_mul((1, 0, 0, 1, 0, 0), (1, 0, 0, 1, 0, 0))
            enabled = bool(root_node.get("Enabled", True))
            # ScreenGui 不是 GuiObject,不會有 UIListLayout,直接排子元素
            for i, child in enumerate(root_node.children):
                self._layout_node(child, origin, size, base, (), 0,
                                  visible=enabled, clips=[], sibling_index=i)
        else:
            self.global_z = False
            # 單獨預覽:把 viewport 當它的父容器
            self._layout_node(root_node, (0.0, 0.0), (float(vw), float(vh)),
                              (1, 0, 0, 1, 0, 0), (), 0, visible=True, clips=[])
        self.boxes.sort(key=lambda b: b.order)
        return self.boxes

    # ------------------------------------------------------------------
    def _sorted_children(self, node, layout_obj):
        kids = [c for c in node.children if defaults.is_renderable(c.class_name)]
        if layout_obj is None:
            return kids
        order = layout_obj.get("SortOrder", "Name")
        if order == "LayoutOrder":
            return sorted(kids, key=lambda c: (c.get("LayoutOrder", 0), c.name))
        if order == "Name":
            return sorted(kids, key=lambda c: c.name)
        return kids  # Custom -> 文件順序

    # ------------------------------------------------------------------
    def _layout_node(self, node, parent_origin, parent_size, parent_matrix,
                     order_prefix, depth, visible, clips, forced=None,
                     sibling_index=0, forced_pos=None):
        cls = node.class_name
        if not defaults.is_renderable(cls):
            return None

        box = Box(node)
        box.depth = depth
        self._doc_index += 1
        doc_i = self._doc_index

        zindex = int(node.get("ZIndex", 1) or 0)
        if self.global_z:
            box.order = (zindex, doc_i)
        else:
            box.order = order_prefix + (zindex, sibling_index, doc_i)

        pw, ph = parent_size
        own_visible = bool(node.get("Visible", True))
        eff_visible = visible and own_visible
        if not own_visible:
            box.hidden_by = "self"
        elif not visible:
            box.hidden_by = "ancestor"

        # ---- 大小 ------------------------------------------------------
        if forced is not None:
            # 父有 UIListLayout/UIGridLayout —— 大小已在 _list/_grid 裡算完
            w, h = forced
        else:
            w, h = self._base_size(node, pw, ph)
            scale = self._ui_scale(node)
            w, h = w * scale, h * scale
            auto = node.get("AutomaticSize", "None")
            if auto != "None":
                w, h = self._auto_size(node, w, h, auto, pw, ph)
            w, h = self._aspect(node, w, h, pw, ph)
            w, h = self._size_constraint(node, w, h)

        # ---- 位置 ------------------------------------------------------
        pos = node.get("Position", (0, 0, 0, 0))
        anchor = node.get("AnchorPoint", (0.0, 0.0))
        px = parent_origin[0] + pos[0] * pw + pos[1]
        py = parent_origin[1] + pos[2] * ph + pos[3]

        box.w, box.h = w, h
        if forced_pos is not None:
            # 父有 UIListLayout/UIGridLayout —— 位置由 layout 決定,Position/AnchorPoint 失效
            box.x, box.y = forced_pos
        else:
            box.x = px - anchor[0] * w
            box.y = py - anchor[1] * h

        # ---- 旋轉 ------------------------------------------------------
        rot = float(node.get("Rotation", 0) or 0)
        box.matrix = parent_matrix
        if abs(rot) > 1e-6:
            box.matrix = _mat_mul(parent_matrix,
                                  _rotation_about(rot, box.x + w / 2, box.y + h / 2))

        box.clips = clips
        box.parent = None
        if eff_visible or self.show_hidden:
            self.boxes.append(box)

        # ---- 文字 ------------------------------------------------------
        if self._is_text(cls):
            self._layout_text(box, node)
        box.invisible = self._invisible_reason(node, cls, box)

        # ---- 子元素 ----------------------------------------------------
        pad = self._padding(node, w, h)
        cox, coy = box.x + pad[0], box.y + pad[1]
        cw, ch = max(0.0, w - pad[0] - pad[2]), max(0.0, h - pad[1] - pad[3])
        box.content_origin = (cox, coy)
        box.content_size = (cw, ch)

        child_clips = clips
        if node.get("ClipsDescendants", False) or cls in ("ScrollingFrame", "CanvasGroup"):
            child_clips = clips + [(box, self._corner_radius(node, w, h))]

        if cls == "ScrollingFrame":
            cox, coy, cw, ch = self._canvas_region(node, box, cox, coy, cw, ch)

        child_order = () if self.global_z else box.order
        self._layout_children(node, (cox, coy), (cw, ch), box.matrix,
                              child_order, depth + 1, eff_visible, child_clips)
        return box

    # ------------------------------------------------------------------
    def _layout_children(self, node, origin, size, matrix, order_prefix, depth,
                         visible, clips):
        layout_obj = self._layout_object(node)
        kids = self._sorted_children(node, layout_obj)
        if not kids:
            return

        if layout_obj is None:
            for i, child in enumerate(kids):
                self._layout_node(child, origin, size, matrix, order_prefix,
                                  depth, visible, clips, sibling_index=i)
            return

        if layout_obj.class_name == "UIGridLayout":
            placements = self._grid(layout_obj, kids, size)
        else:
            placements = self._list(layout_obj, kids, size, origin)

        for i, (child, ox, oy, fw, fh) in enumerate(placements):
            self._layout_node(child, origin, size, matrix, order_prefix, depth,
                              visible, clips, forced=(fw, fh), sibling_index=i,
                              forced_pos=(origin[0] + ox, origin[1] + oy))

    # ------------------------------------------------------------------
    def _base_size(self, node, pw, ph):
        size = node.get("Size", (0, 0, 0, 0))
        constraint = node.get("SizeConstraint", "RelativeXY")
        if constraint == "RelativeXX":
            bw = bh = pw
        elif constraint == "RelativeYY":
            bw = bh = ph
        else:
            bw, bh = pw, ph
        return (size[0] * bw + size[1], size[2] * bh + size[3])

    def _ui_scale(self, node):
        s = node.first_of_class("UIScale")
        return float(s.get("Scale", 1.0)) if s else 1.0

    def _padding(self, node, w, h):
        p = node.first_of_class("UIPadding")
        if not p:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            _udim(p.get("PaddingLeft", (0, 0)), w),
            _udim(p.get("PaddingTop", (0, 0)), h),
            _udim(p.get("PaddingRight", (0, 0)), w),
            _udim(p.get("PaddingBottom", (0, 0)), h),
        )

    def _corner_radius(self, node, w, h):
        """UICorner 的半徑。

        現代 Roblox **不寫 CornerRadius**,寫的是 TopLeftRadius 那四個
        (CornerRadius 已是 API dump 標成 CanSave:false 的 legacy 別名)。
        只讀 CornerRadius 的話,真實檔案裡設了 2px 圓角的元素會全部被畫成預設 8px。
        這裡以「XML 裡真的有寫的那個」優先,四角不同時取最大值當近似
        (渲染只畫一個半徑)。
        """
        c = node.first_of_class("UICorner")
        if not c:
            return 0.0
        written = [c.props[k] for k in
                   ("TopLeftRadius", "TopRightRadius", "BottomLeftRadius", "BottomRightRadius")
                   if k in c.props]
        if not written and "CornerRadius" in c.props:
            written = [c.props["CornerRadius"]]
        if not written:
            written = [c.get("CornerRadius", (0.0, 8.0))]
        r = max(written, key=lambda u: _udim(u, min(w, h)))
        return min(_udim(r, min(w, h)), min(w, h) / 2)

    def _layout_object(self, node):
        for cls in ("UIListLayout", "UIGridLayout", "UITableLayout", "UIPageLayout"):
            obj = node.first_of_class(cls)
            if obj:
                return obj
        return None

    def _aspect(self, node, w, h, pw, ph):
        c = node.first_of_class("UIAspectRatioConstraint")
        if not c:
            return w, h
        ratio = float(c.get("AspectRatio", 1.0)) or 1.0
        atype = c.get("AspectType", "FitWithinMaxSize")
        dom = c.get("DominantAxis", "Width")
        if atype == "ScaleWithParentSize":
            w, h = pw, ph
        if atype == "FitWithinMaxSize":
            if w / ratio <= h:
                h = w / ratio
            else:
                w = h * ratio
        else:
            if dom == "Width":
                h = w / ratio
            else:
                w = h * ratio
        return w, h

    def _size_constraint(self, node, w, h):
        c = node.first_of_class("UISizeConstraint")
        if not c:
            return w, h
        mn = c.get("MinSize", (0.0, 0.0))
        mx = c.get("MaxSize", (float("inf"), float("inf")))
        return (min(max(w, mn[0]), mx[0]), min(max(h, mn[1]), mx[1]))

    # ------------------------------------------------------------------
    def _invisible_reason(self, node, cls, box):
        """Visible=true 卻什麼都看不到的原因。

        「UI 沒出現」最常見的兩個原因,一個是 Visible=false,另一個就是
        透明度被設成 1 —— 後者在 Explorer 裡完全看不出來,所以要主動點名。
        純粹當版面容器的透明 Frame 不算(那是正常寫法),只在它連子元素
        都沒有時才回報。
        """
        reasons = []
        bg = float(node.get("BackgroundTransparency", 0.0) or 0.0)
        opaque_bg = bg < 0.999
        if int(node.get("BorderSizePixel", 1) or 0) > 0:
            opaque_bg = True
        us = node.first_of_class("UIStroke")
        if us and us.get("Enabled", True) and \
                float(us.get("Transparency", 0.0) or 0.0) < 0.999:
            opaque_bg = True

        if cls in defaults.TEXT_CLASSES:
            has_text = bool((node.get("Text", "") or "").strip())
            t = float(node.get("TextTransparency", 0.0) or 0.0)
            ts = float(node.get("TextStrokeTransparency", 1.0) or 1.0)
            if has_text and t >= 0.999 and ts >= 0.999:
                reasons.append("文字全透明")
            elif not has_text:
                reasons.append("Text 是空的")
            if not reasons:
                return None
        elif cls in defaults.IMAGE_CLASSES:
            img = node.get("Image", "") or ""
            it = float(node.get("ImageTransparency", 0.0) or 0.0)
            if img and it >= 0.999:
                reasons.append("圖片全透明")
            elif not img:
                reasons.append("Image 是空的")
            if not reasons:
                return None

        if opaque_bg:
            return None
        if not reasons:
            # 透明容器:有子元素就是正常寫法,沒有才算真的空
            if any(defaults.is_renderable(c.class_name) for c in node.children):
                return None
            reasons.append("空的透明框")
        return " + ".join(reasons)

    def _is_text(self, cls):
        return cls in defaults.TEXT_CLASSES

    def _text_runs(self, node):
        raw = node.get("Text", "")
        if node.class_name == "TextBox" and not raw:
            raw = node.get("PlaceholderText", "")
        if raw is None:
            raw = ""
        return textmod.runs_from(str(raw), bool(node.get("RichText", False)))

    def _text_face(self, node):
        face = node.get("FontFace", None)
        if face is None:
            legacy = node.props.get("Font")
            from .enums import LEGACY_FONT
            if isinstance(legacy, int) and legacy in LEGACY_FONT:
                fam, weight, italic = LEGACY_FONT[legacy]
                return (fam, weight, "Italic" if italic else "Normal")
            face = ("SourceSansPro", 400, "Normal")
        return face

    def _layout_text(self, box, node):
        runs = self._text_runs(node)
        face = self._text_face(node)
        pad = self._padding(node, box.w, box.h)
        avail_w = max(1.0, box.w - pad[0] - pad[2])
        avail_h = max(1.0, box.h - pad[1] - pad[3])
        wrapped = bool(node.get("TextWrapped", False))
        line_h = float(node.get("LineHeight", 1.0) or 1.0)
        mvg = int(node.get("MaxVisibleGraphemes", -1) or -1)

        if node.get("TextScaled", False):
            tc = node.first_of_class("UITextSizeConstraint")
            mn = int(tc.get("MinTextSize", 1)) if tc else 1
            mx = int(tc.get("MaxTextSize", 100)) if tc else 100
            size = textmod.fit_scaled(runs, face, avail_w, avail_h, True,
                                      line_h, mn, mx, mvg)
            wrapped = True
        else:
            size = float(node.get("TextSize", 14) or 14)
            tc = node.first_of_class("UITextSizeConstraint")
            if tc:
                size = min(max(size, int(tc.get("MinTextSize", 1))),
                           int(tc.get("MaxTextSize", 100)))

        lines, tw, th = textmod.layout(runs, face, size, avail_w, wrapped,
                                       line_h, mvg)
        box.text_size = size
        box.lines = lines
        box.text_w, box.text_h = tw, th

    def _auto_size(self, node, w, h, auto, pw, ph):
        if auto == "None":
            return w, h
        pad = self._padding(node, w, h)
        if self._is_text(node.class_name):
            runs = self._text_runs(node)
            face = self._text_face(node)
            size = float(node.get("TextSize", 14) or 14)
            line_h = float(node.get("LineHeight", 1.0) or 1.0)
            wrapped = bool(node.get("TextWrapped", False))
            limit = max(1.0, w - pad[0] - pad[2]) if auto in ("Y",) or wrapped else 1e9
            tw, th = textmod.measure(runs, face, size, limit, wrapped, line_h)
            if auto in ("X", "XY"):
                w = tw + pad[0] + pad[2]
            if auto in ("Y", "XY"):
                h = th + pad[1] + pad[3]
            return w, h

        # 容器:量子元素撐出來的外框(只算 offset 部分,scale 子元素不參與)
        max_x = max_y = 0.0
        layout_obj = self._layout_object(node)
        kids = self._sorted_children(node, layout_obj)
        if layout_obj is not None and layout_obj.class_name == "UIListLayout":
            total, cross = 0.0, 0.0
            padding = _udim(layout_obj.get("Padding", (0, 0)),
                            w if layout_obj.get("FillDirection", "Vertical") == "Horizontal" else h)
            vertical = layout_obj.get("FillDirection", "Vertical") == "Vertical"
            for i, c in enumerate(kids):
                cw, chh = self._base_size(c, w, h)
                if vertical:
                    total += chh + (padding if i else 0)
                    cross = max(cross, cw)
                else:
                    total += cw + (padding if i else 0)
                    cross = max(cross, chh)
            max_x, max_y = (cross, total) if vertical else (total, cross)
        else:
            for c in kids:
                cw, chh = self._base_size(c, w, h)
                pos = c.get("Position", (0, 0, 0, 0))
                anchor = c.get("AnchorPoint", (0.0, 0.0))
                cx = pos[0] * w + pos[1] - anchor[0] * cw
                cy = pos[2] * h + pos[3] - anchor[1] * chh
                max_x = max(max_x, cx + cw)
                max_y = max(max_y, cy + chh)
        if auto in ("X", "XY"):
            w = max_x + pad[0] + pad[2]
        if auto in ("Y", "XY"):
            h = max_y + pad[1] + pad[3]
        return w, h

    # ------------------------------------------------------------------
    def _canvas_region(self, node, box, cox, coy, cw, ch):
        canvas = node.get("CanvasSize", (0, 0, 2, 0))
        cpos = node.get("CanvasPosition", (0.0, 0.0))
        thickness = float(node.get("ScrollBarThickness", 12) or 0)
        window_w, window_h = cw, ch
        if node.get("VerticalScrollBarInset", "None") == "ScrollBar":
            window_w = max(0.0, cw - thickness)
        if node.get("HorizontalScrollBarInset", "None") == "ScrollBar":
            window_h = max(0.0, ch - thickness)
        canvas_w = max(window_w, canvas[0] * window_w + canvas[1])
        canvas_h = max(window_h, canvas[2] * window_h + canvas[3])
        return (cox - cpos[0], coy - cpos[1], canvas_w, canvas_h)

    # ------------------------------------------------------------------
    def _list(self, layout_obj, kids, size, origin):
        cw, ch = size
        vertical = layout_obj.get("FillDirection", "Vertical") == "Vertical"
        halign = layout_obj.get("HorizontalAlignment", "Left")
        valign = layout_obj.get("VerticalAlignment", "Top")
        padding = _udim(layout_obj.get("Padding", (0, 0)), ch if vertical else cw)

        sized = []
        for c in kids:
            w, h = self._base_size(c, cw, ch)
            s = self._ui_scale(c)
            w, h = w * s, h * s
            auto = c.get("AutomaticSize", "None")
            if auto != "None":
                w, h = self._auto_size(c, w, h, auto, cw, ch)
            w, h = self._aspect(c, w, h, cw, ch)
            w, h = self._size_constraint(c, w, h)
            sized.append((c, w, h))

        total = sum((h if vertical else w) for _, w, h in sized)
        total += padding * max(0, len(sized) - 1)

        main_align = valign if vertical else halign
        if main_align in ("Center",):
            cursor = ((ch if vertical else cw) - total) / 2
        elif main_align in ("Bottom", "Right"):
            cursor = (ch if vertical else cw) - total
        else:
            cursor = 0.0

        cross_align = halign if vertical else valign
        out = []
        for c, w, h in sized:
            extent = ch if vertical else cw
            del extent
            cross_room = (cw - w) if vertical else (ch - h)
            if cross_align == "Center":
                cross = cross_room / 2
            elif cross_align in ("Right", "Bottom"):
                cross = cross_room
            else:
                cross = 0.0
            if vertical:
                out.append((c, cross, cursor, w, h))
                cursor += h + padding
            else:
                out.append((c, cursor, cross, w, h))
                cursor += w + padding
        return out

    def _grid(self, layout_obj, kids, size):
        cw, ch = size
        cell = _udim2(layout_obj.get("CellSize", (0, 100, 0, 100)), cw, ch)
        pad = _udim2(layout_obj.get("CellPadding", (0, 5, 0, 5)), cw, ch)
        horizontal = layout_obj.get("FillDirection", "Horizontal") == "Horizontal"
        max_cells = int(layout_obj.get("FillDirectionMaxCells", 0) or 0)
        corner = layout_obj.get("StartCorner", "TopLeft")
        halign = layout_obj.get("HorizontalAlignment", "Left")
        valign = layout_obj.get("VerticalAlignment", "Top")

        span = cw if horizontal else ch
        cell_span = (cell[0] if horizontal else cell[1]) + (pad[0] if horizontal else pad[1])
        if max_cells <= 0:
            max_cells = max(1, int((span + (pad[0] if horizontal else pad[1]) + 1e-6) // cell_span)) if cell_span > 0 else 1

        rows = (len(kids) + max_cells - 1) // max_cells if max_cells else 1
        grid_w = (max_cells * cell[0] + (max_cells - 1) * pad[0]) if horizontal else (rows * cell[0] + (rows - 1) * pad[0])
        grid_h = (rows * cell[1] + (rows - 1) * pad[1]) if horizontal else (max_cells * cell[1] + (max_cells - 1) * pad[1])

        if halign == "Center":
            ox0 = (cw - grid_w) / 2
        elif halign == "Right":
            ox0 = cw - grid_w
        else:
            ox0 = 0.0
        if valign == "Center":
            oy0 = (ch - grid_h) / 2
        elif valign == "Bottom":
            oy0 = ch - grid_h
        else:
            oy0 = 0.0

        out = []
        for i, c in enumerate(kids):
            if horizontal:
                col, row = i % max_cells, i // max_cells
            else:
                col, row = i // max_cells, i % max_cells
            if corner in ("TopRight", "BottomRight"):
                col = (max_cells - 1 - col) if horizontal else col
            if corner in ("BottomLeft", "BottomRight"):
                row = (rows - 1 - row) if horizontal else row
            x = ox0 + col * (cell[0] + pad[0])
            y = oy0 + row * (cell[1] + pad[1])
            out.append((c, x, y, cell[0], cell[1]))
        return out
