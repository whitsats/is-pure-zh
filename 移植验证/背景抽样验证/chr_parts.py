"""Decode the CHR.AFS header sections as part-placement records.

Header layout observed:
  u32[0]      = 0x0A (type)
  u32[1..N]   = byte offsets of the sections that follow
  u32[last]   = total size
Section 0 sits at u32[1] and holds (count, 0, (h<<16|w), 2) + count records.
The remaining sections are 12 bytes each and read as (x, y, (h<<16|w)).
"""
from pathlib import Path
import struct
import sys

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


def main():
    indices = [int(v) for v in (sys.argv[1:] or ['2', '6', '10', '0', '4'])]
    with ISO.open('rb') as f:
        for index in indices:
            raw = entry(f, index)
            total = len(raw)
            words = list(struct.unpack_from('<16I', raw, 0))
            print(f'\n=== CHR {index}: {total} bytes ({total:#x})')
            print('  header u32[0:12]', [hex(w) for w in words[:12]])
            starts = [w for w in words[1:11] if 0x40 <= w < total]
            starts = sorted(set(starts))
            print('  section offsets', [hex(s) for s in starts], 'end', hex(total))
            for n, s in enumerate(starts):
                end = starts[n + 1] if n + 1 < len(starts) else total
                size = end - s
                body = raw[s:end]
                if size == 12:
                    x, y, wh = struct.unpack_from('<3I', body, 0)
                    print('   +%#06x len 12  x %4d y %4d size %dx%d'
                          % (s, x, y, wh & 0xFFFF, wh >> 16))
                else:
                    head = struct.unpack_from('<4I', body, 0) if size >= 16 else ()
                    print('   +%#06x len %d  head %s' % (s, size, [hex(v) for v in head]))
                    rec = (size - 16) // 4
                    if 0 < rec <= 24:
                        vals = struct.unpack_from('<%dI' % rec, body, 16)
                        print('      records(%d): %s' % (rec, [hex(v) for v in vals]))


if __name__ == '__main__':
    main()
