#!/usr/bin/env python3
"""Build game-v7.iso from game-v6.iso by replacing SLPM_665.70 (ELF) in place.
- Patched ELF is exactly the same length as the original (1,514,848 bytes),
  so in-place replacement works and the ISO9660 directory size field is unchanged.
- Usage: python3 build_iso_v7.py [base_iso] [patched_elf] [out_iso]
  Defaults: ~/workspace/is-pure/game-v6.iso, build/SLPM_665.70-patched.elf, game-v7.iso
  On the box: python3 build_iso_v7.py ~/ispure/v6/game-v6.iso ~/ispure/v6/SLPM_665.70-patched.elf ~/ispure/v7/game-v7.iso
"""
import hashlib, os, shutil, sys

ELF_LBA = 823692
ELF_SIZE = 1514848

def md5_file(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    base_iso = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/workspace/is-pure/game-v6.iso')
    elf_path = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser('~/workspace/is-pure/build/SLPM_665.70-patched.elf')
    out_path = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser('~/workspace/is-pure/game-v7.iso')
    elf = open(elf_path, 'rb').read()
    assert len(elf) == ELF_SIZE, f'patched ELF size {len(elf)} != {ELF_SIZE}'
    print(f'patched ELF md5: {hashlib.md5(elf).hexdigest()}')
    print(f'base {base_iso} md5: {md5_file(base_iso)}')
    shutil.copyfile(base_iso, out_path)
    with open(out_path, 'r+b') as f:
        f.seek(ELF_LBA * 2048)
        f.write(elf)
    print(f'wrote {out_path}: {os.path.getsize(out_path)} bytes, md5={md5_file(out_path)}')

if __name__ == '__main__':
    main()
