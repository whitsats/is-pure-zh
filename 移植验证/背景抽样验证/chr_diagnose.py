"""Diagnose CHR pixel format and strip geometry using the paired thumbnail.

Checks:
  * which byte lane behaves like alpha (few levels, <=128, many zeros)
  * whether the thumbnail's alpha statistics match that lane
  * column occupancy runs of the 1024-wide strip
"""
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 106958848


def entry(f, index):
    f.seek(BASE + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + off)
    return unpack(f.read(length))


def tim2(raw):
    hs = struct.unpack_from('<H', raw, 0x1C)[0]
    w, h = struct.unpack_from('<HH', raw, 0x24)
    depth = raw[0x20] & 0x0F
    return w, h, depth, np.frombuffer(raw, np.uint8, offset=0x10 + hs,
                                      count=w * h * 4).reshape(h, w, 4)


def lane_stats(arr):
    out = []
    for i in range(4):
        lane = arr[..., i]
        out.append((i, int(lane.max()), int(np.unique(lane).size),
                    float((lane == 0).mean() * 100)))
    return out


def runs(occupied, min_len=8):
    out, start = [], None
    for i, v in enumerate(occupied):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i - start))
            start = None
    if start is not None and len(occupied) - start >= min_len:
        out.append((start, len(occupied) - start))
    return out


def main():
    with ISO.open('rb') as f:
        for index in (2, 4, 0):
            raw = entry(f, index)
            hs = 0x100 if (len(raw) - 0x100) % 8192 == 0 else 0x180
            px = np.frombuffer(raw, np.uint8, offset=hs)
            tw, th, depth, timg = tim2(entry(f, index + 1))
            print(f'\n=== CHR {index}: {len(raw)} bytes, header {hs:#x}, '
                  f'{px.size // 8192} pages, thumbnail {tw}x{th} depth {depth}')
            print('  raw lanes (idx, max, unique, zero%):', lane_stats(px.reshape(-1, 4)))
            print('  thumb lanes:', lane_stats(timg))
            alpha = px[3::4]
            print('  raw lane3 zero%% %.1f | thumb alpha zero%% %.1f'
                  % ((alpha == 0).mean() * 100, (timg[..., 3] == 0).mean() * 100))
            for width in (1024, 512, 256):
                if px.size // 4 % width:
                    continue
                h = px.size // 4 // width
                a = alpha.reshape(h, width)
                occ = (a > 0).any(axis=0)
                print(f'  width {width} rows {h}: occupied columns '
                      f'{occ.sum()}/{width}, runs {runs(occ)[:8]}')


if __name__ == '__main__':
    main()
