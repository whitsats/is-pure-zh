"""List ISO9660 directory records so AFS archives get their real names."""
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
SECTOR = 2048


def read_sectors(f, lba, length):
    f.seek(lba * SECTOR)
    return f.read(length)


def walk(f, lba, size, prefix='', depth=0, out=None):
    out = out if out is not None else []
    data = read_sectors(f, lba, size)
    pos = 0
    while pos < len(data):
        rec_len = data[pos]
        if rec_len == 0:
            pos = (pos // SECTOR + 1) * SECTOR
            continue
        rec = data[pos:pos + rec_len]
        ext_attr, ext_lba, ext_size = struct.unpack_from('<BIB', rec, 1)[0], 0, 0
        ext_lba = struct.unpack_from('<I', rec, 2)[0]
        ext_size = struct.unpack_from('<I', rec, 10)[0]
        flags = rec[25]
        name_len = rec[32]
        raw_name = rec[33:33 + name_len]
        pos += rec_len
        if raw_name in (b'\x00', b'\x01'):
            continue
        name = raw_name.decode('latin-1')
        if ';' in name:
            name = name.split(';')[0]
        if flags & 0x02:
            if depth < 3:
                walk(f, ext_lba, ext_size, prefix + name + '/', depth + 1, out)
        else:
            out.append((prefix + name, ext_lba, ext_size))
    return out


def main():
    with ISO.open('rb') as f:
        pvd = read_sectors(f, 16, SECTOR)
        assert pvd[1:6] == b'CD001', 'not an ISO9660 image'
        root = pvd[156:156 + 34]
        root_lba = struct.unpack_from('<I', root, 2)[0]
        root_size = struct.unpack_from('<I', root, 10)[0]
        print('volume id', pvd[40:72].decode('latin-1').strip())
        files = walk(f, root_lba, root_size)
        print('%-42s %10s %10s' % ('name', 'offset', 'size'))
        for name, lba, size in sorted(files, key=lambda r: r[1]):
            print('%-42s %10d %10d' % (name, lba * SECTOR, size))


if __name__ == '__main__':
    main()
