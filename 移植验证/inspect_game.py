from pathlib import Path
import struct

iso = Path(__file__).resolve().parent.parent / 'game-v5.iso'
with iso.open('rb') as f:
    f.seek(16 * 2048 + 156)
    root = f.read(34)
    lba, size = struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0]
    f.seek(lba * 2048)
    data = f.read(size)
    pos = 0
    entries = {}
    while pos < size:
        n = data[pos]
        if not n:
            pos = (pos // 2048 + 1) * 2048
            continue
        r = data[pos:pos+n]
        name = r[33:33+r[32]].decode('ascii', 'replace').split(';')[0]
        entries[name] = (struct.unpack_from('<I', r, 2)[0]*2048, struct.unpack_from('<I', r, 10)[0])
        pos += n
    print('ISO:', entries)
    movie_base, movie_size = entries['MOVIE']
    f.seek(movie_base)
    directory = f.read(movie_size)
    pos = 0
    while pos < len(directory) and directory[pos]:
        n = directory[pos]
        r = directory[pos:pos+n]
        name = r[33:33+r[32]].decode('ascii', 'replace').split(';')[0]
        if name not in ('\x00', '\x01'):
            off = struct.unpack_from('<I', r, 2)[0] * 2048
            length = struct.unpack_from('<I', r, 10)[0]
            print('MOVIE', name, off, length)
            if name.upper().endswith('.PSS') and length < 200_000_000:
                f.seek(off)
                (Path(__file__).parent / 'sample.pss').write_bytes(f.read(length))
                break
        pos += n
    for name in ('BG.AFS','CHR.AFS','EV.AFS','MAC.AFS'):
        if name not in entries: continue
        base, length = entries[name]
        f.seek(base)
        magic, count = struct.unpack('<4sI', f.read(8))
        print(name, magic, count)
        table = f.read(min(count, 5)*8)
        for i in range(min(count, 5)):
            off, n = struct.unpack_from('<II', table, i*8)
            f.seek(base+off)
            print(' ',i,n,f.read(48).hex(' '))
