from pathlib import Path
import struct
from extract_bg import unpack

root = Path(__file__).resolve().parent
with (root.parent/'game-v5.iso').open('rb') as f:
    base = 393924608
    for i in range(8):
        f.seek(base+8+i*8)
        off, length = struct.unpack('<II',f.read(8))
        f.seek(base+off)
        raw = unpack(f.read(length))
        path = root/'提取测试'/f'MAC_{i:03}.bin'
        path.write_bytes(raw)
        print(i, len(raw), raw[:64].hex(' '))
