"""把 layout 算出來的繪製清單畫成 PNG。

每個元素先畫在自己的小圖層上,再依變換貼回主畫布 —— 這樣旋轉、裁切、
UIStroke 溢出都能正確處理,又不必為每個元素配一張全畫布大小的圖。
"""

import math

from PIL import Image, ImageChops, ImageDraw

from . import defaults

CHECKER = ((58, 58, 62), (48, 48, 52))


def _rgb(c):
    if c is None:
        c = (0, 0, 0)
    return tuple(max(0, min(255, int(round(v * 255)))) for v in c[:3])


def _alpha(transparency):
    return max(0, min(255, int(round((1.0 - float(transparency or 0.0)) * 255))))


def _sample_sequence(seq, t):
    """ColorSequence / NumberSequence 取樣(線性內插)。"""
    if not seq:
        return None
    if t <= seq[0][0]:
        return seq[0][1]
    if t >= seq[-1][0]:
        return seq[-1][1]
    for i in range(len(seq) - 1):
        t0, v0 = seq[i]
        t1, v1 = seq[i + 1]
        if t0 <= t <= t1:
            f = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            if isinstance(v0, tuple):
                return tuple(v0[k] + (v1[k] - v0[k]) * f for k in range(3))
            return v0 + (v1 - v0) * f
    return seq[-1][1]


def _rounded_mask(size, radius, supersample=4):
    """圓角遮罩。放大四倍再縮回來當作抗鋸齒 —— PIL 的圓角本身沒有 AA。"""
    w, h = size
    if w <= 0 or h <= 0:
        return Image.new("L", (max(w, 1), max(h, 1)), 0)
    if radius <= 0.5:
        return Image.new("L", (w, h), 255)
    s = supersample
    big = Image.new("L", (w * s, h * s), 0)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=radius * s, fill=255)
    return big.resize((w, h), Image.LANCZOS)


