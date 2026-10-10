# -*- coding: utf-8 -*-
"""
「玉用去水印」桌面软件图标生成脚本
=====================================
可重复执行：直接运行本脚本即可重新生成两个图标资源。

产物：
  app/assets/app.png   512x512 RGBA，圆角方形裁切头像 + 底部半透明深色渐变
  app/assets/app.ico   含 16/24/32/48/64/128/256 七种尺寸的 Windows 图标

实现要点：
  * 4x 超采样：先在 2048x2048 上完成圆角遮罩与渐变，再 LANCZOS 缩到 512，
    保证圆角边缘抗锯齿、不糊、不拉伸。
  * 裁剪框默认由原图自动检测（非浅色背景区域的 bbox）推导，构图让脸部居中偏上；
    也可用 --crop 手动覆盖。
  * 只读取 sample_doubao.png，绝不修改它。

用法：
  python make_icon.py
  python make_icon.py --crop 300,110,940,750 --radius 112
"""

from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------- 配置

HERE = os.path.dirname(os.path.abspath(__file__))
YUWATER = os.path.dirname(HERE)  # ...\yuwater
SRC_PNG = os.path.join(YUWATER, "sample_doubao.png")
ASSETS = os.path.join(HERE, "assets")
OUT_PNG = os.path.join(ASSETS, "app.png")
OUT_ICO = os.path.join(ASSETS, "app.ico")

OUT_SIZE = 512           # 最终图标边长
SS = 4                   # 超采样倍率
CORNER_RADIUS = 112      # 输出坐标系下的圆角半径 (512 基准)
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

GRAD_TOP = 330           # 渐变起始 y（输出坐标系, 512 基准）
GRAD_ALPHA_MAX = 140     # 渐变底部黑色不透明度
BG_THRESHOLD = 238       # 判定“浅色背景”的灰度阈值
BG_TOLERANCE = 12        # 相对背景基准灰度的容差

FOCUS_Y_MAX = 0.78       # 只在画面上部该比例内做人脸检测
FACE_BAND = 0.05         # 找"肤色最密集横带"的窗口高度（占画面比例）
CHIN_GAP = 6             # 向下追踪下巴时允许的最大连续空行
FACE_W_RATIO = 1.75      # 裁剪边长 / 面部宽度
FACE_ANCHOR = 0.42       # 面部垂直中心在裁剪框中的相对高度（<0.5 即脸部偏上）


# ---------------------------------------------------------------- 工具函数


