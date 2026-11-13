#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断工具：列出 v7 汉化 ELF 里所有被 NUL 截断、运行时显示不全的记录。

对照原版 ELF，逐条打印「日文原文 / 现状（实际只会显示到第一个 NUL）/ 修复后」，
并且把控制符骨架（%N %n %S 0x8753）与原始不一致、需要人工看的记录单独列出。

用法
----
  python 分析截断消息.py --原盘 game-original.iso --elf 打盘/SLPM_665.70-patched.elf
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ELF_LBA = 823692
ELF_SIZE = 1514848

TOKEN = re.compile(rb'%[NnSs]|\x87\x53')


def read_original_elf(iso: Path) -> bytes:
    with iso.open('rb') as f:
        f.seek(ELF_LBA * 2048)
        return f.read(ELF_SIZE)


def records(data: bytes):
    i, n = 0, len(data)
    while i < n:
        if data[i] == 0:
            i += 1
            continue
        j = data.find(b'\x00', i)
        if j < 0:
            j = n
        yield i, j
        i = j + 1


def render(b: bytes) -> str:
    """把游戏内码粗略转成可读文本：能按 Shift-JIS 解码就解码，其余十六进制标出。"""
    out, buf = [], bytearray()

    def flush():
        if not buf:
            return
        try:
            out.append(buf.decode('shift_jis'))
        except UnicodeDecodeError:
            out.append(buf.hex(' '))
        buf.clear()

    i = 0
    while i < len(b):
        if 0x81 <= b[i] <= 0x9f or 0xe0 <= b[i] <= 0xfc:
            buf += b[i:i + 2]
            i += 2
        elif b[i] < 0x20:
            flush()
            out.append(f'<{b[i]:02x}>')
            i += 1
        elif b[i] < 0x80:
            buf.append(b[i])
            i += 1
        else:
            flush()
            out.append(f'[{b[i]:02x}]')
            i += 1
    flush()
    return ''.join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description='列出被 NUL 截断的汉化文本记录')
    ap.add_argument('--原盘', dest='iso', required=True, type=Path)
    ap.add_argument('--elf', dest='elf', required=True, type=Path)
    args = ap.parse_args()

    original = read_original_elf(args.iso)
    patched = args.elf.read_bytes()

    good, odd = [], []
    for i, j in records(original):
        old = original[i:j]
        cur = patched[i:j]
        if len(cur) != len(old):
            continue
        core = cur.rstrip(b'\x00')
        if b'\x00' not in core:
            continue
        merged = cur.replace(b'\x00', b'')
        (good if TOKEN.findall(old) == TOKEN.findall(merged) else odd).append((i, j, old, cur, merged))

    print(f'被 NUL 截断：{len(good) + len(odd)} 条'
          f'（控制符骨架一致、可安全修复 {len(good)} 条；需人工确认 {len(odd)} 条）')
    print('=' * 100)
    for i, j, old, cur, merged in good + odd:
        flag = '' if (i, j, old, cur, merged) in good else '   <<< 控制符骨架与原文不一致，需人工确认'
        print(f'@{hex(i)} 长度 {j - i}{flag}')
        print(f'   日文原文: {render(old)}')
        print(f'   现状显示: {render(cur[:cur.find(bytes([0]))])}   （NUL 之后的都不显示）')
        print(f'   修复之后: {render(merged)}')
        print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
