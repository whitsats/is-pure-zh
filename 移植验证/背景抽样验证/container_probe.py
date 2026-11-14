"""Dump container headers of CHR.AFS / EV.AFS / ETC.AFS / VOICE.AFS entries."""
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
ARCHIVES = {
    'CHR': 106958848, 'EV': 343689216, 'ETC': 325799936,
    'BGM': 103104512, 'SE': 395005952, 'VOICE': 696072192,
}


def afs_entry(f, base, index):
    f.seek(base)
    head = f.read(8)
    if head[:4] != b'AFS\x00':
        return head, None, None
    count = struct.unpack('<I', head[4:])[0]
    if index >= count:
        return head, count, None
    f.seek(base + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    if not off or not length:
        return head, count, (off, length, b'')
    f.seek(base + off)
    return head, count, (off, length, f.read(length))


def words(raw, n=16):
    n = max(1, min(n, len(raw) // 4))
    return [hex(v) for v in struct.unpack_from('<%dI' % n, raw, 0)]


def main():
    with ISO.open('rb') as f:
        for name in ('CHR', 'EV', 'ETC'):
            base = ARCHIVES[name]
            f.seek(base)
            head = f.read(8)
            count = struct.unpack('<I', head[4:])[0]
            print(f'\n== {name}.AFS base {base} entries {count}')
            for index in (0, 1, 2, 3, 4, 5):
                _, _, entry = afs_entry(f, base, index)
                if entry is None:
                    print(' ', index, 'missing')
                    continue
                off, length, payload = entry
                try:
                    raw = unpack(payload)
                except Exception as exc:
                    print(' ', index, 'unpack failed', exc, 'len', length)
                    continue
                if not raw:
                    print(' ', index, 'EMPTY payload (compressed len %d)' % length)
                    continue
                printable = ''.join(chr(c) if 32 <= c < 127 else '.'
                                    for c in raw[:4])
                print('  entry %d comp %7d raw %8d %s' % (index, length, len(raw),
                                                         printable))
                print('    u32', words(raw, 12))
                if raw[:4] == b'TIM2':
                    fmt, ver, nxt = struct.unpack_from('<BBH', raw, 4)[0], 0, 0
                    total = struct.unpack_from('<I', raw, 8)[0]
                    pcount = struct.unpack_from('<I', raw, 16)[0]
                    print('    TIM2 total', total, 'pictures', pcount)
                    if pcount == 1 and len(raw) >= 48:
                        hdr_size = struct.unpack_from('<H', raw, 28)[0]
                        w, h = struct.unpack_from('<HH', raw, 36)
                        img_type = raw[35]
                        print('    TIM2 w', w, 'h', h, 'type', img_type,
                              'hdr', hdr_size, 'data at', 16 + hdr_size)

        print('\n== VOICE.AFS first bytes')
        f.seek(ARCHIVES['VOICE'])
        print('  ', f.read(32).hex(' '))

        print('\n== BGM.AFS entry 0')
        _, count, entry = afs_entry(f, ARCHIVES['BGM'], 0)
        if entry:
            off, length, payload = entry
            print('   comp', length, 'first bytes', payload[:32].hex(' '))
            raw = unpack(payload)
            print('   raw', len(raw), 'head', raw[:48].hex(' '))
            print('   u32', words(raw, 12))

        print('\n== SE.AFS entry 0 (not LZSS)')
        _, count, entry = afs_entry(f, ARCHIVES['SE'], 0)
        if entry:
            off, length, payload = entry
            print('   len', length, 'head', payload[:48].hex(' '))
            print('   ascii', payload[:16])


if __name__ == '__main__':
    main()
