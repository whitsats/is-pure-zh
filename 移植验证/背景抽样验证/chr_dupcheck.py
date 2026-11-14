"""量化「同一人物在画布上出现两次」——与缩略图无关的结构判据。

思路：正常的角色立绘在竖直方向自相关应该单调衰减；如果条目把同一人物叠了两遍，
剪影在某个位移 d 上会重现一次（自相关出现次级峰）。

对每个条目：
    m = 不透明掩码（float）
    A = 自相关（FFT）
    对 40 <= |dx|+|dy| <= 320 的每个位移，IoU(d) = inter / (2S - inter)
    dup = max IoU(d)
再用它和 IoU（与缩略图的剪影相似度）做交叉表，回答「12.7% 里多少是真的坏了」。
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

OUT = B.OUT


def dup_score(canvas):
    m = (canvas[:, :, 3] > 0).astype(np.float32)
    S = float(m.sum())
    if S < 500:
        return 0.0, (0, 0)
    a = fftconvolve(m, m[::-1, ::-1], mode="full")  # 零位移在 (H-1, W-1)
    H, W = m.shape
    best, bestd = 0.0, (0, 0)
    # 只搜竖直为主、允许少量水平偏移的位移
    for dy in range(40, 321, 8):
        row = a[H - 1 + dy]           # 整体下移 dy 后的重叠量
        for dx in (-64, -32, 0, 32, 64):
            if not (0 <= W - 1 + dx < W):
                continue
            inter = float(row[W - 1 + dx])
            if inter <= 0:
                continue
            iou = inter / (2 * S - inter)
            if iou > best:
                best, bestd = iou, (dx, dy)
    return best, bestd


def main():
    rows = list(csv.DictReader(open(OUT / "chr_body.csv", encoding="utf-8")))
    out = []
    for r in rows:
        idx = int(r["index"])
        canvas, _ = B.build(B.entry(idx))
        if canvas is None:
            continue
        d, dd = dup_score(canvas)
        out.append((idx, float(r["iou"]), round(d, 3), dd))
    out.sort(key=lambda t: t[1])

    with open(OUT / "chr_dup.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "iou", "dup", "dup_dx", "dup_dy"])
        for idx, iou, d, dd in out:
            w.writerow([idx, iou, d, dd[0], dd[1]])

    low = [t for t in out if t[1] < 0.70]
    high = [t for t in out if t[1] >= 0.70]
    print(f"全部 {len(out)} 条；IoU<0.70 的 {len(low)} 条，>=0.70 的 {len(high)} 条")
    for thr in (0.40, 0.50, 0.60, 0.70):
        a = sum(1 for t in low if t[2] >= thr)
        b = sum(1 for t in high if t[2] >= thr)
        print(f"  dup >= {thr:.2f}:  低分组 {a:3d}/{len(low)}  高分组 {b:3d}/{len(high)}")
    print("\n低分组前 25 条（idx, iou, dup, 位移）:")
    for t in low[:25]:
        print("   ", t)


if __name__ == "__main__":
    main()
