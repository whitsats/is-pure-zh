"""用新（块号）规则重出 chr_body/solo 的 400 条对照页。

条目集合 = 上一轮 solo/index.csv 里的 400 条（旧货架规则下 IoU<0.80 的那批），
按**新** IoU 升序重排（最差的排在前），每页 80 格（10 列 × 8 行），只画重建。

输出：chr_body/solo/s0..s4.png + chr_body/solo/index.csv（page,slot,index,iou）
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

SOLO = B.OUT / "solo"
COLS, ROWS = 10, 8
CELL = 180
HEAD = 14


def main():
    old = list(csv.DictReader(open(SOLO / "index.csv", encoding="utf-8")))
    todo = {int(r["index"]) for r in old}
    cur = {int(r["index"]): float(r["iou"]) for r in csv.DictReader(open(B.OUT / "chr_body.csv", encoding="utf-8"))}
    items = sorted(((cur.get(i, 0.0), i) for i in todo))
    print(f"重出 {len(items)} 条，新 IoU {items[0][0]:.3f}..{items[-1][0]:.3f}")

    per = COLS * ROWS
    meta = []
    for p in range((len(items) + per - 1) // per):
        chunk = items[p * per:(p + 1) * per]
        sheet = Image.new("RGBA", (COLS * CELL + 4 * (COLS + 1),
                                   ROWS * (CELL + HEAD) + 4 * (ROWS + 1)), (255, 255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for i, (iou, idx) in enumerate(chunk):
            c, w = i % COLS, i // COLS
            x0 = 4 + c * (CELL + 4)
            y0 = 4 + w * (CELL + HEAD + 4)
            d.text((x0, y0 + 1), f"{i}:{idx}", fill=(20, 20, 20, 255))
            canvas, _ = B.build(B.entry(idx))
            ys, xs = np.where(canvas[:, :, 3] > 0)
            if not ys.size:
                continue
            crop = canvas[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            al = np.clip((crop[:, :, 3].astype(np.uint16) * 255 + 64) // 128, 0, 255).astype(np.uint8)
            im = Image.fromarray(np.dstack([crop[:, :, :3], al]), "RGBA")
            im.thumbnail((CELL - 8, CELL - 8), Image.Resampling.LANCZOS)
            bg = Image.new("RGBA", (CELL, CELL), (255, 255, 255, 255))
            bg.alpha_composite(im, ((CELL - im.width) // 2, (CELL - im.height) // 2))
            sheet.alpha_composite(bg, (x0, y0 + HEAD))
            meta.append([p, i, idx, round(iou, 4)])
        sheet.convert("RGB").save(SOLO / f"s{p}.png")
        print(f"  saved solo/s{p}.png  {len(chunk)} 条")
    with open(SOLO / "index.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["page", "slot", "index", "iou"])
        wr.writerows(meta)
    print("done")


if __name__ == "__main__":
    main()
