#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新生成汉化字库（v7.1 字库修复）。

本脚本解决 v7 字库的两个显示问题：

1. **旧字形残影／发糊**
   FONT00.FOP 里每个字占 24×24 像素、4 位深，但游戏给每个字只用**两位**
   （plane 0 用 bit0-1，plane 1 用 bit2-3）。v7 的替换脚本写新字形前只用
   `15 ^ bit` 清掉自己那一位，另一位上残留的原版字形没被清掉，于是新旧字形
   叠在一起 —— 表现为章节标题、菜单里未汉化的全角英文与数字重影发糊。
   本脚本改成两位一起清（plane 0 用掩码 0b0011，plane 1 用 0b1100），
   再以亮度 1 写入，与原版观感一致。

2. **标点过大**
   v7 保留了原版约 24 像素满格的标点，比 20 像素的正文大一圈。
   本脚本把剧情里实际用到的全角标点改用 18 像素，与正文风格、大小统一。
   标点定位不能用 Pillow 的 `textbbox`（CJK 下返回的是前进宽度，会把
   、「」这类窄标点摆偏），改为渲染后取真实墨迹包围盒来摆放。

用法
----
  python 制作粗圆修复字库.py --字库源 FONT00-v6.FOP.bin \\
        --字体 "方正粗圆_GBK.ttf" --输出目录 out

字体需自备（例如方正粗圆_GBK.ttf），仓库不附带字体文件。
输出：FONT00-粗圆.FOP.bin（解压态）、FONT00-粗圆.lzss（可直接打进 ETC.AFS）、
      字符替换清单.json（每个字用了哪个字形、落在哪个 slot）。
