from pathlib import Path
import struct

root = Path(__file__).resolve().parent
with (root.parent / 'game-v5.iso').open('rb') as f:
    base = 636928
    f.seek(base + 8 + 8)
    offset, length = struct.unpack('<II', f.read(8))
    f.seek(base + offset)
    blob = f.read(length)

size = int.from_bytes(blob[:4], 'little')
ring = bytearray(4096)
at = 0xfee
src = 4
out = bytearray()
while src < len(blob) and len(out) < size:
    flag = blob[src]
    src += 1
    for _ in range(8):
        if src >= len(blob) or len(out) >= size:
            break
        if flag & 1:
            b = blob[src]; src += 1
            out.append(b); ring[at] = b; at = (at + 1) & 4095
        else:
            a, b = blob[src:src+2]; src += 2
            pos = a | ((b & 0xf0) << 4)
            for j in range((b & 15) + 3):
                v = ring[(pos+j) & 4095]
                out.append(v); ring[at] = v; at = (at + 1) & 4095
        flag >>= 1
print('expected',size,'actual',len(out),'consumed',src,'of',len(blob),'head',out[:64].hex(' '))
(root/'BG_001_probe.bin').write_bytes(out)
