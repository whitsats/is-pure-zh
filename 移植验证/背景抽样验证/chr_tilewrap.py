"""按 32×32 块全局连续编号的读取模型（GPT/DeepSeek 提出的候选规则）。

与 chr_body.py 的"货架"模型差别只在 w 不是 32 的整数倍行宽时：
  - 货架：一条宽 w 的条带整条放在 1024 行内，放不下就整条换行（行尾剩下的块丢弃）；
  - tile：所有部件共用连续块号 tile，源坐标 sx=(tile%32)*32, sy=(tile//32)*32，
          读完一块 tile+=1，部件内按 y=0..h-32、x=0..w-32 的顺序取块。
          w=32 时两者等价；w=96/160/192 时不同（块可以跨存储行）。

用法：
    python chr_tilewrap.py            # 全部 879 条，输出 chr_tile.csv 并与 chr_body.csv 对比
    python chr_tilewrap.py 634 1272   # 指定条目，输出对照图
"""
from __future__ import annotations

import csv
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

OUT = Path(__file__).resolve().parent / "chr_tile"


def build_tile(raw: bytes):
    hs = B.header_len(raw)
    px = np.frombuffer(raw, np.uint8, offset=hs, count=((len(raw) - hs) // 4) * 4)
    total = px.size // 4
    recs = B.records(raw, hs)
    if not recs:
        return None, [], []
    block = px[: (total // 1024) * 1024 * 4].reshape(-1, 32, 1024, 4)
    nband = block.shape[0]
    canvas = np.zeros((B.CANVAS[1], B.CANVAS[0], 4), np.uint8)
    tile = 0
    used, warn = [], []
    total_tiles = nband * 32
    for k, r in enumerate(recs):
        w, h = r["w"], r["h"]
        if k == len(recs) - 1 or r["end"] == 0:
            h = ((total - tile * 1024) // w) if w else 0
        tw, th = max(1, w // 32), max(1, h // 32)
        piece = np.zeros((th * 32, tw * 32, 4), np.uint8)
        for j in range(th):
            for i in range(tw):
                if tile >= total_tiles:
                    warn.append(f"p{k} 块号越界 {tile}")
                    break
                sy, sx = tile // 32, tile % 32
                piece[j * 32:(j + 1) * 32, i * 32:(i + 1) * 32] = block[sy, :, sx * 32:(sx + 1) * 32]
                tile += 1
        x, y = r["x"], r["y"]
        Hh = min(piece.shape[0], canvas.shape[0] - y)
        Ww = min(piece.shape[1], canvas.shape[1] - x)
        if Hh <= 0 or Ww <= 0 or x >= canvas.shape[1] or y >= canvas.shape[0]:
            warn.append(f"p{k} 画布越界 x={x} y={y} w={w} h={h}")
            continue
        sub = piece[:Hh, :Ww]
        m = sub[:, :, 3] > 0
        canvas[y:y + Hh, x:x + Ww][m] = sub[m]
        used.append({**r, "index": k})
    if tile * 1024 < total:
        warn.append(f"未消费 {total - tile * 1024} 像素")
    return canvas, used, warn


def main():
    OUT.mkdir(exist_ok=True)
    args = [int(a) for a in sys.argv[1:]]
    if args:
        for idx in args:
            canvas, used, warn = build_tile(B.entry(idx))
            t, w, h = B.thumb(idx + 1)
            tref = t[:, :, :3].astype(np.int16).mean(axis=2) > 24
            iou = B.silhouette_iou(canvas, tref) if canvas is not None else 0
            old = B.build(B.entry(idx))[0]
            old_iou = B.silhouette_iou(old, tref) if old is not None else 0
            print(f"CHR {idx}: tile {len(used)}件 IoU {iou:.3f}   (货架 {old_iou:.3f})  warn={len(warn)}")
            for tag, c in (("tile", canvas), ("old", old)):
                if c is None:
                    continue
                a = np.where(c[:, :, 3] > 0, 255, 0).astype(np.uint8)
                rgb = c[:, :, :3].astype(np.uint16)
                al = c[:, :, 3].astype(np.uint16)
                rgb = np.clip((rgb * al[..., None] + 127) // 255, 0, 255).astype(np.uint8)
                Image.fromarray(np.dstack([rgb, a]), "RGBA").save(OUT / f"{tag}_{idx:04d}.png")
        return

    rows = []
    with open(B.ISO, "rb") as f:
        f.seek(B.BASE + 4)
        n = struct.unpack("<I", f.read(4))[0]
    for idx in range(0, n, 2):
        if not B.is_body(idx):
            continue
        canvas, used, warn = build_tile(B.entry(idx))
        t, w, h = B.thumb(idx + 1)
        tref = t[:, :, :3].astype(np.int16).mean(axis=2) > 24
        iou = B.silhouette_iou(canvas, tref) if canvas is not None else 0.0
        rows.append([idx, round(iou, 4), len(used), len(warn), "; ".join(warn[:3])])
    with open(OUT / "chr_tile.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["index", "iou_tile", "parts", "warnings", "warn_text"])
        wr.writerows(rows)

    old = {int(r["index"]): float(r["iou"]) for r in csv.DictReader(open(B.OUT / "chr_body.csv", encoding="utf-8"))}
    new = {r[0]: r[1] for r in rows}
    common = sorted(set(old) & set(new))
    a = np.array([old[i] for i in common])
    b = np.array([new[i] for i in common])
    print(f"条目 {len(common)}")
    print(f"  货架  中位 {np.median(a):.3f}  ≥0.90 {int((a >= 0.9).sum())}  ≥0.80 {int((a >= 0.8).sum())}  <0.70 {int((a < 0.7).sum())}")
    print(f"  tile  中位 {np.median(b):.3f}  ≥0.90 {int((b >= 0.9).sum())}  ≥0.80 {int((b >= 0.8).sum())}  <0.70 {int((b < 0.7).sum())}")
    print(f"  变好的 {(b > a + 0.02).sum()}  变差的 {(b < a - 0.02).sum()}  基本不变 {((np.abs(b - a) <= 0.02)).sum()}")
    print(f"  总警告 {sum(r[3] for r in rows)} 条，涉及 {sum(1 for r in rows if r[3])} 个条目")


if __name__ == "__main__":
    main()
