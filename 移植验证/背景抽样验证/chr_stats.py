"""Collect header statistics for all CHR.AFS sprite entries.

Only the head of each LZSS stream is inflated (the raw size is stored in the
first four compressed bytes), so this covers all 1473 entries quickly.
"""
from pathlib import Path
import struct
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 106958848
NEED = 0x200


def unpack_prefix(blob, need):
    """Inflate at most `need` bytes of the LZSS stream (same format as
    extract_bg.unpack, but stops early)."""
    size = int.from_bytes(blob[:4], 'little')
    ring, at, pos, out = bytearray(4096), 0xfee, 4, bytearray()
    while pos < len(blob) and len(out) < min(size, need):
        flag = blob[pos]
        pos += 1
        for _ in range(8):
            if pos >= len(blob) or len(out) >= min(size, need):
                break
            if flag & 1:
                n = blob[pos]
                pos += 1
                out.append(n)
                ring[at] = n
                at = (at + 1) & 4095
            else:
                a, b = blob[pos:pos + 2]
                pos += 2
                src = a | ((b & 0xF0) << 4)
                for j in range((b & 15) + 3):
                    n = ring[(src + j) & 4095]
                    out.append(n)
                    ring[at] = n
                    at = (at + 1) & 4095
                    if len(out) >= min(size, need):
                        break
        if len(out) >= min(size, need):
            break
    return size, bytes(out)


def main():
    rows = []
    with ISO.open('rb') as f:
        f.seek(BASE)
        count = struct.unpack('<I', f.read(8)[4:])[0]
        for index in range(0, count, 2):
            f.seek(BASE + 8 + index * 8)
            off, length = struct.unpack('<II', f.read(8))
            f.seek(BASE + off)
            blob = f.read(length)
            raw_len, head = unpack_prefix(blob, NEED)
            hs = 0x100 if (raw_len - 0x100) % 8192 == 0 else 0x180
            declared = struct.unpack_from('<I', head, 0x88)[0]
            w, h = declared & 0xFFFF, declared >> 16
            parts = struct.unpack_from('<I', head, 0x80)[0]
            rows.append((index, raw_len, hs, w, h, parts, length))

    print('entries', len(rows))
    print('header sizes', Counter(r[2] for r in rows))
    print('raw_len range', min(r[1] for r in rows), max(r[1] for r in rows))
    print('parts field histogram', Counter(r[5] for r in rows).most_common(12))
    print('declared sizes (top 12)',
          Counter((r[3], r[4]) for r in rows).most_common(12))
    ratios = []
    for r in rows:
        px = (r[1] - r[2]) // 4
        area = r[3] * r[4]
        if area:
            ratios.append((px / area, r))
    ratios.sort(key=lambda t: t[0])
    print('pixel/declared-area ratio: min %.3f median %.3f max %.3f' %
          (ratios[0][0], ratios[len(ratios) // 2][0], ratios[-1][0]))
    print('\nclosest to ratio 1.0:')
    for ratio, r in sorted(ratios, key=lambda t: abs(t[0] - 1))[:8]:
        print('  CHR %4d raw %8d hs %#5x declared %dx%d parts %d ratio %.3f'
              % (r[0], r[1], r[2], r[3], r[4], r[5], ratio))

    (ROOT / 'chr_stats.txt').write_text(
        'index raw_len header declared_w declared_h parts compressed\n' +
        '\n'.join('%4d %8d %#5x %4d %4d %3d %8d' % r for r in rows) + '\n',
        encoding='utf-8')
    print('wrote', ROOT / 'chr_stats.txt')


if __name__ == '__main__':
    main()
