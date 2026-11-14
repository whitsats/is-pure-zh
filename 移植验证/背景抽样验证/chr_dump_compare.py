"""PCSX2 纹理转储逐像素核对：条目虚拟行 vs PCSX2/textures/SLPM-66570/dumps。

原理：CHR 像素流前 32*1024 像素即 1024x32 虚拟行，PCSX2 转储的同名纹理应与之逐像素相等。
本脚本对给定条目扫全部 1024x32 转储，输出 RGB/alpha 的 max/mean 差与最佳匹配，
max==0 即引擎纹理逐像素一致；若最佳 mean 仍很大（>5），说明该条目尚未被转储。

用法：
    python chr_dump_compare.py 2840            # 核对 2840
    python chr_dump_compare.py 518             # 核对 518（已知精确匹配，用作自检）
    python chr_dump_compare.py 2840,2792       # 多条
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

DUMPS = Path(__file__).resolve().parent.parent.parent / "PCSX2" / "textures" / "SLPM-66570" / "dumps"


def virt_row(idx: int) -> np.ndarray:
    raw = B.entry(idx)
    hs = B.header_len(raw)
    px = np.frombuffer(raw, np.uint8, offset=hs, count=32 * 1024 * 4).reshape(32, 1024, 4)
    return px


def main() -> None:
    idxs = [int(a) for a in sys.argv[1:][0].split(",")] if len(sys.argv) > 1 else [2840]
    dumps = []
    for fn in sorted(os.listdir(DUMPS)):
        if not fn.lower().endswith(".png"):
            continue
        p = DUMPS / fn
        if Image.open(p).size == (1024, 32):
            dumps.append((fn, np.asarray(Image.open(p).convert("RGBA")).astype(np.int16)))
    print(f"1024x32 dumps: {len(dumps)}")
    for idx in idxs:
        v = virt_row(idx).astype(np.int16)
        scored = []
        for fn, di in dumps:
            rgbd = np.abs(di[:, :, :3] - v[:, :, :3])
            ad = np.abs(di[:, :, 3] - v[:, :, 3])
            scored.append((float(rgbd.mean()), float(rgbd.max()), float(ad.mean()), float(ad.max()), fn))
        scored.sort()
        mean, rmax, amean, amax, fn = scored[0]
        exact = (rmax == 0 and amax == 0)
        print(f"CHR {idx}: best={fn} RGB mean={mean:.4f} max={rmax:.0f} "
              f"alpha mean={amean:.4f} max={amax:.0f} "
              f"{'EXACT' if exact else ('close' if mean < 5 else 'NOT DUMPED (best is another texture)')}")


if __name__ == "__main__":
    main()