加 --preview 只生成 _修复预览.png（原字形 vs 新字形对照），不压缩。
"""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
from pathlib import Path
import struct
import sys
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

CHINESE_PX = 20
LATIN_PX = 18
PUNCT_PX = 18

PUNCT = set('。、，．・：；？！「」『』（）〔〕［］｛｝〈〉【】～〜ー—‐…‥“”‘’＋－×÷＝％＃＆＊＠☆★○●◎◇■□▲△▼▽※→←↑↓／＼')
# 少数标点在 GBK 字体的码位上与源文本不完全一致，退回等价的写法
FALLBACK = {'〜': '～', '−': '－', '‐': '－', '‥': '…', 'ʼ': "'"}
FULLWIDTH = '０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ'


# --------------------------------------------------------------------------- #
# LZSS（游戏自己的变体：0xfee 起始的 4096 字节环，匹配长度 3–18）
# --------------------------------------------------------------------------- #
def compress_lzss(data: bytes) -> bytes:
    out = bytearray(struct.pack('<I', len(data)))
    positions = defaultdict(deque)
    i, n = 0, len(data)
    while i < n:
        flagpos = len(out)
        out.append(0)
        flag = 0
        for bit in range(8):
            if i >= n:
                break
            best, bestpos = 0, 0
            if i + 3 <= n:
                key = data[i:i + 3]
                q = positions[key]
                while q and q[0] < i - 4096:
                    q.popleft()
                for j in list(q)[-48:][::-1]:
                    limit = min(18, n - i)
                    length = 3
                    while length < limit and data[j + length] == data[i + length]:
                        length += 1
                    if length > best:
                        best, bestpos = length, j
                        if best == 18:
                            break
            consumed = best if best >= 3 else 1
            if best >= 3:
                ringpos = (0xfee + bestpos) & 4095
                out.extend((ringpos & 255, ((ringpos >> 4) & 0xf0) | (best - 3)))
            else:
                flag |= 1 << bit
                out.append(data[i])
            for j in range(i, i + consumed):
                if j + 3 <= n:
                    positions[data[j:j + 3]].append(j)
            i += consumed
        out[flagpos] = flag
    return bytes(out)


def unpack(blob: bytes) -> bytes:
    """解压（用于自检 roundtrip）。"""
    size = int.from_bytes(blob[:4], 'little')
    ring, at, pos, out = bytearray(4096), 0xfee, 4, bytearray()
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
                a, b = blob[pos:pos + 2]
                pos += 2
                src = a | ((b & 0xf0) << 4)
                for j in range((b & 15) + 3):
                    n = ring[(src + j) & 4095]
                    out.append(n)
                    ring[at] = n
                    at = (at + 1) & 4095
            flag >>= 1
    if len(out) != size:
        raise ValueError(f'LZSS 解压长度不符：期望 {size}，得到 {len(out)}')
    return bytes(out)


# --------------------------------------------------------------------------- #
def build(source: Path, font_path: Path, outdir: Path, preview: bool) -> None:
    mapping = json.loads((Path(__file__).resolve().parent / '字码频率证据.json').read_text('utf-8'))['mapping']

    font_zh = ImageFont.truetype(str(font_path), CHINESE_PX)
    font_en = ImageFont.truetype(str(font_path), LATIN_PX)
    font_pu = ImageFont.truetype(str(font_path), PUNCT_PX)
    cmap = TTFont(font_path).getBestCmap()

    def resolve(char: str) -> str | None:
        for cand in (char, unicodedata.normalize('NFKC', char), FALLBACK.get(char)):
            if cand and len(cand) == 1 and ord(cand) in cmap:
                return cand
        return None

    data = bytearray(source.read_bytes())
    changes, skipped = [], []

    work = dict(mapping)
    for char in FULLWIDTH:
        code = char.encode('shift_jis').hex()
        work.setdefault(code, [[char, 1]])

    for code, votes in sorted(work.items()):
        char, count = votes[0]
        chinese = '\u4e00' <= char <= '\u9fff'
        latin = char in FULLWIDTH
        punct = char in PUNCT
        if not (chinese or latin or punct):
            skipped.append((code, char, 'kana or unclassified kept as original'))
            continue
        glyph = char if (chinese or punct) else unicodedata.normalize('NFKC', char)
        glyph = resolve(glyph)
        if glyph is None:
            skipped.append((code, char, 'no glyph in font'))
            continue
        if count < 1 or count / sum(v[1] for v in votes) < 0.75:
            skipped.append((code, char, 'low confidence'))
            continue
        lead, trail = bytes.fromhex(code)
        if 0x81 <= lead <= 0x9f:
            row = lead - 0x81
        elif 0xe0 <= lead <= 0xfc:
            row = lead - 0xe0 + 31
        else:
            skipped.append((code, char, 'invalid lead'))
            continue
        if not 0x40 <= trail <= 0xfc or trail == 0x7f:
            skipped.append((code, char, 'invalid trail'))
            continue
        index = row * 188 + (trail - 0x40 - (trail > 0x7f))
        slot, plane = divmod(index, 2)
        if slot >= 4096:
            skipped.append((code, char, 'outside font'))
            continue
        offset = 0x5000 + slot * 288
        chunk = np.frombuffer(bytes(data[offset:offset + 288]), dtype=np.uint8)
        nibbles = np.empty(576, dtype=np.uint8)
        nibbles[0::2] = chunk & 15
        nibbles[1::2] = chunk >> 4
        bit = 1 if plane == 0 else 4
        # 每个字只有两位；两位一起清，旧字形才不会留下来变成重影
        mask = 3 if plane == 0 else 12
        old = (nibbles.reshape(24, 24) & mask) != 0
        ys, xs = np.nonzero(old)
        metric_left, metric_right = data[0x1e + index * 2:0x20 + index * 2]
        if not len(xs) or metric_right < metric_left or metric_right > 24:
            skipped.append((code, char, 'invalid original glyph bounds'))
            continue

        image = Image.new('L', (24, 24), 0)
        font = font_zh if chinese else (font_pu if punct else font_en)
        if punct:
            scratch = Image.new('L', (64, 64), 0)
            ImageDraw.Draw(scratch).text((16, 16), glyph, font=font, fill=255)
            ink = np.asarray(scratch) > 128
            iy, ix = np.nonzero(ink)
            if not len(ix):
                skipped.append((code, char, 'empty glyph'))
                continue
            patchpix = ink[iy.min():iy.max() + 1, ix.min():ix.max() + 1]
            height, width = patchpix.shape
        else:
            draw = ImageDraw.Draw(image)
            box = draw.textbbox((0, 0), glyph, font=font)
            width, height = box[2] - box[0], box[3] - box[1]
            if width <= 0 or height <= 0:
                skipped.append((code, char, 'empty glyph box'))
                continue
        if width > 24 or height > 24:
            skipped.append((code, char, 'glyph larger than cell'))
            continue
        center = (int(xs.min()) + int(xs.max()) + 1) / 2
        left = int(round(max(metric_left, min(center - width / 2, metric_right + 1 - width, 24 - width))))
        bottom = int(ys.max()) + 1
        top = int(max(0, min(24 - height, bottom - height)))
        if punct:
            canvas = np.zeros((24, 24), bool)
            canvas[top:top + height, left:left + width] = patchpix
            pix = canvas.reshape(-1)
        else:
            draw.text((left - box[0], top - box[1]), glyph, font=font, fill=255)
            pix = np.asarray(image).reshape(-1) >= 128
        nibbles = (nibbles & (15 ^ mask)) | (pix.astype(np.uint8) * bit)
        data[offset:offset + 288] = bytes((nibbles[0::2] | (nibbles[1::2] << 4)).tolist())
        changes.append((code, char, slot, plane, count, glyph))

    if preview:
        preview_sheet(source, data, changes, outdir)
        return

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / 'FONT00-粗圆.FOP.bin').write_bytes(data)
    (outdir / '字符替换清单.json').write_text(
        json.dumps({'replaced': changes, 'skipped': skipped}, ensure_ascii=False, indent=2), encoding='utf-8')

    kinds = {'chinese': 0, 'latin': 0, 'punct': 0}
    for _, char, *_ in changes:
        kinds['chinese' if '\u4e00' <= char <= '\u9fff' else ('latin' if char in FULLWIDTH else 'punct')] += 1
    print('替换', len(changes), kinds, '跳过', len(skipped))

    print('压缩中…', flush=True)
    compressed = compress_lzss(bytes(data))
    if unpack(compressed) != bytes(data):
        sys.exit('LZSS 往返校验失败，已中止')
    (outdir / 'FONT00-粗圆.lzss').write_bytes(compressed)
    print('压缩后', len(compressed), '字节，往返校验通过')


def preview_sheet(source: Path, data: bytearray, changes, outdir: Path) -> None:
    pal = np.array([[0, 0, 0], [70, 70, 70], [150, 150, 150], [255, 255, 255]], np.uint8)
    old_data = source.read_bytes()
    pick = [c for c in changes if c[1] in PUNCT or c[1] in FULLWIDTH][:60]
    pick += [c for c in changes if '\u4e00' <= c[1] <= '\u9fff'][:12]
    scale = 6
    rows = []
    for code, char, slot, plane, count, glyph in pick:
        tiles = []
        for blob in (old_data, bytes(data)):
            buf = np.frombuffer(blob[0x5000 + slot * 288:0x5000 + (slot + 1) * 288], np.uint8)
            nib = np.empty(576, np.uint8)
            nib[::2] = buf & 15
            nib[1::2] = buf >> 4
            lv = (nib.reshape(24, 24) >> (plane * 2)) & 3
            tiles.append(Image.fromarray(pal[lv].astype(np.uint8), 'RGB').resize((24 * scale, 24 * scale), Image.NEAREST))
        width = sum(t.width for t in tiles) + 10
        row = Image.new('RGB', (width, tiles[0].height), (0, 0, 255))
        x = 0
        for t in tiles:
            row.paste(t, (x, 0))
            x += t.width + 10
        ImageDraw.Draw(row).text((4, 4), f'{char} {code} p{plane}', fill=(255, 0, 0))
        rows.append(row)
    sheet = Image.new('RGB', (max(r.width for r in rows), sum(r.height + 3 for r in rows)), (0, 0, 255))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 3
    out = outdir / '_修复预览.png'
    sheet.save(out)
    print('预览已写出', out, sheet.size, '左=原字形 右=新字形')


def main() -> int:
    ap = argparse.ArgumentParser(description='生成 v7.1 修复字库（清残留 + 标点缩小）')
    ap.add_argument('--字库源', dest='source', required=True, type=Path,
                    help='v7 的字库源文件 FONT00-v6.FOP.bin（在完整补丁包内）')
    ap.add_argument('--字体', dest='font', required=True, type=Path, help='方正粗圆 TTF，需自备')
    ap.add_argument('--输出目录', dest='out', required=True, type=Path)
    ap.add_argument('--preview', action='store_true', help='只生成预览对照图')
    args = ap.parse_args()
    build(args.source, args.font, args.out, args.preview)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
