"""Dump the CHR.AFS custom header word by word and guess its table layout."""
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
    with ISO.open('rb') as f:
        f.seek(BASE)
        count = struct.unpack('<I', f.read(8)[4:])[0]
        print('CHR.AFS entries', count)
        for index in (0, 2):
            raw = entry(f, index)
            print(f'\n=== CHR {index}: {len(raw)} bytes ({len(raw):#x})')
            limit = 0x180 if len(raw) > 0x20000 else 0x100
            for off in range(0, limit, 16):
                u = struct.unpack_from('<4I', raw, off)
                u16 = struct.unpack_from('<8H', raw, off)
                print('  %#05x  %08x %08x %08x %08x   u16 %s' %
                      (off, *u, ' '.join('%5d' % v for v in u16)))
            print('  tail of file', raw[-16:].hex(' '))


if __name__ == '__main__':
    main()
