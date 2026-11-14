"""Inspect the 256-byte BG container header and the alpha mask geometry."""
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 636928


def read_entry(f, index):
    f.seek(BASE + 8 + index * 8)
    offset, length = struct.unpack('<II', f.read(8))
    f.seek(BASE + offset)
    return unpack(f.read(length))


def main():
    with ISO.open('rb') as f:
        for index in (12, 20, 278):
            raw = read_entry(f, index)
            print(f'--- BG {index} len {len(raw):#x}')
            words = struct.unpack_from('<64I', raw, 0)
            for n, value in enumerate(words):
                if value:
                    print('   +%#04x u32[%2d] = %#010x %d' % (n * 4, n, value, value))
            print('   raw[0:64]', raw[:64].hex(' '))

    # alpha mask geometry of a normal background and of the 278 card
    for index in (20, 278):
        path = ROOT / 'samples' / f'BG_{index:03}_full.png'
        im = Image.open(path).convert('RGBA')
        alpha = np.asarray(im)[:, :, 3]
        bbox = im.getchannel('A').getbbox()
        print(f'--- alpha BG {index} bbox {bbox} shape {alpha.shape}')
        rows = (alpha == 255).sum(axis=1)
        cols = (alpha == 255).sum(axis=0)
        print('   opaque rows first/last:', int(np.argmax(rows > 0)),
              int(len(rows) - 1 - np.argmax(rows[::-1] > 0)))
        print('   opaque cols first/last:', int(np.argmax(cols > 0)),
              int(len(cols) - 1 - np.argmax(cols[::-1] > 0)))
        if bbox:
            x0, y0, x1, y1 = bbox
            inside = alpha[y0:y1, x0:x1]
            print('   inside bbox opaque pct %.3f%%' % ((inside == 255).mean() * 100))
            print('   row widths unique (first 20 rows):', rows[:20].tolist())
            print('   mask rectangle?', bool((inside == 255).all()))
        # unique colours in the visible area
        arr = np.asarray(im)
        print('   RGB min/max', arr[:, :, :3].min(), arr[:, :, :3].max())
        print('   transparent RGB sample', arr[alpha == 0][:1, :3].tolist())


if __name__ == '__main__':
    main()
