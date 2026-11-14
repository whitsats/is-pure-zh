"""Locate every AFS archive in the ISO and classify its entries.

Scans 2048-byte sector boundaries for the 'AFS\\0' magic, prints the archive
offset, entry count and a size/layout histogram of its entries (read-only).
"""
from pathlib import Path
import struct
import sys
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
SECTOR = 2048


def find_archives(f):
    f.seek(0, 2)
    total = f.tell()
    hits = []
    offset = 0
    while offset < total:
        f.seek(offset)
        block = f.read(SECTOR + 8)
        if block[:4] == b'AFS\x00':
            count = struct.unpack('<I', block[4:8])[0]
            if 0 < count < 5000:
                hits.append((offset, count))
        offset += SECTOR
    return hits, total


def classify(f, base, count):
    rows = []
    table_end = base + 8 + count * 8
    for index in range(count):
        f.seek(base + 8 + index * 8)
        entry = f.read(8)
        if len(entry) < 8:
            rows.append((index, 0, 0, 'TRUNCATED'))
            continue
        off, length = struct.unpack('<II', entry)
        if off == 0 or length == 0:
            rows.append((index, 0, 0, 'EMPTY'))
            continue
        if base + off < table_end:
            rows.append((index, length, 0, 'OVERLAPS_TABLE'))
            continue
        f.seek(base + off)
        payload = f.read(length)
        try:
            raw = unpack(payload)
        except Exception:
            rows.append((index, length, 0, 'NOT_LZSS'))
            continue
        if raw[:4] == b'TIM2':
            tag = 'TIM2'
        elif len(raw) == 0x160100 and raw[:4] == b'\x05\x00\x00\x00':
            tag = 'BG_0x160100'
        else:
            first = struct.unpack_from('<I', raw, 0)[0]
            tag = f'raw:{len(raw):#x}:first:{first:#x}'
        rows.append((index, length, len(raw), tag))
    return rows


def main():
    with ISO.open('rb') as f:
        hits, total = find_archives(f)
        print('ISO size', total, 'AFS candidates', len(hits))
        for base, count in hits:
            print('\n=== AFS at 0x%x (%d) entries %d' % (base, base, count))
            rows = classify(f, base, count)
            hist = Counter(r[3] for r in rows)
            for tag, n in hist.most_common(10):
                print('   %4d  %s' % (n, tag))
            for row in rows[:4]:
                print('   entry %3d size %8d unpacked %9d %s' % row)
            if count > 4:
                print('   ...')
                for row in rows[-2:]:
                    print('   entry %3d size %8d unpacked %9d %s' % row)


if __name__ == '__main__':
    main()
