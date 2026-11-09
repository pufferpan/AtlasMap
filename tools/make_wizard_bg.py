"""生成首次启动向导的背景素材（左侧留白放向导面板，右侧 3 行 45° 斜置软件截图）。

产物（都在 assets/）：
    wizard_base.png   纯底：渐变 + 柔光 + 左侧压暗 + 边缘淡出（没有卡片）
    wizard_row1..3.png  三条横平竖直的截图带子（卡片本身不转，画的时候整体转 −45°）
    wizard_rows.json  画布尺寸 + 每条带子的中心坐标（Qt 端按这个摆）
    wizard_bg.png     把上面几层合成好的整图（静态兜底 / 预览用）

卡片带子是横的（不是旋转后的透明大图），PNG 小得多；Qt 里用 QPainter 旋转绘制，
所以「三行从屏幕外面飞进来」是逐行做的动画，不需要一份旋转好的位图。

用法：
    python tools/make_wizard_bg.py                 # 2560x1600
    python tools/make_wizard_bg.py --size 1920x1200
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
PAGES = ASSETS
OUT = os.path.join(ASSETS, "wizard_bg.png")

TOP = (11, 30, 51)
BOTTOM = (18, 54, 92)
ACCENT = (32, 96, 160)

ROWS = 3
PER_ROW = 6
CARD_W = 400
GAP = 8
ANGLE = 45.0          # 整行倾斜角度（按需求 45°）
CARD_RADIUS = 26
BORDER = 7

PICK = [
    "tutorial_maps.png", "tutorial_ue.png",
    "tutorial_performance.png", "tutorial_progress.png",
]


def gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        # 中间偏亮一点，别死板
        k = 0.5 + 0.5 * math.sin(math.pi * min(1.0, t * 1.05))
        c = tuple(int(top[i] + (bottom[i] - top[i]) * (0.55 * t + 0.45 * k))
                  for i in range(3))
        d.line([(0, y), (w, y)], fill=c)
    return img


def rounded(im, radius):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, im.size[0] - 1, im.size[1] - 1), radius, fill=255)
    out = im.convert("RGBA")
    out.putalpha(mask)
    return out


def card(path, width):
    img = Image.open(path).convert("RGB")
    target = int(round(width * 9 / 16))
    scale = min(width / img.size[0], target / img.size[1])
    img = img.resize((max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale))), Image.LANCZOS)
    plate = Image.new("RGB", (width, target), (10, 22, 34))
    plate.paste(img, ((width - img.size[0]) // 2, (target - img.size[1]) // 2))
    img, h = plate, target
    inner = rounded(img, CARD_RADIUS)
    canvas = Image.new("RGBA", (width + BORDER * 2, h + BORDER * 2), (0, 0, 0, 0))
    edge = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        (0, 0, canvas.size[0] - 1, canvas.size[1] - 1), CARD_RADIUS + BORDER,
        fill=(255, 255, 255, 235))
    canvas.alpha_composite(edge)
    canvas.alpha_composite(inner, (BORDER, BORDER))
    # 整体压暗 + 偏蓝，让右侧像「背景」而不是「主体」
    dim = Image.new("RGBA", canvas.size, (12, 34, 58, 96))
    canvas.alpha_composite(dim)
    return canvas


def shadow(size, blur, alpha):
    s = Image.new("RGBA", (size[0] + blur * 2, size[1] + blur * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(s)
    d.rounded_rectangle((blur, blur, blur + size[0], blur + size[1]),
                        CARD_RADIUS + BORDER, fill=(2, 10, 20, alpha))
    return s.filter(ImageFilter.GaussianBlur(blur * 0.55))


def build_base(size):
    """纯底：渐变 + 右侧柔光 + 左侧压暗 + 左上光斑 + 上下淡边。"""
    w, h = size
    base = gradient(size, TOP, BOTTOM).convert("RGBA")

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((w * 0.45, -h * 0.25, w * 1.25, h * 1.15), fill=(56, 132, 210, 60))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(160)))

    # 左半部分压暗，给向导面板留出可读的底
    veil = Image.new("RGBA", size, (0, 0, 0, 0))
    vd = ImageDraw.Draw(veil)
    for x in range(int(w * 0.62)):
        a = int(232 * (1 - x / (w * 0.62)) ** 1.25)
        vd.line([(x, 0), (x, h)], fill=(9, 24, 42, a))
    base.alpha_composite(veil)

    flare = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(flare).ellipse((-w * 0.25, -h * 0.35, w * 0.45, h * 0.5),
                                  fill=(32, 96, 160, 90))
    base.alpha_composite(flare.filter(ImageFilter.GaussianBlur(180)))

    edge = Image.new("RGBA", size, (0, 0, 0, 0))
    ed = ImageDraw.Draw(edge)
    fade = int(h * 0.06)
    for y in range(fade):
        a = int(150 * (1 - y / fade))
        ed.line([(0, y), (w, y)], fill=TOP + (a,))
        ed.line([(0, h - 1 - y), (w, h - 1 - y)], fill=TOP + (a,))
    base.alpha_composite(edge)
    return base


def build_row(files, row_index, start_index):
    """一条横平竖直的截图带子（卡片不旋转，整条带子后面在 Qt 里转 −45°）。"""
    art_w = CARD_W + BORDER * 2
    art_h = int(round((CARD_W * 9 / 16) + BORDER * 2))
    pad = 90
    band_w = PER_ROW * art_w + (PER_ROW - 1) * GAP + pad * 2
    band_h = art_h + pad * 2
    band = Image.new("RGBA", (band_w, band_h), (0, 0, 0, 0))
    for c in range(PER_ROW):
        name = files[(start_index + c) % len(files)]
        art = card(os.path.join(PAGES, name), CARD_W)
        x = pad + c * (art_w + GAP)
        y = pad
        sh = shadow(art.size, 30, 120)
        band.alpha_composite(sh, (x - 30, y - 30))
        band.alpha_composite(art, (x, y))
    return band, art_h


def build(size):
    """三行卡片先在带子里横平竖直排好，整条带子转 −45°；再把三条带子各切出来单独存，
    并算出「这条带子的中心转到画布上的哪里」，Qt 端按同样的角度和中心画回去，
    和静态整图完全对得上（这就是 3 行能各自飞进来的前提）。"""
    w, h = size
    base = build_base(size)

    random.seed(7)
    files = [f for f in PICK if os.path.exists(os.path.join(PAGES, f))]
    if not files:
        raise SystemExit(f"找不到截图：{PAGES}")

    art_h = int(round((CARD_W * 9 / 16) + BORDER * 2))
    pitch = art_h + 96                    # 行距（带子坐标系）：留出明显缝隙，三行才分得开
    pad = 34                              # 每行上下多留一点，别把投影切掉

    art_w = CARD_W + BORDER * 2
    band_pad = 90
    band_w = PER_ROW * art_w + (PER_ROW - 1) * GAP + band_pad * 2
    band_h = ROWS * pitch + band_pad * 2
    band = Image.new("RGBA", (band_w, band_h), (0, 0, 0, 0))

    idx = 0
    for r in range(ROWS):
        y = band_pad + r * pitch
        for c in range(PER_ROW):
            name = files[idx % len(files)]
            idx += 1
            art = card(os.path.join(PAGES, name), CARD_W)
            x = band_pad + c * (art_w + GAP)
            sh = shadow(art.size, 30, 120)
            band.alpha_composite(sh, (x - 30, y - 30))
            band.alpha_composite(art, (x, y))

    rotated = band.rotate(-ANGLE, resample=Image.BICUBIC, expand=True)

    # 整条带子的中心落在右半球
    cx0, cy0 = w * 0.78, h * 0.50
    top_left = (cx0 - rotated.size[0] / 2, cy0 - rotated.size[1] / 2)

    flat = base.copy()
    flat.alpha_composite(rotated, (int(top_left[0]), int(top_left[1])))

    rad = math.radians(-ANGLE)
    cos_a, sin_a = math.cos(rad), math.sin(rad)

    def _rot_about_center(px, py):
        """带子坐标系 → 旋转后图坐标系（PIL rotate 的约定：绕中心转，expand 后挪到新画布中心）。"""
        bx, by = band_w / 2, band_h / 2
        dx, dy = px - bx, py - by
        rx = dx * cos_a + dy * sin_a
        ry = -dx * sin_a + dy * cos_a
        return (rotated.size[0] / 2 + rx, rotated.size[1] / 2 + ry)

    # 每条带子：先在 band 坐标系里裁出来，再单独转 −45°，把旋转「烤」进 PNG。
    # 这样 Qt 端只需要按左上角整块贴图就行 —— 位置和 PIL 整图逐像素一致，
    # 也不用每帧再 rotate 一次（那才是动画卡的元凶）。
    rows = []
    for r in range(ROWS):
        y0 = band_pad + r * pitch
        strip = band.crop((0, max(0, y0 - pad), band_w,
                           min(band_h, y0 + art_h + pad)))
        sx, sy = _rot_about_center(band_w / 2, y0 + art_h / 2)
        baked = strip.rotate(-ANGLE, resample=Image.BICUBIC, expand=True)
        left = top_left[0] + sx - baked.size[0] / 2
        top = top_left[1] + sy - baked.size[1] / 2
        rows.append({
            "file": f"wizard_row{r + 1}.png",
            "x": round(left, 1),
            "y": round(top, 1),
            "w": baked.size[0],
            "h": baked.size[1],
            "img": baked,
        })

    return {
        "canvas": [w, h],
        "base": "wizard_base.png",
        "rows": [{k: v for k, v in row.items() if k != "img"} for row in rows],
        "flat": flat,
        "base_img": base,
        "row_images": [row["img"] for row in rows],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", default="2560x1600")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    w, h = (int(x) for x in args.size.lower().split("x"))
    data = build((w, h))
    os.makedirs(ASSETS, exist_ok=True)

    data["flat"].convert("RGB").save(args.out, "PNG", optimize=True)
    data["base_img"].convert("RGB").save(os.path.join(ASSETS, "wizard_base.png"),
                                         "PNG", optimize=True)
    for i, img in enumerate(data["row_images"], start=1):
        img.save(os.path.join(ASSETS, f"wizard_row{i}.png"), "PNG", optimize=True)
    for row in data["rows"]:
        row.pop("img", None)
    meta = {"canvas": data["canvas"], "base": data["base"], "rows": data["rows"]}
    with open(os.path.join(ASSETS, "wizard_rows.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    total = sum(os.path.getsize(os.path.join(ASSETS, n))
                for n in ["wizard_base.png", "wizard_row1.png",
                          "wizard_row2.png", "wizard_row3.png"])
    print(f"[wizard-bg] {args.out} ({w}x{h}, "
          f"{os.path.getsize(args.out) / 1048576:.1f} MB)")
    print(f"[wizard-bg] 分层素材 {total / 1048576:.1f} MB"
          f"（base + 3 条带子），清单 assets/wizard_rows.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
