import struct
import zlib
from pathlib import Path

ISO_PATH = Path('/home/user/ispure/v7/game-v7.iso')
AFS_BASES = {'BG': 636928, 'CHR': 106958848, 'EV': 343689216}


def unpack_lzss(blob: bytes) -> bytearray:
    size = int.from_bytes(blob[:4], 'little')
    ring, at, pos, out = bytearray(4096), 0xFEE, 4, bytearray()
    while pos < len(blob) and len(out) < size:
        flag = blob[pos]
        pos += 1
        for _ in range(8):
            if pos >= len(blob) or len(out) >= size:
                break
            if flag & 1:
                n = blob[pos]
                pos += 1
                out.append(n)
                ring[at] = n
                at = (at + 1) & 4095
            else:
                a, b = blob[pos : pos + 2]
                pos += 2
                src = a | ((b & 0xF0) << 4)
                for j in range((b & 15) + 3):
                    n = ring[(src + j) & 4095]
                    out.append(n)
                    ring[at] = n
                    at = (at + 1) & 4095
            flag >>= 1
    return out


def decode_clean_30(raw: bytes, crop_canvas: bool = True):
    """按 1024px 存储行读取 32x32 块，剥离四周 1px 镜像保护边，以 30x30 核心无缝拼合"""
    cnt = struct.unpack_from('<I', raw, 0)[0]
    ptrs = struct.unpack_from(f'<{cnt}I', raw, 4)
    sec0 = ptrs[0]
    hs = ptrs[-2]  # 0x100 或 0x180

    n_rect, cx, cy, cw, ch, fmt = struct.unpack_from('<IHHHHH', raw, sec0)
    rects = [struct.unpack_from('<BBBBHH', raw, sec0 + 16 + r * 8) for r in range(n_rect)]

    # 网格步长严格为 30 像素
    max_w = max([cw] + [(gx + gw) * 30 for gx, _, gw, _, _, _ in rects])
    max_h = max([ch] + [(gy + gh) * 30 for _, gy, _, gh, _, _ in rects])
    canvas = bytearray(max_w * max_h * 4)

    tile = 0
    for gx, gy, gw, gh, rfmt, end_tile in rects:
        for j in range(gh):
            for i in range(gw):
                # 1024 像素宽虚拟行，每行 32 个 32x32 块
                sy, sx = tile // 32, tile % 32
                for py in range(1, 31):  # 跳过 py=0 和 py=31 保护边
                    dy = (gy + j) * 30 + (py - 1)
                    if dy >= max_h:
                        continue
                    src_row = hs + ((sy * 32 + py) * 1024 + sx * 32) * 4
                    dst_row = (dy * max_w + (gx + i) * 30) * 4
                    for px in range(1, 31):  # 跳过 px=0 和 px=31 保护边
                        sp = src_row + px * 4
                        a8 = min(255, (raw[sp + 3] * 255 + 64) // 128)
                        if a8 > 0:
                            dp = dst_row + (px - 1) * 4
                            canvas[dp] = raw[sp]
                            canvas[dp + 1] = raw[sp + 1]
                            canvas[dp + 2] = raw[sp + 2]
                            canvas[dp + 3] = a8
                tile += 1
        if end_tile > tile:
            tile = end_tile

    if crop_canvas:
        out = bytearray(cw * ch * 4)
        for y in range(ch):
            s_off = ((cy + y) * max_w + cx) * 4
            d_off = y * cw * 4
            out[d_off : d_off + cw * 4] = canvas[s_off : s_off + cw * 4]
        return cw, ch, out
    return max_w, max_h, canvas


def decode_old_32(raw: bytes, crop_canvas: bool = True):
    """旧版 32x32 含保护边拼接（用于对比）"""
    cnt = struct.unpack_from('<I', raw, 0)[0]
    ptrs = struct.unpack_from(f'<{cnt}I', raw, 4)
    sec0 = ptrs[0]
    hs = ptrs[-2]
    n_rect, cx, cy, cw, ch, fmt = struct.unpack_from('<IHHHHH', raw, sec0)
    rects = [struct.unpack_from('<BBBBHH', raw, sec0 + 16 + r * 8) for r in range(n_rect)]
    max_w = max([cw] + [(gx + gw) * 32 for gx, _, gw, _, _, _ in rects])
    max_h = max([ch] + [(gy + gh) * 32 for _, gy, _, gh, _, _ in rects])
    canvas = bytearray(max_w * max_h * 4)
    tile = 0
    for gx, gy, gw, gh, rfmt, end_tile in rects:
        for j in range(gh):
            for i in range(gw):
                sy, sx = tile // 32, tile % 32
                for py in range(32):
                    dy = (gy + j) * 32 + py
                    if dy >= max_h:
                        continue
                    src_row = hs + ((sy * 32 + py) * 1024 + sx * 32) * 4
                    dst_row = (dy * max_w + (gx + i) * 32) * 4
                    for px in range(32):
                        sp = src_row + px * 4
                        a8 = min(255, (raw[sp + 3] * 255 + 64) // 128)
                        if a8 > 0:
                            dp = dst_row + px * 4
                            canvas[dp : dp + 4] = bytes((raw[sp], raw[sp + 1], raw[sp + 2], a8))
                tile += 1
        if end_tile > tile:
            tile = end_tile
    if crop_canvas:
        out = bytearray(cw * ch * 4)
        for y in range(ch):
            s_off = ((cy + y) * max_w + cx) * 4
            d_off = y * cw * 4
            out[d_off : d_off + cw * 4] = canvas[s_off : s_off + cw * 4]
        return cw, ch, out
    return max_w, max_h, canvas


def write_png_rgba(path: Path, w: int, h: int, rgba_bytes: bytearray):
    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw.extend(rgba_bytes[y * stride : (y + 1) * stride])
    comp = zlib.compress(bytes(raw), level=6)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', comp) + chunk(b'IEND', b''))


def scale_nearest_rgba(w: int, h: int, rgba: bytearray, s: int):
    nw, nh = w * s, h * s
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy = y // s
        for x in range(nw):
            sp = (sy * w + (x // s)) * 4
            dp = (y * nw + x) * 4
            out[dp : dp + 4] = rgba[sp : sp + 4]
    return nw, nh, out


if __name__ == '__main__':
    out_dir = Path('/workspace/is-pure-zh/移植验证')
    # Clean up broken files from earlier linear-offset test if present
    for broken in out_dir.glob('*_去重排边修复*.png'):
        broken.unlink(missing_ok=True)

    with ISO_PATH.open('rb') as f:
        for tag, base, indices in [
            ('CHR', AFS_BASES['CHR'], [2792, 2840, 0, 6, 634, 1272]),
            ('BG', AFS_BASES['BG'], [12, 14]),
            ('EV', AFS_BASES['EV'], [0]),
        ]:
            for idx in indices:
                f.seek(base + 8 + idx * 8)
                off, ln = struct.unpack('<II', f.read(8))
                f.seek(base + off)
                raw = unpack_lzss(f.read(ln))
                w, h, rgba = decode_clean_30(raw, crop_canvas=True)
                out_file = out_dir / f'{tag}_{idx:04d}_完美无接缝_{w}x{h}.png'
                write_png_rgba(out_file, w, h, rgba)
                print(f'Saved: {out_file} ({w}x{h})')

        # Build 4x zoomed side-by-side comparison for CHR 2792 (Old 32x32 vs Fixed 30x30)
        f.seek(AFS_BASES['CHR'] + 8 + 2792 * 8)
        off, ln = struct.unpack('<II', f.read(8))
        f.seek(AFS_BASES['CHR'] + off)
        raw2792 = unpack_lzss(f.read(ln))

        ow, oh, orgba = decode_old_32(raw2792, crop_canvas=True)
        nw, nh, nrgba = decode_clean_30(raw2792, crop_canvas=True)

        ow4, oh4, o4 = scale_nearest_rgba(ow, oh, orgba, 4)
        nw4, nh4, n4 = scale_nearest_rgba(nw, nh, nrgba, 4)

        CW, CH = ow4 + nw4 + 60, max(oh4, nh4) + 40
        board = bytearray([30, 34, 42, 255] * (CW * CH))

        def blit(src, sw, sh, ox, oy):
            for y in range(sh):
                for x in range(sw):
                    sp = (y * sw + x) * 4
                    a = src[sp + 3] / 255.0
                    dp = ((oy + y) * CW + (ox + x)) * 4
                    board[dp] = int(src[sp] * a + 255 * (1 - a))
                    board[dp + 1] = int(src[sp + 1] * a + 255 * (1 - a))
                    board[dp + 2] = int(src[sp + 2] * a + 255 * (1 - a))
                    board[dp + 3] = 255

        blit(o4, ow4, oh4, 20, 20)
        blit(n4, nw4, nh4, ow4 + 40, 20)
        cmp_file = out_dir / '修复前后终极对照_2792_去保护边.png'
        write_png_rgba(cmp_file, CW, CH, board)
        print(f'Saved comparison: {cmp_file} ({CW}x{CH})')