def content_bbox(img: Image.Image, tolerance: int = BG_TOLERANCE):
    """返回原图中非浅色背景内容(人物)的包围盒 (l, t, r, b)。

    做法：取四周边框像素的中位灰度作为背景基准 bg，
    亮度低于 bg - tolerance 视为内容，再用投影找首尾有效行列。
    为避免噪点干扰，要求某行/列至少有 0.3% 的像素属于内容。
    """
    g = img.convert("L")
    w, h = g.size
    gp = g.load()

    border = []
    step = max(1, w // 64)
    for x in range(0, w, step):
        border.append(gp[x, 0])
        border.append(gp[x, h - 1])
    for y in range(0, h, step):
        border.append(gp[0, y])
        border.append(gp[w - 1, y])
    border.sort()
    bg = border[len(border) // 2]  # 中位数，抗噪
    threshold = bg - tolerance

    mask = g.point(lambda v: 255 if v < threshold else 0)
    px = mask.load()

    min_count_x = max(1, int(h * 0.003))
    min_count_y = max(1, int(w * 0.003))

    col_hits = [0] * w
    row_hits = [0] * h
    for y in range(h):
        for x in range(w):
            if px[x, y]:
                col_hits[x] += 1
                row_hits[y] += 1

    xs = [x for x in range(w) if col_hits[x] >= min_count_x]
    ys = [y for y in range(h) if row_hits[y] >= min_count_y]
    if not xs or not ys:
        return (0, 0, w, h)
    return (xs[0], ys[0], xs[-1] + 1, ys[-1] + 1)


def face_focus(img: Image.Image):
    """定位人物面部：返回 (cx, cy, face_w, chin_y) 或 None。

    思路：插画里脸部是画面中最大的一片暖色肤色区域。
      1) 用 R>G>B 的暖色条件粗筛肤色；
      2) 只在画面上部 FOCUS_Y_MAX 以内统计（排除胸口/手臂的露肤）；
      3) 用 FACE_BAND 比例高度的滑动窗口找肤色最密集的横带 -> 面部垂直中心 cy；
      4) 面部宽度 face_w 取上部区域内肤色像素的水平跨度，比单条横带更稳；
      5) 下巴 chin_y：从 cy 向下追踪肤色行，连续空行超过 CHIN_GAP 即认为脸已结束
         （这样脖子/胸口不会把下巴一路拖到画布底部）。
    """
    import numpy as np  # 局部导入：无 numpy 时会被上层 try 捕获，走 fallback

    a = np.asarray(img.convert("RGB")).astype(np.int16)
    R, G, B = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    skin = (R > G + 12) & (G > B + 4) & (R > 150) & (R < 252)

    h, w = skin.shape
    cut = int(h * FOCUS_Y_MAX)
    upper = skin[:cut, :]
    if int(upper.sum()) < w * h * 0.001:
        return None

    rows = upper.sum(1)
    band = max(1, int(h * FACE_BAND))
    dens = np.convolve(rows, np.ones(band, dtype=np.int64), mode="same")
    cy = int(np.argmax(dens))

    xs = np.nonzero(upper.sum(0))[0]
    if xs.size == 0:
        return None
    x0, x1 = int(xs[0]), int(xs[-1])

    chin_y = cy
    gap = 0
    for y in range(cy, h):
        if skin[y].any():
            chin_y = y
            gap = 0
        else:
            gap += 1
            if gap > CHIN_GAP:
                break

    return ((x0 + x1) / 2.0, float(cy), float(x1 - x0 + 1), float(chin_y))


def hair_top(img: Image.Image, y_hint: float) -> float:
    """在面部上方找内容（头发）最上沿的 y，用于只校准裁剪框上边界。"""
    import numpy as np

    g = np.asarray(img.convert("L")).astype(np.int16)
    h, w = g.shape
    dark = (g < 245).sum(1)
    limit = max(1, int(w * 0.003))
    top = 0
    for y in range(0, max(1, int(y_hint))):
        if dark[y] > limit:
            top = y
            break
    return float(top)


def auto_crop_box(img: Image.Image, face_ratio=FACE_W_RATIO, anchor=FACE_ANCHOR):
    """推导正方形裁剪框：脸部水平居中、垂直偏上，头顶留白，肩部入画。

    边长只由"面部宽度"决定（内容 bbox 会被人物的长发和出画的身体拉满整幅画，
    不能用来定边长）；垂直位置用"面部中心锚点"确定：
        side = face_w * face_ratio
        cx   = 面部水平中心
        top  = 面部中心 y - side * anchor   (anchor<0.5 -> 脸部偏上)
    最后只做"上边界不切头发"校准，并把整框夹回画布内（边长保持，不变形）。
    """
    w, h = img.size
    focus = None
    try:
        focus = face_focus(img)
    except Exception:
        focus = None

    if focus:
        cx, cy, face_w, _chin_y = focus
        side = int(round(face_w * face_ratio))
    else:
        l, t, r, b = content_bbox(img)
        cx = (l + r) / 2.0
        cy = t + (b - t) * 0.35
        side = int(round((r - l) * 1.25))

    side = max(64, min(side, w, h))
    left = int(round(cx - side / 2.0))
    top = int(round(cy - side * anchor))

    # 上边界校准：别把头发切掉
    try:
        ht = hair_top(img, cy - side * 0.5)
    except Exception:
        ht = 0.0
    if ht > 0 and top > ht - side * 0.02:
        top = int(round(ht - side * 0.02))

    left = max(0, min(left, w - side))
    top = max(0, min(top, h - side))
    return (left, top, left + side, top + side)


def cover_resize(img: Image.Image, size: int) -> Image.Image:
    """等比缩放并居中裁剪到 size x size（不变形、不拉伸）。"""
    sw, sh = img.size
    scale = max(size / sw, size / sh)
    nw, nh = max(size, int(round(sw * scale))), max(size, int(round(sh * scale)))
    resized = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - size) // 2
    top = (nh - size) // 2
    return resized.crop((left, top, left + size, top + size))


def rounded_mask(size: int, radius: int, ss: int = SS) -> Image.Image:
    """在超采样尺寸下绘制圆角矩形遮罩（8x 再超采样得到抗锯齿边缘），再缩到 size。"""
    big = size * ss
    r = radius * ss
    s = 8  # 圆角遮罩自身的额外超采样，保证边缘平滑
    m = Image.new("L", (big * s, big * s), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, big * s - 1, big * s - 1), radius=r * s, fill=255)
    m = m.resize((big, big), Image.LANCZOS)
    return m


