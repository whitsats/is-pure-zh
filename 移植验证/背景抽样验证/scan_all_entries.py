"""Scan all 280 BG.AFS entries and classify container layouts (read-only).

Writes only a text report under 背景抽样验证/.
"""
from pathlib import Path
import struct
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 636928


def main():
    rows = []
    with ISO.open('rb') as f:
        f.seek(BASE)
        head = f.read(8)
        assert head[:4] == b'AFS\x00', 'AFS magic mismatch'
        count = struct.unpack('<I', head[4:])[0]
        print('AFS entries', count)
        for index in range(count):
            f.seek(BASE + 8 + index * 8)
            offset, length = struct.unpack('<II', f.read(8))
            if offset == 0 or length == 0:
                rows.append((index, 0, 0, 'EMPTY', 0))
                continue
            f.seek(BASE + offset)
            payload = f.read(length)
            try:
                raw = unpack(payload)
            except Exception as exc:
                rows.append((index, length, 0, f'UNPACK_FAIL:{exc}', 0))
                continue
            first = struct.unpack_from('<I', raw, 0)[0]
            tag = 'TIM2' if raw[:4] == b'TIM2' else f'raw:{len(raw):#x}:first:{first:#x}'
            alpha = 0
            if raw[:4] != b'TIM2' and len(raw) == 0x160100:
                pixels = np.frombuffer(raw, dtype=np.uint8, offset=256)
                alpha = int(pixels[3::4].max())
            rows.append((index, length, len(raw), tag, alpha))

    print('\nindex compressed unpacked layout alpha_max')
    for row in rows:
        print('%3d %8d %8d %-28s %3d' % row)

    print('\nlayout histogram')
    hist = Counter(r[3] for r in rows)
    for tag, n in hist.most_common():
        print('%4d  %s' % (n, tag))
    odd = [r for r in rows if r[0] % 2 == 1]
    even = [r for r in rows if r[0] % 2 == 0]
    print('\nodd entries', len(odd), 'even entries', len(even))
    print('odd layouts', Counter(r[3] for r in odd))
    print('even layouts', Counter(r[3] for r in even))
    print('alpha_max histogram (0x160100 items)', Counter(r[4] for r in rows if r[4]))
    (ROOT / 'afslayout_scan.txt').write_text(
        'index compressed unpacked layout alpha_max\n' +
        '\n'.join('%3d %8d %8d %s %3d' % r for r in rows) + '\n',
        encoding='utf-8')
    print('\nwrote', ROOT / 'afslayout_scan.txt')


if __name__ == '__main__':
    main()
