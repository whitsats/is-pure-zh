#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把重新生成的字库打进 ETC.AFS（v7.1）。

ETC.AFS 是个带偏移表的归档：表头 4 字节魔数、4 字节条目数，
随后是条目表（每条 8 字节：偏移、长度），表后面还有一段以 48 字节为一条的
元数据（文件名在元数据 +0，实际压缩长度在 +44）。FONT00.FOP 是第 4 号条目。

新字库压缩后比 v7 略小，脚本按 2048 字节对齐重新分配空间、把后面的条目整体
前移或后移（shift），并同步修正条目表与元数据。

用法
----
  python 替换字库.py --afs etc-v6.afs --lzss FONT00-粗圆.lzss --输出 etc-v6-粗圆.afs
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys

FONT_ENTRY = 4              # FONT00.FOP 在 ETC.AFS 里的条目号
ETC_ALLOCATION = 17889280   # 打进 ISO 时 ETC.AFS 的槽位大小


def patch_afs(src: bytes, blob: bytes) -> bytes:
    count = struct.unpack_from('<I', src, 4)[0]
    meta, metalen = struct.unpack_from('<II', src, 8 + count * 8)
    off, _oldlen = struct.unpack_from('<II', src, 8 + FONT_ENTRY * 8)
    nextoff = struct.unpack_from('<I', src, 8 + (FONT_ENTRY + 1) * 8)[0]

    name = src[meta + FONT_ENTRY * 48:meta + FONT_ENTRY * 48 + 32].split(b'\0')[0]
    if name != b'FONT00.FOP':
        sys.exit(f'第 {FONT_ENTRY} 号条目不是 FONT00.FOP，而是 {name!r}，请确认输入的是 ETC.AFS。')

    newalloc = (len(blob) + 2047) // 2048 * 2048
    shift = newalloc - (nextoff - off)

    out = bytearray(src[:off] + blob + bytes(newalloc - len(blob)) + src[nextoff:])
    for i in range(count):
        oldoff, size = struct.unpack_from('<II', src, 8 + i * 8)
        if i == FONT_ENTRY:
            struct.pack_into('<II', out, 8 + i * 8, off, len(blob))
        elif oldoff >= nextoff:
            struct.pack_into('<II', out, 8 + i * 8, oldoff + shift, size)
    struct.pack_into('<II', out, 8 + count * 8, meta + shift, metalen)
    struct.pack_into('<I', out, meta + shift + FONT_ENTRY * 48 + 44, len(blob))

    if len(out) > ETC_ALLOCATION:
        sys.exit(f'新的 ETC.AFS 有 {len(out)} 字节，超过 ISO 槽位 {ETC_ALLOCATION} 字节。')
    print(f'ETC.AFS：字库 {len(blob)} 字节，占用 {newalloc}，后续条目位移 {shift}，'
          f'新大小 {len(out)} / {ETC_ALLOCATION}')
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description='把新字库打进 ETC.AFS')
    ap.add_argument('--afs', dest='afs', required=True, type=Path, help='v7 的 etc-v6.afs')
    ap.add_argument('--lzss', dest='lzss', required=True, type=Path, help='FONT00-粗圆.lzss')
    ap.add_argument('--输出', dest='out', required=True, type=Path)
    args = ap.parse_args()

    out = patch_afs(args.afs.read_bytes(), args.lzss.read_bytes())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(out)
    print('已写出', args.out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
