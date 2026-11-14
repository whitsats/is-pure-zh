"""找水平接缝：逐行比较相邻两行的 RGB 跳变，定位错位发生的确切 y。

剪影 IoU 只看轮廓，看不见「下巴处横向错位」这类内部问题。
对每个条目：
    diff[y] = mean(|RGB[y] - RGB[y-1]|)，只统计两行都不透明且数量 >= 30 的列
    base    = median(diff)          （正常画面内的行间差）
    peak    = max(diff) / base      （接缝强度）
输出 peak 最大的条目及其 y，并统计 y % 32 的分布（部件边界都是 32 的倍数）。

用法：python chr_seam.py [数量] [--force]
    结果写 chr_seam.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

OUT = B.OUT.parent / "chr_seam.csv"


def scan(idx: int):
    canvas, used = B.build(B.entry(idx))
    if canvas is None:
        return None
    a = canvas[:, :, 3] > 0
    rgb = canvas[:, :, :3].astype(np.int16)
    diffs, ys, counts = [], [], []
    for y in range(1, canvas.shape[0]):
        m = a[y] & a[y - 1]
        n = int(m.sum())
        if n < 30:
            continue
        d = np.abs(rgb[y, m] - rgb[y - 1, m]).mean()
        diffs.append(d)
        ys.append(y)
        counts.append(n)
    if len(diffs) < 40:
        return None
    diffs = np.asarray(diffs)
    base = float(np.median(diffs))
    if base < 1e-3:
        return None
    k = int(np.argmax(diffs))
    return {
        "index": idx,
        "peak": round(float(diffs[k] / base), 2),
        "y": ys[k],
        "y_abs32": ys[k] % 32,
        "base": round(base, 2),
        "parts": len(used),
    }


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
    rows = []
    with open(B.ISO, "rb") as f:
        import struct
        f.seek(B.BASE + 4)
        n = struct.unpack("<I", f.read(4))[0]
    idxs = [i for i in range(0, n, 2) if B.is_body(i)]
    if limit:
        idxs = idxs[:limit]
    for j, idx in enumerate(idxs):
        r = scan(idx)
        if r:
            rows.append(r)
        if j % 100 == 0:
            print("  ...", j, flush=True)
    rows.sort(key=lambda r: -r["peak"])
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["index", "peak", "y", "y_abs32", "base", "parts"])
        wr.writeheader()
        wr.writerows(rows)
    peaks = np.array([r["peak"] for r in rows])
    print(f"条目 {len(rows)}  peak 中位 {np.median(peaks):.2f}  p90 {np.percentile(peaks, 90):.2f}  max {peaks.max():.2f}")
    print("peak > 2.0:", int((peaks > 2).sum()), " > 3.0:", int((peaks > 3).sum()))
    from collections import Counter
    c = Counter(r["y_abs32"] for r in rows if r["peak"] > 2.5)
    print("强接缝的 y%32 分布:", c.most_common(8))
    print("最强 12 条:")
    for r in rows[:12]:
        print("   ", r)


if __name__ == "__main__":
    main()
