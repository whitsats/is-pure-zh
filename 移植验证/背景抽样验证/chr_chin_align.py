"""下巴错位定量定位：把缩略图拉伸到 704×480，逐 16 行带算最佳垂直位移 dy。

逻辑：若重建内部在某个 y 有真实错位，则该 y 上下的内容相对缩略图的位移会**跳变**；
若只是整张图的整体偏移/缩比，dy 全程应为常数。
"""
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, ".")
import chr_body as B  # noqa: E402


def prep(idx):
    raw = B.entry(idx)
    c, used = B.build(raw)
    al = np.clip((c[:, :, 3].astype(np.uint16) * 255 + 64) // 128, 0, 255).astype(np.uint8)
    rec = Image.new("RGBA", (704, 480), (255, 255, 255, 255))
    rec.alpha_composite(Image.fromarray(np.dstack([c[:, :, :3], al]), "RGBA"))
    rec = rec.convert("L")
    t, w, h = B.thumb(idx + 1)
    a = np.clip((t[:, :, 3:4].astype(np.uint16) * 255 + 64) // 128, 0, 255).astype(np.uint8)
    th = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    th.alpha_composite(Image.fromarray(np.dstack([t[:, :, :3], a]), "RGBA"))
    th = th.convert("L").resize((704, 480), Image.Resampling.BILINEAR)
    return np.asarray(rec, np.float32), np.asarray(th, np.float32)


def best_dy(A, T, y0, y1, xs, rng=10):
    """在 y0..y1 行、给定列上，求 T 相对 A 的最佳垂直位移（T 上移 dy 后更像 A）"""
    A = A[y0:y1][:, xs]
    best, bd = -9e9, 0
    for dy in range(-rng, rng + 1):
        T2 = T[y0 + dy:y1 + dy][:, xs]
        if T2.shape != A.shape:
            continue
        m = (A < 250) | (T2 < 250)
        if m.sum() < 200:
            continue
        d = A[m] - T2[m]
        sc = -float(np.abs(d).mean())
        if sc > best:
            best, bd = sc, dy
    return bd, -best


def run(idx):
    A, T = prep(idx)
    xs = np.where((A < 250).any(axis=0))[0]
    xs = slice(max(0, xs.min()), min(704, xs.max() + 1))
    g, err = best_dy(A, T, 0, 480, xs)
    print(f"\n=== CHR {idx} 全图最佳 dy={g} (MAE {err:.1f}) ===")
    print("  行带   dy   MAE   （若 dy 在某行附近跳变，即重建内部错位）")
    rows = []
    for y0 in range(0, 480, 16):
        dy, e = best_dy(A, T, y0, min(480, y0 + 48), xs, rng=14)
        rows.append((y0, dy, e))
        print(f"  {y0:3d}-{y0 + 48:3d}  {dy:+3d}  {e:5.1f}")
    dys = [r[1] for r in rows if r[2] < 40]
    if dys:
        print(f"  dy 范围 {min(dys)}..{max(dys)}，中位 {int(np.median(dys))}；"
              f"跳变>1 的行带: {[r[0] for i, r in enumerate(rows) if i and abs(r[1] - rows[i - 1][1]) > 1 and r[2] < 40]}")
    return rows


for a in sys.argv[1:]:
    run(int(a))
