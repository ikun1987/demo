# -*- coding: utf-8 -*-
"""图标资源验证脚本（只读，不修改任何文件）。

检查项：
  1. app.png 存在，尺寸 512x512，模式 RGBA
  2. app.png 四角像素 alpha == 0（圆角外完全透明）
  3. app.ico 存在，PIL info 中列出全部尺寸
  4. 直接解析 ICO 文件头，确认 256x256 真的被写进去了
  5. 逐个尺寸都能用 PIL 正确打开并解码

用法：python verify_icon.py
"""

from __future__ import annotations

import os
import struct
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PNG = os.path.join(HERE, "assets", "app.png")
APP_ICO = os.path.join(HERE, "assets", "app.ico")
EXPECTED = [16, 24, 32, 48, 64, 128, 256]

ok = True


def check(cond, msg):
    global ok
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        ok = False
    return cond


def main():
    print("=" * 68)
    print("「玉用去水印」图标资源验证")
    print("=" * 68)

    # ---------------------------------------------------------- app.png
    print("\n[1] app.png")
    check(os.path.isfile(APP_PNG), "存在: %s" % APP_PNG)
    print("       字节大小: %d bytes" % os.path.getsize(APP_PNG))
    with Image.open(APP_PNG) as im:
        im.load()
        print("       尺寸/模式: %s x %s  %s" % (im.size[0], im.size[1], im.mode))
        check(im.size == (512, 512), "尺寸为 512x512")
        check(im.mode == "RGBA", "模式为 RGBA")
        rgba = im.convert("RGBA")
        w, h = rgba.size
        corners = {
            "左上": rgba.getpixel((0, 0)),
            "右上": rgba.getpixel((w - 1, 0)),
            "左下": rgba.getpixel((0, h - 1)),
            "右下": rgba.getpixel((w - 1, h - 1)),
        }
        for name, px in corners.items():
            print("       %s角像素: %s" % (name, px))
        check(all(px[3] == 0 for px in corners.values()),
              "四角 alpha 全部 == 0（圆角外完全透明）")
        # 中心必须是不透明的（确认图像内容没被裁掉）
        cx = rgba.getpixel((w // 2, h // 3))
        print("       中心区域像素(不透明): %s" % (cx,))
        check(cx[3] == 255, "画面中心 alpha == 255（图像有效）")

    # ---------------------------------------------------------- app.ico
    print("\n[2] app.ico (PIL 读取)")
    check(os.path.isfile(APP_ICO), "存在: %s" % APP_ICO)
    print("       字节大小: %d bytes" % os.path.getsize(APP_ICO))
    with Image.open(APP_ICO) as im:
        im.load()
        print("       im.info = %s" % (im.info,))
        sizes = sorted(im.info.get("sizes", set()))
        print("       包含尺寸: %s" % (sizes,))
        got = [s[0] for s in sizes]
        check(got == EXPECTED, "尺寸列表等于 %s" % EXPECTED)

        # 每个尺寸都能独立解码
        decoded = []
        for s in EXPECTED:
            try:
                im.size = (s, s)
                frame = im.copy()
                frame.load()
                decoded.append((s, frame.size, frame.mode))
            except Exception as e:  # pragma: no cover
                check(False, "%dx%d 解码失败: %s" % (s, s, e))
        print("       逐尺寸解码: %s" % (decoded,))
        check(len(decoded) == len(EXPECTED), "全部 7 个尺寸均可独立解码")

    # -------------------------------------------- 直接解析 ICO 文件头
    print("\n[3] app.ico (原始文件头解析，权威确认)")
    with open(APP_ICO, "rb") as f:
        raw = f.read()
    reserved, itype, count = struct.unpack_from("<HHH", raw, 0)
    print("       reserved=%d type=%d count=%d" % (reserved, itype, count))
    check(reserved == 0 and itype == 1, "ICO 文件头合法 (0,1)")
    check(count == len(EXPECTED), "目录项数量 == %d" % len(EXPECTED))
    found = []
    for i in range(count):
        off = 6 + i * 16
        bw, bh, ncolors, res, planes, bpp, nbytes, offset = struct.unpack_from(
            "<BBBBHHII", raw, off)
        # ICO 中 0 表示 256
        w = bw or 256
        h = bh or 256
        found.append(w)
        print("       [%d] %3dx%-3d  色彩数=%-3d 位深=%-2d  数据=%7d bytes  @0x%06X"
              % (i, w, h, ncolors, bpp, nbytes, offset))
        check(offset + nbytes <= len(raw), "%dx%d 数据未越界" % (w, h))
    check(256 in found, "256x256 确实写入 ICO（不是被静默丢弃）")
    check(sorted(found) == EXPECTED, "文件头中的尺寸集合 == %s" % EXPECTED)

    # 256 图标是否为 PNG 压缩（Vista+ 常见做法），并校验可解码
    idx = found.index(256)
    off = 6 + idx * 16
    _bw, _bh, _nc, _r, _p, _bpp, nbytes, offset = struct.unpack_from("<BBBBHHII", raw, off)
    blob = raw[offset:offset + nbytes]
    print("       256x256 数据块前 8 字节: %s" % (blob[:8].hex(),))
    check(len(blob) == nbytes, "256x256 数据块长度与目录声明一致")

    print("\n" + "=" * 68)
    print("结果: %s" % ("全部通过 [PASS]" if ok else "存在失败项 [FAIL]"))
    print("=" * 68)
    return 0 if ok else 1


if __name__ == "__main__":
    # Windows 控制台默认 GBK，这里强制 UTF-8 输出，避免中文/符号报错
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
