from pathlib import Path
import struct
from extract_bg import unpack

root = Path(__file__).resolve().parent
needle = 'ちゃんは高校の演劇部に所属している'.encode('shift_jis')
with (root.parent/'game-original.iso').open('rb') as f:
    base = 393924608
    for i in range(74):
        f.seek(base+8+i*8)
        off, size = struct.unpack('<II',f.read(8))
        f.seek(base+off)
        data = unpack(f.read(size))
        at = data.find(needle)
        if at >= 0:
            print(f'MAC {i} text at 0x{at:x}, bytes:',data[at-8:at+len(needle)+8].hex(' '))
