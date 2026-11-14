"""Probe BG.AFS: validate ISO/AFS header, then inspect sampled even entries.

Read-only: opens the ISO once for reading and writes nothing but stdout.
"""
from pathlib import Path
import hashlib
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
BASE = 636928
SAMPLE = [12, 14, 16, 18, 20, 40, 80, 120, 160, 200, 240, 278, 279]


def main():
    if not ISO.exists():
        raise SystemExit(f'ISO missing: {ISO}')
    print('ISO', ISO, 'size', ISO.stat().st_size)
    with ISO.open('rb') as f:
        f.seek(BASE)
        head = f.read(8)
        print('AFS header at base: magic %r count %d' % (head[:4], struct.unpack('<I', head[4:])[0]))
        if head[:4] != b'AFS\x00':
            raise SystemExit('AFS magic mismatch - wrong ISO layout')
        count = struct.unpack('<I', head[4:])[0]
        print('entry table bytes', count * 8, 'ends at', hex(BASE + 8 + count * 8))
        for index in SAMPLE:
            f.seek(BASE + 8 + index * 8)
            entry = f.read(8)
            if len(entry) < 8:
                print(index, 'entry truncated')
                continue
            offset, length = struct.unpack('<II', entry)
            if offset == 0 or length == 0:
                print(index, 'EMPTY entry', offset, length)
                continue
            f.seek(BASE + offset)
            payload = f.read(length)
            digest = hashlib.sha1(payload).hexdigest()[:16]
            try:
                raw = unpack(payload)
            except Exception as exc:
                print(index, 'UNPACK FAILED', exc, 'compressed', length, 'sha1', digest)
                continue
            print(index, 'compressed', length, 'unpacked', len(raw), hex(len(raw)),
                  'head', raw[:24].hex(' '), 'sha1', digest)
            # first 256 bytes look like a 64-entry table of uint32
            if len(raw) >= 256:
                table = struct.unpack_from('<64I', raw, 0)
                print('   table[0:8]', [hex(v) for v in table[:8]],
                      'nonzero', sum(1 for v in table if v), 'max', hex(max(table)))
            # candidate TIM2 style
            if raw[:4] == b'TIM2':
                print('   TIM2 container')


if __name__ == '__main__':
    main()
