"""chr_unified.py 的抽样渲染：取全身类/半身类各自最差的若干条，拼成总览图人工核对。"""
from pathlib import Path
import csv
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as c  # noqa: E402

OUT = Path(__file__).resolve().parent / "chr_unified"
rows = list(csv.DictReader(open(OUT / "chr_unified.csv", encoding="utf-8")))
for r in rows:
    r["iou"] = float(r["iou"])
    r["index"] = int(r["index"])
    r["thumb_w"] = int(r["thumb_w"])
    r["thumb_h"] = int(r["thumb_h"])

body = sorted([r for r in rows if r["thumb_w"] == 160], key=lambda r: r["iou"])
half = sorted([r for r in rows if r["thumb_w"] == 35], key=lambda r: r["iou"])

sample = body[:10] + body[-2:] + half[:10] + half[-2:]


def panel(idx: int, iou: float) -> Image.Image:
    raw = c.entry(idx)
    canvas, used = c.build(raw)
    t, tw, th = c.thumb(idx + 1)
    ys, xs = np.where(canvas[:, :, 3] > 0)
    crop = canvas[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    al = crop[:, :, 3].astype(np.uint16)
    a8 = np.clip((al * 255 + 64) // 128, 0, 255).astype(np.uint8)
    rgba = np.dstack([crop[:, :, :3], a8])
    big = Image.fromarray(rgba, "RGBA")
    big.thumbnail((160, 160), Image.Resampling.LANCZOS)
    bg = Image.new("RGBA", (170, 190), (238, 238, 238, 255))
    bg.alpha_composite(big, ((170 - big.width) // 2, 4))
    ref = Image.fromarray(t, "RGBA")
    ref.thumbnail((80, 80), Image.Resampling.NEAREST)
    bg.alpha_composite(ref, (170 - ref.width - 2, 170 - ref.height))
    d = ImageDraw.Draw(bg)
    d.text((2, 172), f"#{idx} IoU {iou:.3f}", fill=(0, 0, 0, 255))
    return bg.convert("RGB")


cols = 6
rows_n = (len(sample) + cols - 1) // cols
sheet = Image.new("RGB", (170 * cols, 190 * rows_n), "white")
for n, r in enumerate(sample):
    p = panel(r["index"], r["iou"])
    sheet.paste(p, ((n % cols) * 170, (n // cols) * 190))
sheet.save(OUT / "montage_worst_and_best.png")
print("saved", OUT / "montage_worst_and_best.png")
print("body worst:", [(r["index"], r["iou"]) for r in body[:10]])
print("half worst:", [(r["index"], r["iou"]) for r in half[:10]])
