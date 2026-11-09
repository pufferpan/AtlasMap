"""生成 AtlasMap 的宣传网页（首屏整墙 + reveal 滚动）。

用法：
    python tools/make_site.py
产出：
    site/index.html + site/pages/*.jpg
    work/AtlasMap-宣传页.zip（可直接发出去，双击 index.html 就能看）
"""
from __future__ import annotations

import os
import re
import shutil
import zipfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
SITE = os.path.join(ROOT, "site")
PAGES = os.path.join(SITE, "pages")
REF = (os.environ.get("ATLASMAP_PROMO_TEMPLATE")
       or os.path.join(SITE, "promo-template.html"))

TILES = [
    ("pg_main.jpg", "地图库",
     "37 张 pak 地图 + 预设里的Iceland，中文名和代号一起显示，搜中文或代号都行。"),
    ("pg_export.jpg", "导出小窗",
     "点开始导出，主窗口就地缩成右下角小窗：进度、当前动作、跑了多久都在上面。"),
    ("pg_log.jpg", "实时日志",
     "右下角小按钮下拉看导出器原始输出：levels / instances / split 分块一条不落。"),
    ("pg_runs.jpg", "缺图直接拦下",
     "图在 pak 里不存在时，阶段勾选全部禁用并给出橙色提示，不会让你白等一次空导出。"),
]

SHOWS = [
    ("pg_main.jpg", "选图 → 勾资源根 → 导出，全部在同一个窗口里"),
    ("pg_export.jpg", "导出结束自动变回主窗口，按钮换成「打开导出目录 / 关闭」"),
]


def _crop_card(src: str, dst: str, box_ratio, w=340, h=220) -> None:
    im = Image.open(src).convert("RGB")
    bw, bh = im.size
    x0, y0, x1, y1 = box_ratio
    im = im.crop((int(bw * x0), int(bh * y0), int(bw * x1), int(bh * y1)))
    scale = max(w / im.width, h / im.height)
    im = im.resize((max(w, int(im.width * scale)), max(h, int(im.height * scale))), Image.LANCZOS)
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    im = im.crop((left, top, left + w, top + h))
    im.save(dst, "JPEG", quality=82, optimize=True, progressive=True)


def _fit(src: str, dst: str, max_w: int = 1400, quality: int = 84) -> None:
    im = Image.open(src).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    im.save(dst, "JPEG", quality=quality, optimize=True, progressive=True)


