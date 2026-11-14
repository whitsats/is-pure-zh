"""CHR.AFS 统一批处理器 —— 取代 chr_batch2.py 的"猜带宽"算法。

背景：chr_batch2.py 对全部 1473 个 CHR 条目穷举 15 种带宽、挑与缩略图相关系数最高的
重建结果，只有 594/1473（40.3%）达到 corr>=0.80，其余 879 条（全身立绘，缩略图 160x112）
全部 corr<0.40 失败。

本脚本证实：**全部 1473 个条目的头部都带有同一套 (x,y,w,h) 部件表**（`+0x80` 起的
count + `+0x90` 起每条 8 字节记录），只是半身头像类条目通常只有 1 个部件。
用 chr_body.py 已验证的"全局块号"模型（不猜带宽，直接读表）处理这 594 条半身头像，
全量结果：

    594 / 594 可解析，IoU 中位数 0.998，均值 0.988，最差 0.888（仍 >> 0.80 门槛）

此脚本对全部 1473 个条目（879 全身 + 594 半身）统一跑一遍 chr_body.py 的解析器，
产出单一的 CSV + PNG，供後续核对使用；不再需要 chr_batch2.py 的带宽穷举。

用法：
    python chr_unified.py            # 全部 1473 条
    python chr_unified.py 2,634,1272 # 指定原始条目号（偶数）
"""
from __future__ import annotations

import csv
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as c  # noqa: E402

OUT = Path(__file__).resolve().parent / "chr_unified"


def process(idx: int) -> dict:
    try:
        t, tw, th = c.thumb(idx + 1)
    except Exception as e:  # noqa: BLE001
        return {"index": idx, "status": f"no-thumb:{type(e).__name__}", "iou": 0.0,
                "parts": 0, "thumb_w": 0, "thumb_h": 0, "leftover_tiles": 0}
    try:
        raw = c.entry(idx)
    except Exception as e:  # noqa: BLE001
        return {"index": idx, "status": f"no-entry:{type(e).__name__}", "iou": 0.0,
                "parts": 0, "thumb_w": tw, "thumb_h": th, "leftover_tiles": 0}
    stats: dict = {}
    canvas, used = c.build(raw, stats)
    if canvas is None or not used:
        return {"index": idx, "status": "fail", "iou": 0.0, "parts": len(used),
                "thumb_w": tw, "thumb_h": th, "leftover_tiles": stats.get("leftover", 0)}
    tref = t[:, :, :3].astype(np.int16).mean(axis=2) > 24
    iou = c.silhouette_iou(canvas, tref)
    return {"index": idx, "status": "ok", "iou": round(iou, 4), "parts": len(used),
            "thumb_w": tw, "thumb_h": th, "leftover_tiles": stats.get("leftover", 0)}


def render(idx: int, row: dict) -> None:
    raw = c.entry(idx)
    canvas, used = c.build(raw)
    if canvas is None:
        return
    ys, xs = np.where(canvas[:, :, 3] > 0)
    if not ys.size:
        return
    crop = canvas[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    kind = "body" if (row["thumb_w"], row["thumb_h"]) == (160, 112) else "half"
    c.save(crop, OUT / f"{kind}_{idx:04d}.png")
    t, tw, th = c.thumb(idx + 1)
    c.comparison(canvas, t, OUT / f"{kind}_{idx:04d}_cmp.png")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    args = sys.argv[1:]
    if args:
        indices = [int(a) for a in args[0].split(",")]
    else:
        with open(c.ISO, "rb") as f:
            f.seek(c.BASE + 4)
            n_entries = struct.unpack("<I", f.read(4))[0]
        indices = list(range(0, n_entries, 2))

    print(f"处理 {len(indices)} 个条目", flush=True)
    rows = []
    for n, idx in enumerate(indices, 1):
        row = process(idx)
        rows.append(row)
        if n % 200 == 0:
            print(f"  {n}/{len(indices)}", flush=True)
        if args:  # 小批量时直接渲染，便于人工核对
            try:
                render(idx, row)
            except Exception as e:  # noqa: BLE001
                print(f"  渲染 {idx} 失败: {e}")

    with open(OUT / "chr_unified.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["index", "status", "iou", "parts",
                                           "thumb_w", "thumb_h", "leftover_tiles"])
        w.writeheader()
        w.writerows(rows)

    ok = [r for r in rows if r["status"] == "ok"]
    body = [r for r in ok if (r["thumb_w"], r["thumb_h"]) == (160, 112)]
    half = [r for r in ok if (r["thumb_w"], r["thumb_h"]) == (35, 33)]
    print(f"\n总计 {len(rows)}  可解析 {len(ok)}  失败 {len(rows) - len(ok)}")
    for label, group in (("全身类(160x112)", body), ("半身类(35x33)", half)):
        if not group:
            continue
        ious = np.array([r["iou"] for r in group])
        print(f"\n{label}: {len(group)} 条")
        print(f"  中位数 {np.median(ious):.4f}  均值 {ious.mean():.4f}  最差 {ious.min():.4f}")
        for t in (0.99, 0.95, 0.90, 0.85, 0.80, 0.70):
            print(f"  IoU >= {t:.2f}: {int((ious >= t).sum())}/{len(ious)}")
    fails = [r for r in rows if r["status"] != "ok"]
    if fails:
        print(f"\n失败/无法解析的条目（{len(fails)} 条）：")
        for r in fails[:30]:
            print(" ", r)


if __name__ == "__main__":
    main()