def bottom_gradient(size: int, top_y: int, alpha_max: int, ss: int = SS) -> Image.Image:
    """生成从 top_y 到 size 的黑色 alpha 渐变（0 -> alpha_max），尺寸为 size*ss。"""
    dim = size * ss  # 注意：勿用 big 作变量名，会遮蔽外层同名局部变量
    top_big = int(round(top_y * ss))
    grad = Image.new("L", (1, dim), 0)
    px = grad.load()
    span = max(1, dim - top_big)
    for y in range(dim):
        if y < top_big:
            v = 0
        else:
            # 幂曲线：底部更实，上部更柔和
            k = (y - top_big) / span
            v = int(round(alpha_max * (k ** 1.35)))
        px[0, y] = min(255, max(0, v))
    grad = grad.resize((dim, dim), Image.NEAREST)
    return grad


# ---------------------------------------------------------------- 主流程


def build_app_png(crop_box=None, radius=CORNER_RADIUS, out_size=OUT_SIZE) -> Image.Image:
    if not os.path.isfile(SRC_PNG):
        raise SystemExit("找不到源图: %s" % SRC_PNG)

    with Image.open(SRC_PNG) as im:
        src = im.convert("RGBA")

    box = crop_box or auto_crop_box(src)
    print("[1/4] 源图 %s, 裁剪框 %s" % (src.size, box))
    cropped = src.crop(box)

    big = out_size * SS
    print("[2/4] 4x 超采样缩放 -> %dx%d" % (big, big))
    base = cover_resize(cropped, big)  # RGBA, 构图居中

    print("[3/4] 叠加底部渐变 (y=%d -> %d, alpha 0 -> %d)" % (GRAD_TOP, out_size, GRAD_ALPHA_MAX))
    grad = bottom_gradient(out_size, GRAD_TOP, GRAD_ALPHA_MAX, SS)
    black = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    black.putalpha(grad)
    base = Image.alpha_composite(base, black)

    print("[4/4] 圆角遮罩 r=%d (4x 超采样) 并 LANCZOS 缩到 %dx%d" % (radius, out_size, out_size))
    mask_big = rounded_mask(out_size, radius, SS)     # 2048x2048 抗锯齿圆角遮罩
    rounded = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    rounded.paste(base, (0, 0), mask_big)             # 2048 尺度上完成圆角裁切
    rounded.putalpha(mask_big)
    out = rounded.resize((out_size, out_size), Image.LANCZOS)  # 再缩到 512 -> 边缘平滑
    # 缩放会让边缘产生很小的非零值，这里把明显透明处强制归零，保证四角严格 alpha==0
    alpha = out.getchannel("A").point(lambda v: 0 if v < 8 else v)
    out.putalpha(alpha)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成「玉用去水印」图标资源")
    ap.add_argument("--crop", default=None,
                    help="手动裁剪框 left,top,right,bottom（原图像素，正方形）")
    ap.add_argument("--radius", type=int, default=CORNER_RADIUS, help="圆角半径(512基准)")
    ap.add_argument("--size", type=int, default=OUT_SIZE, help="输出边长，默认 512")
    ap.add_argument("--face-ratio", type=float, default=FACE_W_RATIO,
                    help="裁剪边长 / 面部宽度，默认 %.3f" % FACE_W_RATIO)
    ap.add_argument("--anchor", type=float, default=FACE_ANCHOR,
                    help="面部中心在裁剪框中的相对高度，默认 %.3f" % FACE_ANCHOR)
    args = ap.parse_args(argv)

    crop = None
    if args.crop:
        parts = [int(v) for v in args.crop.replace(" ", "").split(",")]
        if len(parts) != 4:
            raise SystemExit("--crop 需要 4 个整数: l,t,r,b")
        crop = tuple(parts)

    if crop is None:
        crop = auto_crop_box(Image.open(SRC_PNG).convert("RGBA"),
                             args.face_ratio, args.anchor)

    os.makedirs(ASSETS, exist_ok=True)
    png = build_app_png(crop, args.radius, args.size)
    png.save(OUT_PNG, format="PNG", optimize=True)
    print("      写出 %s (%d bytes)" % (OUT_PNG, os.path.getsize(OUT_PNG)))

    png.save(OUT_ICO, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print("      写出 %s (%d bytes, sizes=%s)" % (OUT_ICO, os.path.getsize(OUT_ICO), ICO_SIZES))
    return 0


if __name__ == "__main__":
    # Windows 控制台默认 GBK，这里强制 UTF-8 输出，避免中文报错
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
