"""Identify audio containers in BGM.AFS / SE.AFS / VOICE.AFS."""
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
ARCHIVES = {'BGM': 103104512, 'SE': 395005952, 'VOICE': 696072192}

MAGICS = [b'VAGp', b'VAGi', b'RIFF', b'OggS', b'\x80\x00', b'SShd', b'SSHD',
          b'PS2', b'PSS', b'ADX', b'\x00\x00\x00\x00']


def main():
    with ISO.open('rb') as f:
        for name, base in ARCHIVES.items():
            f.seek(base)
            head = f.read(8)
            print(f'\n== {name}.AFS @ {base} head {head[:4]!r} '
                  f'count {struct.unpack("<I", head[4:])[0] if head[:4] == b"AFS\\x00" else "n/a"}')
            count = struct.unpack('<I', head[4:])[0]
            for index in range(min(6, count)):
                f.seek(base + 8 + index * 8)
                off, length = struct.unpack('<II', f.read(8))
                f.seek(base + off)
                blob = f.read(min(64, length))
                print(f'  entry {index}: off {off} len {length} head {blob[:24].hex(" ")} '
                      f'ascii {blob[:12]!r}')
            if name == 'VOICE':
                for index in (100, 500, 1000, 2000):
                    if index >= count:
                        continue
                    f.seek(base + 8 + index * 8)
                    off, length = struct.unpack('<II', f.read(8))
                    f.seek(base + off)
                    blob = f.read(48)
                    print(f'  entry {index}: len {length} head {blob[:24].hex(" ")}')
            # entry size histogram
            sizes = []
            for index in range(count):
                f.seek(base + 8 + index * 8)
                off, length = struct.unpack('<II', f.read(8))
                sizes.append(length)
            print(f'  entries {count} total {sum(sizes)} min {min(sizes)} max {max(sizes)}')
            print(f'  first 12 sizes {sizes[:12]}')


if __name__ == '__main__':
    main()