class Renderer:
    def __init__(self, viewport, fetcher=None, background="checker",
                 show_hidden=False, outline=False, scale=1):
        self.vw, self.vh = viewport
        self.fetcher = fetcher
        self.background = background
        self.show_hidden = show_hidden
        self.outline = outline
        self.scale = scale
        self._clip_cache = {}
        self.warnings = []
        self.missing_images = set()

    # ------------------------------------------------------------------
    def render(self, boxes):
        canvas = self._make_background()
        for box in boxes:
            try:
                self._draw_box(canvas, box)
            except Exception as exc:  # 單一元素畫壞不該讓整張圖失敗
                self.warnings.append(f"{box.node.path}: {type(exc).__name__}: {exc}")
        if self.scale != 1:
            canvas = canvas.resize(
                (int(self.vw * self.scale), int(self.vh * self.scale)),
                Image.LANCZOS)
        return canvas

    def _make_background(self):
        if self.background == "transparent":
            return Image.new("RGBA", (self.vw, self.vh), (0, 0, 0, 0))
        if self.background == "black":
            return Image.new("RGBA", (self.vw, self.vh), (0, 0, 0, 255))
        if self.background == "white":
            return Image.new("RGBA", (self.vw, self.vh), (255, 255, 255, 255))
        # 棋盤格 —— 一眼就能看出哪裡是「沒東西」而不是「畫了黑色」
        img = Image.new("RGBA", (self.vw, self.vh), CHECKER[0] + (255,))
        d = ImageDraw.Draw(img)
        cell = 16
        for y in range(0, self.vh, cell):
            for x in range(0, self.vw, cell):
                if (x // cell + y // cell) % 2:
                    d.rectangle([x, y, x + cell - 1, y + cell - 1],
                                fill=CHECKER[1] + (255,))
        return img

    # ------------------------------------------------------------------
    def _draw_box(self, canvas, box):
        node = box.node
        cls = node.class_name
        w, h = int(round(box.w)), int(round(box.h))
        if w <= 0 or h <= 0:
            return
        if w > 8000 or h > 8000:
            self.warnings.append(f"{node.path}: 尺寸過大 {w}x{h},略過")
            return

        stroke = self._stroke_of(node)
        margin = int(math.ceil(stroke[1])) + 2 if stroke else 2
        lw, lh = w + margin * 2, h + margin * 2
        layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        rect = (margin, margin, margin + w - 1, margin + h - 1)

        radius = self._corner_radius(node, w, h)
        shape_mask = _rounded_mask((w, h), radius)

        faded = self._group_fade(box)

        # ---- 背景 ------------------------------------------------------
        bg_alpha = _alpha(node.get("BackgroundTransparency", 0.0))
        if bg_alpha > 0:
            fill = Image.new("RGBA", (w, h),
                             _rgb(node.get("BackgroundColor3")) + (bg_alpha,))
            grad = self._gradient(node, w, h)
            if grad is not None:
                fill = self._apply_gradient(fill, grad)
            fill.putalpha(ImageChops.multiply(fill.getchannel("A"), shape_mask))
            layer.alpha_composite(fill, (margin, margin))

        # ---- 邊框(BorderSizePixel) --------------------------------------
        bsp = int(node.get("BorderSizePixel", 1) or 0)
        if bsp > 0:
            mode = node.get("BorderMode", "Outline")
            if mode == "Outline":
                r = (rect[0] - bsp, rect[1] - bsp, rect[2] + bsp, rect[3] + bsp)
            elif mode == "Inset":
                r = rect
            else:
                r = (rect[0] - bsp / 2, rect[1] - bsp / 2,
                     rect[2] + bsp / 2, rect[3] + bsp / 2)
            col = _rgb(node.get("BorderColor3")) + (255,)
            if radius > 0.5:
                d.rounded_rectangle(r, radius=radius + (bsp if mode == "Outline" else 0),
                                    outline=col, width=bsp)
            else:
                d.rectangle(r, outline=col, width=bsp)

        # ---- 圖片 ------------------------------------------------------
        if cls in defaults.IMAGE_CLASSES:
            self._draw_image(layer, node, w, h, margin, shape_mask)

        # ---- ViewportFrame / VideoFrame 佔位 ----------------------------
        if cls in ("ViewportFrame", "VideoFrame"):
            self._draw_placeholder(d, rect, cls)

        # ---- 文字 ------------------------------------------------------
        if cls in defaults.TEXT_CLASSES and box.lines:
            self._draw_text(layer, box, node, margin, w, h)

        # ---- UIStroke ---------------------------------------------------
        if stroke:
            color, thickness, alpha = stroke
            if radius > 0.5:
                d.rounded_rectangle(
                    (rect[0] - thickness / 2, rect[1] - thickness / 2,
                     rect[2] + thickness / 2, rect[3] + thickness / 2),
                    radius=radius + thickness / 2,
                    outline=color + (alpha,), width=max(1, int(round(thickness))))
            else:
                d.rectangle(
                    (rect[0] - thickness / 2, rect[1] - thickness / 2,
                     rect[2] + thickness / 2, rect[3] + thickness / 2),
                    outline=color + (alpha,), width=max(1, int(round(thickness))))

        # ---- 捲軸 ------------------------------------------------------
        if cls == "ScrollingFrame":
            self._draw_scrollbar(d, node, rect, w, h)

        # ---- 除錯外框 ---------------------------------------------------
        if self.outline:
            d.rectangle(rect, outline=(255, 0, 128, 180), width=1)
        if box.hidden_by:
            self._dash_rect(d, rect, (255, 200, 0, 200)
                            if box.hidden_by == "self" else (255, 120, 0, 140))
        elif box.invisible and self.show_hidden:
            # Visible=true 但透明度讓它看不見 —— 只標位置,不強行畫實體,
            # 否則畫面會跟實際執行時差太多
            self._dash_rect(d, rect, (80, 200, 255, 200))

        if faded < 1.0:
            a = layer.getchannel("A").point(lambda v: int(v * faded))
            layer.putalpha(a)

        self._blit(canvas, layer, box, margin)

    # ------------------------------------------------------------------
    def _group_fade(self, box):
        """CanvasGroup 的 GroupTransparency 近似:直接讓子樹整體變淡。

        嚴格語意是「先把子樹合成成一張圖再套 alpha」,重疊處會有差,
        但對預覽而言差異很小,換來不必為每個 CanvasGroup 開全畫布圖層。
        """
        fade = 1.0
        n = box.node.parent
        while n is not None:
            if n.class_name == "CanvasGroup":
                fade *= 1.0 - float(n.get("GroupTransparency", 0.0) or 0.0)
            n = n.parent
        return fade

    def _corner_radius(self, node, w, h):
        c = node.first_of_class("UICorner")
        if not c:
            return 0.0
        r = c.get("CornerRadius", (0.0, 8.0))
        return max(0.0, min(r[0] * min(w, h) + r[1], min(w, h) / 2))

    def _stroke_of(self, node):
        s = node.first_of_class("UIStroke")
        if not s or not s.get("Enabled", True):
            return None
        alpha = _alpha(s.get("Transparency", 0.0))
        if alpha <= 0:
            return None
        return (_rgb(s.get("Color")), max(0.0, float(s.get("Thickness", 1.0))), alpha)

    # ------------------------------------------------------------------
    def _gradient(self, node, w, h):
        g = node.first_of_class("UIGradient")
        if not g or not g.get("Enabled", True):
            return None
        colors = g.get("Color", [(0.0, (1, 1, 1))])
        trans = g.get("Transparency", [(0.0, 0.0)])
        rotation = float(g.get("Rotation", 0.0) or 0.0)
        offset = g.get("Offset", (0.0, 0.0))

        n = 256
        strip = Image.new("RGBA", (n, 1))
        px = strip.load()
        for i in range(n):
            t = i / (n - 1)
            c = _sample_sequence(colors, t) or (1, 1, 1)
            a = _sample_sequence(trans, t) or 0.0
            px[i, 0] = _rgb(c) + (_alpha(a),)

        diag = int(math.ceil(math.hypot(w, h))) + 2
        big = strip.resize((diag, diag), Image.BILINEAR)
        if abs(rotation) > 1e-6:
            big = big.rotate(-rotation, resample=Image.BILINEAR, expand=False)
        ox = int(round(offset[0] * w))
        oy = int(round(offset[1] * h))
        left = (diag - w) // 2 - ox
        top = (diag - h) // 2 - oy
        return big.crop((left, top, left + w, top + h))

    def _apply_gradient(self, base, grad):
        out = Image.new("RGBA", base.size)
        out.paste(grad)
        a = ImageChops.multiply(base.getchannel("A"), grad.getchannel("A"))
        # 顏色相乘:UIGradient 是把底色乘上漸層色
        rgb = ImageChops.multiply(base.convert("RGB"), grad.convert("RGB"))
        out = rgb.convert("RGBA")
        out.putalpha(a)
        return out

    # ------------------------------------------------------------------
    def _draw_image(self, layer, node, w, h, margin, shape_mask):
        url = node.get("Image", "") or node.get("ImageContent", "")
        img = None
        if url and self.fetcher:
            img = self.fetcher.image(url)
        if url and img is None:
            self.missing_images.add(url)

        if img is None:
            if url:
                d = ImageDraw.Draw(layer)
                self._draw_placeholder(d, (margin, margin, margin + w - 1,
                                           margin + h - 1), "Image")
            return

        # sprite sheet 裁切
        rect_off = node.get("ImageRectOffset", (0, 0))
        rect_size = node.get("ImageRectSize", (0, 0))
        if rect_size[0] > 0 and rect_size[1] > 0:
            img = img.crop((int(rect_off[0]), int(rect_off[1]),
                            int(rect_off[0] + rect_size[0]),
                            int(rect_off[1] + rect_size[1])))

        scale_type = node.get("ScaleType", "Stretch")
        if scale_type == "Slice":
            out = self._nine_slice(img, w, h, node)
        elif scale_type == "Tile":
            out = self._tile(img, w, h, node)
        elif scale_type == "Fit":
            out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            r = min(w / img.width, h / img.height)
            nw, nh = max(1, int(img.width * r)), max(1, int(img.height * r))
            out.paste(img.resize((nw, nh), Image.LANCZOS),
                      ((w - nw) // 2, (h - nh) // 2))
        elif scale_type == "Crop":
            r = max(w / img.width, h / img.height)
            nw, nh = max(1, int(img.width * r)), max(1, int(img.height * r))
            big = img.resize((nw, nh), Image.LANCZOS)
            out = big.crop(((nw - w) // 2, (nh - h) // 2,
                            (nw - w) // 2 + w, (nh - h) // 2 + h))
        else:
            out = img.resize((w, h), Image.LANCZOS)

        tint = node.get("ImageColor3", (1, 1, 1))
        if tint != (1, 1, 1):
            solid = Image.new("RGB", out.size, _rgb(tint))
            a = out.getchannel("A")
            out = ImageChops.multiply(out.convert("RGB"), solid).convert("RGBA")
            out.putalpha(a)

        ia = _alpha(node.get("ImageTransparency", 0.0))
        a = out.getchannel("A")
        if ia < 255:
            a = a.point(lambda v: v * ia // 255)
        a = ImageChops.multiply(a, shape_mask)

        grad = self._gradient(node, w, h)
        if grad is not None:
            out = self._apply_gradient(out, grad)
            a = ImageChops.multiply(a, out.getchannel("A"))
        out.putalpha(a)
        layer.alpha_composite(out, (margin, margin))

    def _nine_slice(self, img, w, h, node):
        sc = node.get("SliceCenter", (0, 0, 0, 0))
        scale = float(node.get("SliceScale", 1.0) or 1.0)
        iw, ih = img.size
        x0, y0, x1, y1 = [int(v) for v in sc]
        if x1 <= x0 or y1 <= y0:
            return img.resize((w, h), Image.LANCZOS)
        left, top = x0, y0
        right, bottom = iw - x1, ih - y1
        dl, dt = int(left * scale), int(top * scale)
        dr, db = int(right * scale), int(bottom * scale)
        dl, dr = min(dl, w), min(dr, max(0, w - min(dl, w)))
        dt, db = min(dt, h), min(db, max(0, h - min(dt, h)))
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        def part(box, dest_box):
            bw = dest_box[2] - dest_box[0]
            bh = dest_box[3] - dest_box[1]
            if bw <= 0 or bh <= 0:
                return
            if box[2] - box[0] <= 0 or box[3] - box[1] <= 0:
                return
            out.paste(img.crop(box).resize((bw, bh), Image.LANCZOS), dest_box[:2])

        mx0, mx1 = dl, w - dr
        my0, my1 = dt, h - db
        part((0, 0, x0, y0), (0, 0, mx0, my0))
        part((x1, 0, iw, y0), (mx1, 0, w, my0))
        part((0, y1, x0, ih), (0, my1, mx0, h))
        part((x1, y1, iw, ih), (mx1, my1, w, h))
        part((x0, 0, x1, y0), (mx0, 0, mx1, my0))
        part((x0, y1, x1, ih), (mx0, my1, mx1, h))
        part((0, y0, x0, y1), (0, my0, mx0, my1))
        part((x1, y0, iw, y1), (mx1, my0, w, my1))
        part((x0, y0, x1, y1), (mx0, my0, mx1, my1))
        return out

    def _tile(self, img, w, h, node):
        ts = node.get("TileSize", (1.0, 0.0, 1.0, 0.0))
        tw = max(1, int(round(ts[0] * w + ts[1])))
        th = max(1, int(round(ts[2] * h + ts[3])))
        tile = img.resize((tw, th), Image.LANCZOS)
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for y in range(0, h, th):
            for x in range(0, w, tw):
                out.alpha_composite(tile, (x, y))
        return out

    def _draw_placeholder(self, d, rect, kind):
        x0, y0, x1, y1 = [int(v) for v in rect]
        d.rectangle(rect, outline=(120, 130, 150, 200), width=1)
        d.line([x0, y0, x1, y1], fill=(120, 130, 150, 120), width=1)
        d.line([x0, y1, x1, y0], fill=(120, 130, 150, 120), width=1)

    def _dash_rect(self, d, rect, color, dash=5):
        x0, y0, x1, y1 = [int(v) for v in rect]
        for x in range(x0, x1, dash * 2):
            d.line([x, y0, min(x + dash, x1), y0], fill=color)
            d.line([x, y1, min(x + dash, x1), y1], fill=color)
        for y in range(y0, y1, dash * 2):
            d.line([x0, y, x0, min(y + dash, y1)], fill=color)
            d.line([x1, y, x1, min(y + dash, y1)], fill=color)

    # ------------------------------------------------------------------
    def _draw_text(self, layer, box, node, margin, w, h):
        d = ImageDraw.Draw(layer)
        pad_node = node.first_of_class("UIPadding")
        pl = pt = pr = pb = 0.0
        if pad_node:
            pl = pad_node.get("PaddingLeft", (0, 0))[0] * w + pad_node.get("PaddingLeft", (0, 0))[1]
            pt = pad_node.get("PaddingTop", (0, 0))[0] * h + pad_node.get("PaddingTop", (0, 0))[1]
            pr = pad_node.get("PaddingRight", (0, 0))[0] * w + pad_node.get("PaddingRight", (0, 0))[1]
            pb = pad_node.get("PaddingBottom", (0, 0))[0] * h + pad_node.get("PaddingBottom", (0, 0))[1]

        area_x = margin + pl
        area_y = margin + pt
        area_w = max(1.0, w - pl - pr)
        area_h = max(1.0, h - pt - pb)

        size = box.text_size or 14
        line_h = float(node.get("LineHeight", 1.0) or 1.0) * size
        total_h = len(box.lines) * line_h

        yalign = node.get("TextYAlignment", "Center")
        if yalign == "Center":
            y = area_y + (area_h - total_h) / 2
        elif yalign == "Bottom":
            y = area_y + area_h - total_h
        else:
            y = area_y

        xalign = node.get("TextXAlignment", "Center")
        base_color = _rgb(node.get("TextColor3"))
        if node.class_name == "TextBox" and not (node.get("Text", "") or ""):
            base_color = _rgb(node.get("PlaceholderColor3", (178 / 255,) * 3))
        text_alpha = _alpha(node.get("TextTransparency", 0.0))
        stroke_alpha = _alpha(node.get("TextStrokeTransparency", 1.0))
        stroke_color = _rgb(node.get("TextStrokeColor3"))

        # TextStrokeTransparency 畫的固定是 1px 外框;UIStroke 才吃 Thickness
        stroke_width = 1
        ui_stroke = node.first_of_class("UIStroke")
        if ui_stroke and ui_stroke.get("Enabled", True) and \
                ui_stroke.get("ApplyStrokeMode", "Contextual") == "Contextual":
            sa = _alpha(ui_stroke.get("Transparency", 0.0))
            if sa > 0:
                stroke_alpha = sa
                stroke_color = _rgb(ui_stroke.get("Color"))
                stroke_width = max(1, int(round(float(ui_stroke.get("Thickness", 1.0)))))

        truncate = node.get("TextTruncate", "None")

        for line in box.lines:
            if xalign == "Center":
                x = area_x + (area_w - line.width) / 2
            elif xalign == "Right":
                x = area_x + area_w - line.width
            else:
                x = area_x
            for run, piece, font, adv in line.pieces:
                color = _rgb(run.color) if run.color else base_color
                if truncate == "AtEnd" and x + adv > area_x + area_w + 0.5:
                    piece = self._ellipsize(piece, font, area_x + area_w - x)
                    adv = font.getlength(piece)
                if stroke_alpha > 0:
                    d.text((x, y), piece, font=font,
                           fill=stroke_color + (stroke_alpha,), anchor="la",
                           stroke_width=stroke_width,
                           stroke_fill=stroke_color + (stroke_alpha,))
                if run.stroke:
                    sc, st = run.stroke
                    d.text((x, y), piece, font=font, anchor="la",
                           fill=_rgb(sc) + (255,),
                           stroke_width=max(1, int(round(st))),
                           stroke_fill=_rgb(sc) + (255,))
                d.text((x, y), piece, font=font, fill=color + (text_alpha,),
                       anchor="la")
                if run.underline:
                    uy = y + size * 0.92
                    d.line([x, uy, x + adv, uy], fill=color + (text_alpha,), width=1)
                if run.strike:
                    sy = y + size * 0.55
                    d.line([x, sy, x + adv, sy], fill=color + (text_alpha,), width=1)
                x += adv
            y += line_h

    def _ellipsize(self, piece, font, room):
        if room <= 0:
            return ""
        ell = "…"
        ew = font.getlength(ell)
        acc = ""
        for ch in piece:
            if font.getlength(acc + ch) + ew > room:
                break
            acc += ch
        return acc + ell

    # ------------------------------------------------------------------
    def _draw_scrollbar(self, d, node, rect, w, h):
        thickness = int(node.get("ScrollBarThickness", 12) or 0)
        if thickness <= 0:
            return
        color = _rgb(node.get("ScrollBarImageColor3", (0, 0, 0)))
        alpha = _alpha(node.get("ScrollBarImageTransparency", 0.0))
        if alpha <= 0:
            return
        direction = node.get("ScrollingDirection", "XY")
        canvas = node.get("CanvasSize", (0, 0, 2, 0))
        canvas_h = canvas[2] * h + canvas[3]
        canvas_w = canvas[0] * w + canvas[1]
        pos = node.get("CanvasPosition", (0, 0))
        x0, y0, x1, y1 = rect

        if direction in ("Y", "XY") and canvas_h > h:
            left = x1 - thickness + 1
            frac = min(1.0, h / canvas_h)
            bar_h = max(12, h * frac)
            off = (h - bar_h) * (pos[1] / max(1.0, canvas_h - h))
            d.rectangle([left, y0, x1, y1], fill=color + (alpha // 4,))
            d.rounded_rectangle([left, y0 + off, x1, y0 + off + bar_h],
                                radius=thickness / 2, fill=color + (alpha,))
        if direction in ("X", "XY") and canvas_w > w:
            top = y1 - thickness + 1
            frac = min(1.0, w / canvas_w)
            bar_w = max(12, w * frac)
            off = (w - bar_w) * (pos[0] / max(1.0, canvas_w - w))
            d.rectangle([x0, top, x1, y1], fill=color + (alpha // 4,))
            d.rounded_rectangle([x0 + off, top, x0 + off + bar_w, y1],
                                radius=thickness / 2, fill=color + (alpha,))

    # ------------------------------------------------------------------
    def _clip_mask(self, clips):
        """把祖先鏈上所有 ClipsDescendants 的框交集成一張全畫布遮罩。"""
        if not clips:
            return None
        key = tuple((id(b), round(r, 2)) for b, r in clips)
        if key in self._clip_cache:
            return self._clip_cache[key]

        mask = Image.new("L", (self.vw, self.vh), 255)
        for cbox, radius in clips:
            layer = Image.new("L", (self.vw, self.vh), 0)
            cw, ch = int(round(cbox.w)), int(round(cbox.h))
            if cw <= 0 or ch <= 0:
                mask = Image.new("L", (self.vw, self.vh), 0)
                break
            shape = _rounded_mask((cw, ch), radius)
            if cbox.rotated:
                angle = math.degrees(math.atan2(cbox.matrix[1], cbox.matrix[0]))
                rot = shape.rotate(-angle, resample=Image.BICUBIC, expand=True)
                ccx, ccy = cbox.to_canvas(cbox.x + cbox.w / 2, cbox.y + cbox.h / 2)
                layer.paste(rot, (int(round(ccx - rot.width / 2)),
                                  int(round(ccy - rot.height / 2))))
            else:
                cx, cy = cbox.to_canvas(cbox.x, cbox.y)
                layer.paste(shape, (int(round(cx)), int(round(cy))))
            mask = ImageChops.multiply(mask, layer)
        self._clip_cache[key] = mask
        return mask

    def _blit(self, canvas, layer, box, margin):
        mask = self._clip_mask(box.clips)
        if box.rotated:
            angle = math.degrees(math.atan2(box.matrix[1], box.matrix[0]))
            layer = layer.rotate(-angle, resample=Image.BICUBIC, expand=True)
            cx, cy = box.to_canvas(box.x + box.w / 2, box.y + box.h / 2)
            px = int(round(cx - layer.width / 2))
            py = int(round(cy - layer.height / 2))
        else:
            ax, ay = box.to_canvas(box.x, box.y)
            px = int(round(ax)) - margin
            py = int(round(ay)) - margin

        if mask is not None:
            region = mask.crop((px, py, px + layer.width, py + layer.height))
            layer = layer.copy()
            layer.putalpha(ImageChops.multiply(layer.getchannel("A"), region))

        # 裁掉畫布外的部分,alpha_composite 不吃負座標
        sx = max(0, -px)
        sy = max(0, -py)
        ex = min(layer.width, self.vw - px)
        ey = min(layer.height, self.vh - py)
        if ex <= sx or ey <= sy:
            return
        if (sx, sy, ex, ey) != (0, 0, layer.width, layer.height):
            layer = layer.crop((sx, sy, ex, ey))
            px += sx
            py += sy
        canvas.alpha_composite(layer, (px, py))
