"""给 879 条部件图集打分并落逐条标签（供 6.7 节核对）。

剪影 IoU 看不见两类问题：胸口/身上的白块、以及块状遗骸（矩形碎块面积小、对剪影几乎无影响）。
这里补两个与内部像素有关的判据：

  hole   轮廓内部的透明洞占比  = 填洞后的掩码 - 原掩码 / 原掩码
         （部件没铺满导致的白块，渲染时会露出背景）
  color  与缩略图逐像素 RGB 一致率：两边都按包围盒裁切、把重建缩放到缩略图大小，
         只统计两边都不透明的像素，|ΔRGB| < 48 视为一致
         （白块、错位的块状遗骸都会让对应位置的 RGB 对不上）

另附 stray = 与主体不相连的不透明块占比（块状遗骸）。

用法：
    python chr_label.py stats          # 打印分布，帮助定阈值
    python chr_label.py labels         # 写 chr_body/all/labels.csv（含目视判定）
    python chr_label.py slots          # 按页打印槽位顺序，便于逐页判读
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

OUT = B.OUT / "all"
CACHE = OUT / "metrics.json"


def metrics(idx: int):
    canvas, used = B.build(B.entry(idx))
    if canvas is None:
        return None
    t, _, _ = B.thumb(idx + 1)
    m = canvas[:, :, 3] > 0
    S = int(m.sum())
    if S < 200:
        return None
    # 洞
    filled = ndimage.binary_fill_holes(m)
    hole = float((filled & ~m).sum() / S)
    # 与主体不相连的块
    lab, n = ndimage.label(filled)
    if n > 1:
        sizes = np.asarray(ndimage.sum(m, lab, range(1, n + 1)))
        stray = float((sizes.sum() - sizes.max()) / S)
    else:
        stray = 0.0
    # 接缝对比度：部件矩形边界处的 RGB 跳变 / 全图相邻列基线
    seam = seam_ratio(canvas, used) if used else 0.0
    # RGB 一致率（包围盒归一化）
    ys, xs = np.where(m)
    rec = canvas[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    tm = t[:, :, 3] > 0
    ty, tx = np.where(tm)
    th = t[ty.min():ty.max() + 1, tx.min():tx.max() + 1]
    h, w = th.shape[:2]
    rr = np.asarray(Image.fromarray(rec, "RGBA").resize((w, h), Image.Resampling.BILINEAR)).astype(np.int16)
    rm = rr[:, :, 3] > 96
    tm = th[:, :, 3] > 0
    common = rm & tm
    if common.sum() < 200:
        color = 0.0
    else:
        d = np.abs(rr[:, :, :3] - th[:, :, :3].astype(np.int16)).sum(axis=2)
        color = float((d[common] < 144).mean())   # 144 = 每通道平均 48
    return {"hole": round(hole, 4), "stray": round(stray, 4),
            "color": round(color, 4), "seam": round(seam, 3)}


def seam_ratio(canvas, used):
    """部件边界两侧的 RGB 跳变相对全图基线的倍数。布局正确时≈ 1，错位时远大于 1。"""
    rgb = canvas[:, :, :3].astype(np.int16)
    a = canvas[:, :, 3] > 0
    H, W = a.shape
    base = []
    for x in range(1, W):
        m = a[:, x] & a[:, x - 1]
        if m.sum() >= 8:
            base.append(np.abs(rgb[m, x] - rgb[m, x - 1]).mean())
    for y in range(1, H):
        m = a[y, :] & a[y - 1, :]
        if m.sum() >= 8:
            base.append(np.abs(rgb[y, m] - rgb[y - 1, m]).mean())
    if not base:
        return 0.0
    b = float(np.median(base))
    if b < 1e-3:
        return 0.0
    seams = []
    for r in used:
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        for xx in (x, x + w - 1):
            if 1 <= xx < W:
                for dx in (-1, 1):
                    x2 = xx + dx
                    if 0 <= x2 < W:
                        m = a[:, xx] & a[:, x2]
                        if m.sum() >= 4:
                            seams.append(np.abs(rgb[m, xx] - rgb[m, x2]).mean())
        for yy in (y, y + h - 1):
            if 1 <= yy < H:
                for dy in (-1, 1):
                    y2 = yy + dy
                    if 0 <= y2 < H:
                        m = a[yy, :] & a[y2, :]
                        if m.sum() >= 4:
                            seams.append(np.abs(rgb[yy, m] - rgb[y2, m]).mean())
    if not seams:
        return 0.0
    return float(np.median(seams) / b)


def load_all(force=False):
    if CACHE.exists() and not force:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(open(B.OUT / "chr_body.csv", encoding="utf-8")))
    out = {}
    for i, r in enumerate(rows):
        idx = int(r["index"])
        mt = metrics(idx)
        if mt:
            out[str(idx)] = {**mt, "iou": float(r["iou"])}
        if i % 100 == 0:
            print("  ...", i, flush=True)
    CACHE.write_text(json.dumps(out), encoding="utf-8")
    return out


def cmd_stats(data):
    import statistics as st
    for k in ("hole", "stray", "color"):
        v = [d[k] for d in data.values()]
        q = sorted(v)
        print(f"{k}: min {q[0]:.3f}  p10 {q[len(q)//10]:.3f}  median {st.median(v):.3f}  "
              f"p90 {q[9*len(q)//10]:.3f}  max {q[-1]:.3f}")
    for thr in (0.90, 0.80, 0.70, 0.60, 0.50):
        print(f"  color < {thr:.2f}: {sum(1 for d in data.values() if d['color'] < thr)}")
    for thr in (0.005, 0.01, 0.02, 0.04):
        print(f"  hole  > {thr:.3f}: {sum(1 for d in data.values() if d['hole'] > thr)}")
    for thr in (0.01, 0.02, 0.05):
        print(f"  stray > {thr:.3f}: {sum(1 for d in data.values() if d['stray'] > thr)}")
    # 与 IoU 的关系（某档为空时跳过，避免 statistics 报无中位数）
    for lo, hi, tag in ((0.0, 0.70, "IoU<0.70"), (0.80, 1.01, "IoU>=0.80")):
        g = [d for d in data.values() if lo <= d["iou"] < hi]
        if not g:
            print(f"\n{tag} n=0")
            continue
        print(f"\n{tag} n={len(g)}  color 中位数 {st.median([d['color'] for d in g]):.3f} "
              f"hole 中位数 {st.median([d['hole'] for d in g]):.4f}")


def cmd_slots():
    rows = list(csv.DictReader(open(OUT / "index.csv", encoding="utf-8")))
    pages = {}
    for r in rows:
        pages.setdefault(int(r["page"]), []).append((int(r["slot"]), int(r["index"])))
    for p in sorted(pages):
        items = sorted(pages[p])
        print(f"page{p:02d}: " + " ".join(f"{s}:{i}" for s, i in items))


def cmd_labels(data):
    # 目视判定：chr_body/solo/visual_labels.py 的 LABELS，字符位置 = solo 页 slot（行优先）
    sys.path.insert(0, str(B.OUT / "solo"))
    from visual_labels import LABELS as labels  # noqa: E402
    rows = list(csv.DictReader(open(B.OUT / "solo" / "index.csv", encoding="utf-8")))
    out = []
    for r in rows:
        idx = int(r["index"])
        d = data.get(str(idx))
        if not d:
            continue
        s = labels.get(f"s{int(r['page'])}", "")
        ch = s[int(r["slot"])] if len(s) > int(r["slot"]) else "?"
        vis = {"b": "bad", "o": "ok", "e": "edge", "?": "?"}.get(ch, "?")
        obj_bad = (d["hole"] > 0.02) or (d["iou"] < 0.60)
        out.append([int(r["page"]), int(r["slot"]), idx, round(d["iou"], 4),
                    d["color"], d["hole"], d["stray"], "bad" if obj_bad else "ok", vis])
    with open(B.OUT / "solo" / "labels.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["page", "slot", "index", "iou", "color", "hole", "stray", "auto", "visual"])
        wr.writerows(out)
    n_auto = sum(1 for r in out if r[7] == "bad")
    n_vis = sum(1 for r in out if r[8] == "bad")
    agree = sum(1 for r in out if r[8] in ("ok", "bad") and r[7] == r[8])
    judged = sum(1 for r in out if r[8] in ("ok", "bad"))
    print(f"labels.csv {len(out)} 行；auto bad {n_auto}；visual bad {n_vis}；"
          f"两者一致 {agree}/{judged}")
    # 全量 879 的 auto 统计
    all_bad = sum(1 for d in data.values()
                  if (d["hole"] > 0.02) or (d["iou"] < 0.60))
    print(f"全量 {len(data)} 条中 auto bad = {all_bad}（{all_bad / len(data) * 100:.1f}%）")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "stats"
    data = load_all(force="--force" in sys.argv)
    if mode == "slots":
        cmd_slots()
    elif mode == "labels":
        cmd_labels(data)
    else:
        cmd_stats(data)