def main() -> int:
    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    os.makedirs(PAGES, exist_ok=True)

    cards = []
    plans = [
        ("_s5.png", (0.02, 0.06, 0.62, 0.52)),
        ("_s5.png", (0.30, 0.20, 0.98, 0.70)),
        ("_s5.png", (0.05, 0.45, 0.60, 0.95)),
        ("_ew_small.png", (0.0, 0.0, 1.0, 1.0)),
        ("_ew_log.png", (0.0, 0.25, 1.0, 1.0)),
        ("_splash.png", (0.0, 0.0, 1.0, 1.0)),
        ("_s4.png", (0.10, 0.10, 0.72, 0.62)),
        ("_s4.png", (0.36, 0.30, 1.0, 0.86)),
        ("_ew_small.png", (0.0, 0.35, 1.0, 1.0)),
        ("_s5.png", (0.40, 0.08, 1.0, 0.55)),
        ("_wiz1.png", (0.04, 0.18, 0.55, 0.82)),
        ("_wiz2.png", (0.04, 0.18, 0.55, 0.82)),
    ]
    made = 0
    for i, (name, box) in enumerate(plans):
        src = os.path.join(WORK, name)
        if not os.path.exists(src):
            continue
        _crop_card(src, os.path.join(PAGES, f"card_{i:02d}.jpg"), box)
        cards.append(f'<figure class="card"><img src="pages/card_{i:02d}.jpg" alt=""></figure>')
        made += 1
    if not cards:
        print("[site] work 里没有可用截图")
        return 1

    for name, dst in (("_s5.png", "pg_main.jpg"), ("_ew_small.png", "pg_export.jpg"),
                      ("_ew_log.png", "pg_log.jpg"), ("_splash.png", "pg_splash.jpg"),
                      ("_s2.png", "pg_runs.jpg")):
        src = os.path.join(WORK, name)
        if os.path.exists(src):
            _fit(src, os.path.join(PAGES, dst))

    version = _version()
    html = _build_html(cards, version)
    out = os.path.join(SITE, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    zip_path = os.path.join(WORK, "AtlasMap-宣传页-%s.zip" % _stamp())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(out, "index.html")
        for name in sorted(os.listdir(PAGES)):
            zf.write(os.path.join(PAGES, name), os.path.join("pages", name))
        zf.writestr("使用说明.txt", _readme(version))
    print(f"[site] {out}（{made} 张首屏卡）")
    print(f"[site] {zip_path} ({os.path.getsize(zip_path) / 1024 / 1024:.2f} MB)")
    return 0


def _build_html(cards, version: str) -> str:
    if not os.path.isfile(REF):
        raise SystemExit(
            f"找不到页面模板：{REF}\n"
            "请用环境变量 ATLASMAP_PROMO_TEMPLATE 指定模板 index.html。")
    ref = open(REF, encoding="utf-8").read()
    html = re.sub(r"<title>.*?</title>", "<title>AtlasMap · 地图导出器</title>",
                  ref, count=1, flags=re.S)
    html = re.sub(r"<h1>.*?</h1>", "<h1>AtlasMap</h1>", html, count=1, flags=re.S)
    html = re.sub(r"(<h1>AtlasMap</h1>(?:\s*<[^>]+>)*\s*)<p>[^<]*</p>",
                  lambda m: m.group(1) + f"<p>地图导出器 ｜ {version}</p>",
                  html, count=1)

    stage_start = html.index('<div class="stage">')
    stage_end = html.index('<div class="hero-side">')
    rows = []
    for r in range(5):
        direction = "fromLeft" if r % 2 == 0 else "fromRight"
        crawl = "crawlLeft" if r % 2 == 0 else "crawlRight"
        chunk = cards[r::5] or cards
        body = "".join(chunk)
        rows.append(f'<div class="track {direction}"><div class="run {crawl}">'
                    f'{body}{body}</div></div>')
    html = html[:stage_start] + '<div class="stage">' + "".join(rows) + "</div>\n  " + html[stage_end:]

    main_start = html.index("<main>")
    main_end = html.index("</main>") + len("</main>")
    html = html[:main_start] + _main_html() + html[main_end:]

    html = re.sub(r"<footer>.*?</footer>",
                  "<footer>AtlasMap · 地图导出器 ｜ 内置固定工具链（2026-10-31 修正版）"
                  " ｜ 仅供学习研究</footer>", html, flags=re.S)
    return html


def _main_html() -> str:
    stats = [("38", "张地图（含预设）"), ("2.5 GB", "单图最大导出"),
             ("4 步", "选图 → 勾根 → 导出 → 进引擎"), ("0", "需要另装解析器")]
    stat_html = "".join(
        f'<div class="stat reveal" style="--i:{i}"><b>{v}</b><span>{k}</span></div>'
        for i, (v, k) in enumerate(stats))

    tiles = "".join(
        f'''<article class="tile reveal" style="--i:{i}">
            <div class="shot"><img src="pages/{img}" alt=""></div>
            <h3>{title}</h3>
            <p>{desc}</p>
          </article>''' for i, (img, title, desc) in enumerate(TILES))

    shows = "".join(
        f'''<figure class="show reveal" style="--i:{i}">
            <img src="pages/{img}" alt="">
            <figcaption>{cap}</figcaption>
          </figure>''' for i, (img, cap) in enumerate(SHOWS))

    return f'''<main>
    <section>
      <div class="wrap">
        <div class="kicker reveal">Map Exporter</div>
        <h2 class="lead reveal" style="--i:1">地图名对得上<br><em>点两下就能导出</em></h2>
        <p class="sub reveal" style="--i:2">
          直接读游戏 pak，不修改任何游戏文件。地图用游戏里的中文名显示，
          资源根按图列出，导出时主窗口就地变成小窗盯着进度。
        </p>
        <div class="stats">{stat_html}
        </div>
      </div>
    </section>

    <section>
      <div class="wrap">
        <div class="kicker reveal">Features</div>
        <h2 class="lead reveal" style="--i:1">你想要的信息，<em>都在一屏里</em></h2>
        <div class="tiles">{tiles}
        </div>
      </div>
    </section>

    <section>
      <div class="wrap">
        <div class="kicker reveal">Workflow</div>
        <h2 class="lead reveal" style="--i:1">选图 → 勾根 → 导出<em> → 进引擎</em></h2>
        <div class="shows">{shows}
        </div>
      </div>
    </section>
  </main>'''


def _stamp() -> str:
    import time
    return time.strftime("%H%M")


def _readme(version: str) -> str:
    return (f"AtlasMap 宣传页（{version}）\n\n"
            "双击 index.html 就能看，图片都在 pages/ 里，整包可以直接传网盘。\n"
            "首屏那面墙是滚动动画；想静态截图可以打开 index.html#still。\n")


def _version() -> str:
    path = os.path.join(ROOT, "app", "version.py")
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("BUILD"):
                    return "1.0+" + line.split('"')[1]
    except Exception:                                       # noqa: BLE001
        pass
    return "1.0"


if __name__ == "__main__":
    raise SystemExit(main())
