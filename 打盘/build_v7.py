#!/usr/bin/env python3
"""Build game-v7.iso from game-original.iso in one step.
Replaces ETC.AFS / MAC.AFS / INIT.BIN / SLPM_665.70 (ELF).
- ETC.AFS / MAC.AFS are AFS archives: the reader uses the AFS header, so trailing
  zero padding up to the allocated size is harmless; the ISO directory size is left
  at the original value.
- INIT.BIN is a raw LZSS blob: the decompressor reads the whole file, so trailing
  zero padding would be misread as stream data. For INIT.BIN we therefore update
  the ISO9660 directory record to the exact new size instead of padding.
- SLPM_665.70 (ELF) is exactly the same length as the original (1,514,848 bytes):
  in-place replacement works and the ISO9660 directory size field is unchanged.
Usage (in 打盘/):
  python3 build_v7.py etc-v6.afs mac-v6.afs init-v5-lazy.bin SLPM_665.70-patched.elf game-v7.iso
  打完 md5 应为 49dd66a1980d4f81aea51069d35299df
  (Windows: certutil -hashfile game-v7.iso MD5)
"""
import hashlib, os, shutil, struct, sys

BASE = os.path.expanduser('~/workspace/is-pure')
SLOTS = {
    'ETC.AFS':  (159082, 17889280),
    'MAC.AFS':  (192346, 1081344),
    'INIT.BIN': (823103, 23601),
    'SLPM_665.70': (823692, 1514848),
}
# Files whose ISO directory size must be updated to the exact new size.
DIR_SIZE_FILES = {'INIT.BIN'}

def md5(b):
    return hashlib.md5(b).hexdigest()

def update_dir_size(iso_data, root_lba, root_size, filename, new_size):
    """Find filename's record in the root directory and set its size (LE+BE)."""
    base = root_lba * 2048
    i = 0
    while i < root_size:
        ln = iso_data[base + i]
        if ln == 0:
            break
        rec = iso_data[base+i: base+i+ln]
        name_len = rec[32]
        name = rec[33:33+name_len]
        if name.split(b';')[0] == filename.encode():
            # size LE at +10, size BE at +14
            struct.pack_into('<I', iso_data, base+i+10, new_size)
            struct.pack_into('>I', iso_data, base+i+14, new_size)
            return True
        i += ln
    return False

def main():
    etc_path, mac_path, init_path, elf_path = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    out_path = sys.argv[5] if len(sys.argv) > 5 else os.path.join(BASE, 'game-v7.iso')
    src_iso = os.path.join(BASE, 'game-original.iso')
    new_files = {
        'ETC.AFS': open(etc_path, 'rb').read(),
        'MAC.AFS': open(mac_path, 'rb').read(),
        'INIT.BIN': open(init_path, 'rb').read(),
        'SLPM_665.70': open(elf_path, 'rb').read(),
    }
    for name, data in new_files.items():
        lba, alloc = SLOTS[name]
        assert len(data) <= alloc, f'{name}: {len(data)} exceeds allocated {alloc}'
        print(f'{name}: new {len(data)} bytes, allocated {alloc}')
    shutil.copyfile(src_iso, out_path)
    with open(out_path, 'r+b') as f:
        for name, data in new_files.items():
            lba, alloc = SLOTS[name]
            f.seek(lba * 2048)
            f.write(data)
            if name not in DIR_SIZE_FILES and len(data) < alloc:
                f.write(b'\x00' * (alloc - len(data)))
        # update ISO directory sizes for DIR_SIZE_FILES
        f.seek(16 * 2048)
        pvd = f.read(2048)
        root = pvd[156:156+34]
        root_lba = struct.unpack('<I', root[2:6])[0]
        root_sz = struct.unpack('<I', root[10:14])[0]
        f.seek(root_lba * 2048)
        root_data = bytearray(f.read(root_sz))
        for name in DIR_SIZE_FILES:
            ok = update_dir_size(root_data, 0, root_sz, name, len(new_files[name]))
            print(f'directory size update {name} -> {len(new_files[name])}: {"ok" if ok else "NOT FOUND"}')
            assert ok, f'directory record for {name} not found'
        f.seek(root_lba * 2048)
        f.write(bytes(root_data))
    size = os.path.getsize(out_path)
    print(f'wrote {out_path}: {size} bytes, md5={md5(open(out_path, "rb").read())}')

if __name__ == '__main__':
    main()
