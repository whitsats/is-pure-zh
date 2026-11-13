#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 v7 汉化 ELF 的「NUL 截断」缺陷（v7.1）。

问题
----
v7 的文本替换工具写中文时，把每一行都按**原始日文行的字节长度补 0x00**，
于是同一个字符串记录里出现了内部 NUL。游戏的文本解释器按 NUL 结尾处理，
读到第一个 NUL 就停，实际后果：

  * 多行提示只显示第一行（存档/记忆卡/免责声明等）；
  * 所有「是／否」确认框只显示问句，选项整行不出现；
  * 复制／粘贴／删除／写入 这类多项目菜单只显示第一项。
  v7 的 ELF 里共 116 条记录受影响。

修复
----
以**原版 ELF**为基准，把每一条 NUL 分隔的记录取出来：
若汉化后的同一区间内部出现 NUL（NUL 之后还有内容），
就去掉该区间里所有 NUL 后重新写回，尾部补 0 保持记录总长度不变。
`%N`/`%n`/`%S`/`0x8753` 等控制符的位置与原始日文完全一致，
所以渲染出来的行数与选项位置也与日版一致。

用法
----
  python 修复截断消息.py --原盘 game-original.iso \\
        --v7elf 打盘/SLPM_665.70-patched.elf \\
        --输出 打盘/SLPM_665.70-fixed.elf

原版 ELF 直接从原盘 ISO 里读，不需要另外准备文件。
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

# 原盘中 SLPM_665.70 的位置（扇区号 × 2048）
ELF_LBA = 823692
ELF_SIZE = 1514848


def read_original_elf(iso: Path) -> bytes:
    with iso.open('rb') as f:
        f.seek(ELF_LBA * 2048)
        data = f.read(ELF_SIZE)
    if len(data) != ELF_SIZE:
        sys.exit(f'原盘里读不到完整的 SLPM_665.70（只读到 {len(data)} 字节），请确认是原版 ISO。')
    return data


def iter_records(data: bytes):
    """按 NUL 切出记录区间 [i, j)。"""
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


def repair(original: bytes, patched: bytearray) -> list[tuple[int, int, bytes, bytes]]:
    """就地修复，返回 (偏移, 结束, 修复前, 修复后) 列表。"""
    fixed = []
    for i, j in iter_records(original):
        old = original[i:j]
        cur = bytes(patched[i:j])
        core = cur.rstrip(b'\x00')
        if b'\x00' not in core or cur == old:
            continue
        merged = cur.replace(b'\x00', b'')
        if len(merged) > len(cur):
            continue
        patched[i:j] = merged + b'\x00' * (len(cur) - len(merged))
        fixed.append((i, j, cur, merged))
    return fixed


def main() -> int:
    ap = argparse.ArgumentParser(description='修复 v7 汉化 ELF 里被 NUL 截断的文本记录')
    ap.add_argument('--原盘', dest='iso', required=True, type=Path, help='原版 ISO（用于取原版 ELF 做基准）')
    ap.add_argument('--v7elf', dest='elf', required=True, type=Path, help='v7 的 SLPM_665.70-patched.elf')
    ap.add_argument('--输出', dest='out', required=True, type=Path, help='输出的修复后 ELF')
    args = ap.parse_args()

    original = read_original_elf(args.iso)
    patched = bytearray(args.elf.read_bytes())
    if len(patched) != ELF_SIZE:
        sys.exit(f'{args.elf} 大小异常：{len(patched)}（应为 {ELF_SIZE}）')

    fixed = repair(original, patched)

    # 复核：不应再有任何内部 NUL
    left = sum(1 for i, j in iter_records(original)
               if b'\x00' in bytes(patched[i:j]).rstrip(b'\x00'))
    if left:
        sys.exit(f'仍有 {left} 条记录未修复，已中止。')

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(bytes(patched))
    print(f'修复 {len(fixed)} 条记录 -> {args.out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
