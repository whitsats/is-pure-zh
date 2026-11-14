from pathlib import Path
import struct
import sys
from PIL import Image

root = Path(__file__).resolve().parent
output = root / '提取测试'
output.mkdir(exist_ok=True)

def unpack(blob):
    size = int.from_bytes(blob[:4], 'little')
    if size > 20_000_000: raise ValueError('unexpected size')
    ring, at, pos, out = bytearray(4096), 0xfee, 4, bytearray()
    while pos < len(blob) and len(out) < size:
        flag = blob[pos]; pos += 1
        for _ in range(8):
            if pos >= len(blob) or len(out) >= size: break
            if flag & 1:
                n = blob[pos]; pos += 1
                out.append(n); ring[at] = n; at = (at + 1) & 4095
            else:
                a, b = blob[pos:pos+2]; pos += 2
                src = a | ((b & 0xf0) << 4)
                for j in range((b & 15) + 3):
                    n = ring[(src+j) & 4095]
                    out.append(n); ring[at] = n; at = (at + 1) & 4095
            flag >>= 1
    if len(out) != size: raise ValueError(f'expected {size}, got {len(out)}')
    return out

def main():
  thumbnails = '--thumbnails' in sys.argv
  with (root.parent / 'game-v5.iso').open('rb') as f:
    base = 636928
    for i in range(280 if thumbnails else 20):
        if thumbnails and i % 2 == 0:
            continue
        f.seek(base+8+i*8)
        offset, length = struct.unpack('<II', f.read(8))
        f.seek(base+offset)
        try:
            data = unpack(f.read(length))
            print(i, len(data), data[:16].hex(' '))
            (output / f'BG_{i:03}.bin').write_bytes(data)
            if data[:4] == b'TIM2':
                width, height = struct.unpack_from('<HH',data, 36)
                img_type = data[35]
                header_size = struct.unpack_from('<H',data,28)[0]
                print(' TIM2',width,height,'type',img_type,'header',header_size)
                if img_type == 3 and len(data) >= 16+header_size+width*height*4:
                    im = Image.frombytes('RGBA',(width,height),bytes(data[16+header_size:16+header_size+width*height*4]))
                    im.putalpha(im.getchannel('A').point(lambda a: min(255,a*2)))
                    im.save(output / f'BG_{i:03}.png')
        except Exception as exc:
            print(i, 'FAILED', exc)

if __name__ == '__main__':
    main()
