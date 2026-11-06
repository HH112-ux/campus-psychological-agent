#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「心屿」小程序的图标资产（纯代码绘制，不依赖外部素材与图标库）。

产物：
  miniprogram/assets/tabbar/{home,chat,logs,mine}{,-active}.png   81×81 透明底
  miniprogram/assets/app-icon-144.png / app-icon-512.png          应用图标

用法：python3 tools/gen_icons.py
依赖：Pillow（`pip install pillow`）

设计约束（与 docs/ui-style-guide.md 一致）：
- 线宽统一 5.6px（81 画布），端点/转角全部圆收笔，不用尖角；
- 图标实体高度统一落在 40–42px（约画布 50–52%），四枚并排视觉重量一致；
- 常态色 = --text-3 #7A736B，选中色 = --brand #3E7A69，不新增色；
- 8 倍超采样后 LANCZOS 缩放，避免 81px 小尺寸下的锯齿。
"""
from __future__ import annotations

import os

from PIL import Image, ImageChops, ImageDraw

# —— 品牌色（与 miniprogram/app.wxss 的令牌同源） ——
BRAND = (0x3E, 0x7A, 0x69)        # --brand
BRAND_DEEP = (0x2F, 0x63, 0x55)   # --brand-ink
BRAND_SOFT = (0x5E, 0x9C, 0x8A)   # --brand-soft
NEUTRAL = (0x7A, 0x73, 0x6B)      # --text-3
CREAM = (0xF7, 0xF4, 0xEF)        # --bg
SAND = (0xC9, 0x7B, 0x3D)         # --accent

SS = 8          # 超采样倍数
CANVAS = 81     # TabBar 图标边长（微信规范）
STROKE = 5.6    # 统一线宽（81 画布坐标）

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABBAR_DIR = os.path.join(ROOT, "miniprogram", "assets", "tabbar")
ASSET_DIR = os.path.join(ROOT, "miniprogram", "assets")


def s(v: float) -> float:
    return v * SS


def stroke(d: ImageDraw.ImageDraw, pts, color, w=STROKE):
    """折线描边：圆角转折 + 圆头端点（Pillow 默认是平头）。"""
    p = [(s(x), s(y)) for x, y in pts]
    d.line(p, fill=color, width=int(round(s(w))), joint="curve")
    r = s(w) / 2.0
    for x, y in (p[0], p[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def arc(d: ImageDraw.ImageDraw, box, start, end, color, w=STROKE):
    """圆弧描边并补圆头（角度按 PIL 约定：0=3 点，顺时针增长）。"""
    d.arc([s(v) for v in box], start=start, end=end, fill=color, width=int(round(s(w))))
    cx = (box[0] + box[2]) / 2.0
    cy = (box[1] + box[3]) / 2.0
    rx = (box[2] - box[0]) / 2.0
    ry = (box[3] - box[1]) / 2.0
    import math

    r = s(w) / 2.0
    for ang in (start, end):
        rad = math.radians(ang)
        x, y = s(cx + rx * math.cos(rad)), s(cy + ry * math.sin(rad))
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def rrect(d, box, radius, color, w=STROKE):
    d.rounded_rectangle([s(v) for v in box], radius=s(radius), outline=color,
                        width=int(round(s(w))))


def new_tab_canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (CANVAS * SS, CANVAS * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


# —— 四枚图标：坐标全部在 81×81 空间内手写 ——

def draw_home(d, c):
    """首页：屋脊 + 墙面 + 拱门（拱门＝「回来坐坐」的手账语气，非尖角门）。"""
    stroke(d, [(20.0, 41.5), (40.5, 21.0), (61.0, 41.5)], c)
    stroke(d, [(25.5, 35.5), (25.5, 59.5), (55.5, 59.5), (55.5, 35.5)], c)
    arc(d, [33.5, 46.5, 47.5, 61.5], 180, 360, c)
    stroke(d, [(33.5, 54.0), (33.5, 59.5)], c)
    stroke(d, [(47.5, 54.0), (47.5, 59.5)], c)


def draw_chat(d, c):
    """对话：圆角气泡 + 下方小尾巴 + 三个呼吸点。"""
    rrect(d, [18.0, 21.0, 63.0, 53.5], 11.0, c)
    stroke(d, [(31.0, 53.0), (27.5, 62.5), (41.0, 53.5)], c)
    for x in (31.5, 40.5, 49.5):
        r = s(2.7)
        d.ellipse([s(x) - r, s(37.2) - r, s(x) + r, s(37.2) + r], fill=c)


def draw_logs(d, c):
    """情绪日志：一页纸 + 三行字（等宽行距、末行更短），读作「记录」而非图片/报表。"""
    rrect(d, [18.5, 18.5, 62.5, 62.5], 8.0, c)
    stroke(d, [(29.0, 31.0), (52.0, 31.0)], c)
    stroke(d, [(29.0, 40.5), (52.0, 40.5)], c)
    stroke(d, [(29.0, 50.0), (44.0, 50.0)], c)


def draw_mine(d, c):
    """我的：头 + 肩线（肩为圆弧，不留直角，避免「证件照」感）。"""
    d.ellipse([s(30.7), s(21.0), s(50.3), s(40.3)], outline=c, width=int(round(s(STROKE))))
    arc(d, [21.5, 46.5, 59.5, 77.5], 180, 360, c)


ICONS = {
    "home": draw_home,
    "chat": draw_chat,
    "logs": draw_logs,
    "mine": draw_mine,
}


def render_tab_icon(name: str, color, out_path: str) -> None:
    img, d = new_tab_canvas()
    ICONS[name](d, color)
    img = img.resize((CANVAS, CANVAS), Image.LANCZOS)
    img.save(out_path, "PNG", optimize=True)


# —— 应用图标 ——

def linear_gradient(size: int, top, bottom) -> Image.Image:
    strip = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        strip.putpixel((0, y), tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return strip.resize((size, size), Image.BILINEAR).convert("RGBA")


def render_app_icon(out_sizes=(512, 144)) -> None:
    """深屿青底 + 奶油色岛屿剪影 + 水面细纹 + 暖沙圆点（背景不做纯白）。

    岛屿用「椭圆 + 水平裁切」构成平底小山，避免出现悬空的白球；
    水纹只画在岛脚以下，不穿过岛体。
    """
    size = 512
    k = 4  # 超采样
    w = size * k
    horizon = 352  # 岛脚 / 水平线

    def scale(box):
        return [v * k for v in box]

    bg = linear_gradient(w, BRAND, BRAND_DEEP)

    # 岛屿：双峰山脊（收尖的轮廓 + 微凹坡面），平底落在水平线上；
    # 用收尖而非圆顶，避免在浅色背景里被读成「云」。
    def ridge(x, cx, half, height, power=1.55):
        t = 1.0 - abs(x - cx) / half
        return height * (t ** power) if t > 0 else 0.0

    pts = [(scale([0, horizon])[0], horizon * k)]
    for i in range(0, w + 1, max(1, int(w / 400))):
        x = i / k
        hgt = max(ridge(x, 204, 152, 122), ridge(x, 350, 112, 76))
        pts.append((i, (horizon - hgt) * k))
    pts.append((w, horizon * k))
    island = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    ImageDraw.Draw(island).polygon(pts, fill=CREAM + (255,))
    bg.alpha_composite(island)

    # 水面：水平线以下压一层深色，把「天 / 水」分开，避免读成云
    water = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    ImageDraw.Draw(water).rectangle([0, int(horizon * k), w, w], fill=BRAND_DEEP + (110,))
    bg.alpha_composite(water)

    # 倒影：镜像岛体并压低透明度，落在水面层上
    h = int(horizon * k)
    refl = bg.crop((0, 0, w, h)).transpose(Image.FLIP_TOP_BOTTOM)
    fade = Image.linear_gradient("L").resize((w, h)).transpose(Image.FLIP_TOP_BOTTOM)
    alpha = ImageChops.multiply(refl.getchannel("A"), fade.point(lambda v: int(v * 0.18)))
    refl.putalpha(alpha)
    bg.alpha_composite(refl, (0, h))

    d = ImageDraw.Draw(bg)
    # 水面：一道浅弧暗示水波，只出现在岛脚下方
    d.arc(scale([86, horizon + 34, 436, horizon + 124]), start=208, end=332,
          fill=BRAND_SOFT + (140,), width=int(11 * k))
    # 暖沙圆点：远处的日/月，是唯一的暖色高光
    d.ellipse(scale([322, 106, 384, 168]), fill=SAND + (255,))

    # 圆角方形遮罩（资料页与分享卡片都按圆角裁切，先自己收干净）
    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, w - 1], radius=int(w * 0.225),
                                           fill=255)
    bg.putalpha(mask)

    for px in out_sizes:
        out = bg.resize((px, px), Image.LANCZOS)
        out.save(os.path.join(ASSET_DIR, f"app-icon-{px}.png"), "PNG", optimize=True)


def main() -> None:
    os.makedirs(TABBAR_DIR, exist_ok=True)
    for name in ICONS:
        render_tab_icon(name, NEUTRAL, os.path.join(TABBAR_DIR, f"{name}.png"))
        render_tab_icon(name, BRAND, os.path.join(TABBAR_DIR, f"{name}-active.png"))
    render_app_icon()

    for root, _, files in os.walk(os.path.join(ROOT, "miniprogram", "assets")):
        for f in sorted(files):
            p = os.path.join(root, f)
            with Image.open(p) as im:
                print(f"{os.path.relpath(p, ROOT)}\t{im.size[0]}×{im.size[1]}\t"
                      f"{os.path.getsize(p) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
