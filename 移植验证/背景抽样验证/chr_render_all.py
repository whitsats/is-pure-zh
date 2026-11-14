"""把指定档位的条目全部渲染成对照表分页（每页 48 条：8 列 × 6 行）。

用法：
    python chr_render_all.py            # 默认 < 0.80 的全部条目
    python chr_render_all.py 0.80 1.01  # 指定 [lo, hi)
输出：chr_body/all/pageNN.png + chr_body/all/index.csv（页号, 格位, 条目号, IoU）
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

OUT = B.OUT / "all"
COLS, ROWS = 8, 6
CELL_W, CELL_H = 236, 236
HEAD = 16

# solo 模式：只画重建，格子更大，判读“是不是一个人”更准
SOLO_COLS, SOLO_ROWS = 10, 8
SOLO_CELL = 180
SOLO_HEAD = 14


def cell(canvas, t):
    box = Image.new("RGBA", (CELL_W, CELL_H), (255, 255, 255, 255))
    ys, xs = np.where(canvas[:, :, 3] > 0)
    if ys.size:
        crop = canvas[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        im = Image.fromarray(crop, "RGBA")
        im.thumbnail((CELL_W // 2 - 6, CELL_H - 6), Image.Resampling.LANCZOS)
        bg = Image.new("RGBA", (CELL_W // 2 - 6, CELL_H - 6), (255, 255, 255, 255))
        bg.alpha_composite(im, ((bg.width - im.width) // 2, (bg.height - im.height) // 2))
        box.alpha_composite(bg, (0, 0))
    ref = Image.fromarray(t, "RGBA")
    ref.thumbnail((CELL_W // 2 - 6, CELL_H - 6), Image.Resampling.NEAREST)
    bg2 = Image.new("RGBA", (CELL_W // 2 - 6, CELL_H - 6), (255, 255, 255, 255))
    bg2.alpha_composite(ref, ((bg2.width - ref.width) // 2, (bg2.height - ref.height) // 2))
    box.alpha_composite(bg2, (CELL_W // 2, 0))
    return box


def cmd_solo(lo=0.0, hi=0.80):
    rows = [r for r in csv.DictReader(open(OUT.parent / "chr_body.csv", encoding="utf-8"))]
    rows = [r for r in rows if lo <= float(r["iou"]) < hi]
    rows.sort(key=lambda r: float(r["iou"]))
    dest = B.OUT / "solo"
    dest.mkdir(exist_ok=True)
    per = SOLO_COLS * SOLO_ROWS
    meta = []
    for p in range((len(rows) + per - 1) // per):
        chunk = rows[p * per:(p + 1) * per]
        sheet = Image.new("RGBA", (SOLO_COLS * SOLO_CELL + 4 * (SOLO_COLS + 1),
                                   SOLO_ROWS * (SOLO_CELL + SOLO_HEAD) + 4 * (SOLO_ROWS + 1)),
                          (255, 255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            c, w = i % SOLO_COLS, i // SOLO_COLS
            x0 = 4 + c * (SOLO_CELL + 4)
            y0 = 4 + w * (SOLO_CELL + SOLO_HEAD + 4)
            d.text((x0, y0 + 1), f"{i}:{r['index']}", fill=(20, 20, 20, 255))
            canvas, _ = B.build(B.entry(int(r["index"])))
            ys, xs = np.where(canvas[:, :, 3] > 0)
            if not ys.size:
                continue
            crop = canvas[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            im = Image.fromarray(crop, "RGBA")
            im.thumbnail((SOLO_CELL - 8, SOLO_CELL - 8), Image.Resampling.LANCZOS)
            bg = Image.new("RGBA", (SOLO_CELL, SOLO_CELL), (255, 255, 255, 255))
            bg.alpha_composite(im, ((SOLO_CELL - im.width) // 2, (SOLO_CELL - im.height) // 2))
            sheet.alpha_composite(bg, (x0, y0 + SOLO_HEAD))
            meta.append([p, i, int(r["index"]), float(r["iou"])])
        sheet.save(dest / f"s{p}.png")
        print(f"saved solo/s{p}.png  {len(chunk)} 条  {chunk[0]['index']}..{chunk[-1]['index']}")
    with open(dest / "index.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["page", "slot", "index", "iou"])
        wr.writerows(meta)
    print(f"共 {len(rows)} 条，{(len(rows) + per - 1) // per} 页")


def main():
    if "--solo" in sys.argv:
        rest = [a for a in sys.argv[1:] if a != "--solo"]
        cmd_solo(float(rest[0]) if rest else 0.0, float(rest[1]) if len(rest) > 1 else 0.80)
        return
    lo = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0
    hi = float(sys.argv[2]) if len(sys.argv) > 2 else 0.80
    rows = [r for r in csv.DictReader(open(OUT.parent / "chr_body.csv", encoding="utf-8"))]
    rows = [r for r in rows if lo <= float(r["iou"]) < hi]
    rows.sort(key=lambda r: float(r["iou"]))
    OUT.mkdir(exist_ok=True)
    per = COLS * ROWS
    idx_rows = []
    for p in range((len(rows) + per - 1) // per):
        chunk = rows[p * per:(p + 1) * per]
        sheet = Image.new("RGBA", (COLS * CELL_W + 8 * (COLS + 1),
                                   ROWS * (CELL_H + HEAD) + 8 * (ROWS + 1)), (255, 255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for i, r in enumerate(chunk):
            c, w = i % COLS, i // COLS
            x0 = 8 + c * (CELL_W + 8)
            y0 = 8 + w * (CELL_H + HEAD + 8)
            d.text((x0, y0 + 2), f"{r['index']}  {float(r['iou']):.3f}", fill=(0, 0, 0, 255))
            canvas, used = B.build(B.entry(int(r["index"])))
            t, _, _ = B.thumb(int(r["index"]) + 1)
            sheet.alpha_composite(cell(canvas, t), (x0, y0 + HEAD))
            idx_rows.append([p, i, int(r["index"]), float(r["iou"])])
        path = OUT / f"page{p:02d}.png"
        sheet.save(path)
        print(f"saved {path.name}  {len(chunk)} 条  {chunk[0]['index']}..{chunk[-1]['index']}")
    with open(OUT / "index.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["page", "slot", "index", "iou"])
        wr.writerows(idx_rows)
    print(f"共 {len(rows)} 条，{p + 1 if rows else 0} 页")


if __name__ == "__main__":
    main()
