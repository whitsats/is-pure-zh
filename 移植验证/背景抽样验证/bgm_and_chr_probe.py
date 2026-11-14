"""Extract the TIM2 images inside BGM.AFS entries and render the CHR strip."""
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BGM = 103104512
CHR = 106958848
OUT = ROOT / 'bgm'
OUT.mkdir(exist_ok=True)
CHROUT = ROOT / 'chr'
CHROUT.mkdir(exist_ok=True)


def payload(f, base, index):
    f.seek(base + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(base + off)
    return unpack(f.read(length))


def tim2_images(raw):
    """Yield every TIM2 picture found in a buffer."""
    pos = 0
    while True:
        start = raw.find(b'TIM2', pos)
        if start < 0:
            break
        hs = struct.unpack_from('<H', raw, start + 0x1C)[0]
        w, h = struct.unpack_from('<HH', raw, start + 0x24)
        data = 0x10 + hs
        if w == 0 or h == 0 or data + w * h * 4 > len(raw):
            pos = start + 4
            continue
        yield start, w, h, np.frombuffer(raw, np.uint8, offset=start + data,
                                         count=w * h * 4).reshape(h, w, 4)
        pos = start + 4


def main():
    with ISO.open('rb') as f:
        for index in (0, 1):
            raw = payload(f, BGM, index)
            images = list(tim2_images(raw))
            print(f'BGM entry {index}: {len(raw)} bytes, {len(images)} TIM2 '
                  f'at {[i[0] for i in images]} sizes '
                  f'{[(i[1], i[2]) for i in images]}')
            for n, (start, w, h, px) in enumerate(images):
                im = Image.fromarray(px, 'RGBA')
                im.putalpha(im.getchannel('A').point(lambda a: min(255, a * 2)))
                path = OUT / f'BGM_{index:02}_{n}.png'
                im.save(path)
            print('   saved to', OUT)

        raw = payload(f, CHR, 2)
        hs = 0x180 if (len(raw) - 0x180) % 8192 == 0 else 0x100
        px = np.frombuffer(raw, np.uint8, offset=hs)
        strip = px.reshape(32, 1024, 4)
        out = np.dstack([strip[:, :, :3],
                         np.where(strip[:, :, 3] > 0, 255, 0).astype(np.uint8)])
        Image.fromarray(out, 'RGBA').save(CHROUT / 'strip_1024x32.png')
        print('CHR 2 strip saved', CHROUT / 'strip_1024x32.png')


if __name__ == '__main__':
    main()
