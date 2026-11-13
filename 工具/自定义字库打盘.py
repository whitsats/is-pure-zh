#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义字库打盘：把任意 TTF/OTF 字体做成游戏字库，打进已经汉化好的盘里。

它做四件事：

1. 从输入的 ISO 里按固定 LBA 取出 ETC.AFS，解析出第 4 号条目 FONT00.FOP
   （LZSS 压缩态），解压得到「解压态字库」。这份字库同时充当**槽位与字距的基准**：
   哪个字码占哪个槽、每个槽的左右边界（0x1e + index*2 处的两张表）都沿用盘上的原样，
   所以换字体不会让字的位置整体跑掉。
2. 用给定字体重新渲染汉化用到的 2508 个字码，规则与 `修复/字库/制作粗圆修复字库.py`
   完全一致（同一位脚本，本工具直接调用它，不复制逻辑）：
     · 旧字形残留两位一起清（修重影/发虚）
     · 标点与全角拉丁用较小字号（修标点过大）
     · 三类字一律画在字体自身的自然基线上（修纵向落位，例如「一」被抬高）
3. 把新字库 LZSS 压缩后替换回 ETC.AFS，按 2048 字节对齐重新分配空间，
   同步修正条目表与元数据。
4. 把 ETC.AFS 写回 ISO 的固定槽位（LBA 159082，槽位 17889280 字节），
   其余扇区原样照抄，最后回读校验。

用法
----
  # 换字体（输入一张已经打好汉化的盘，例如 game-v7.1.iso）
  python 自定义字库打盘.py --盘 game-v7.1.iso --字体 "方正粗圆_GBK.ttf" --输出 out.iso

  # 直接用一个现成的字库文件（.lzss 压缩态，或 1200128 字节的解压态 .FOP.bin）
  python 自定义字库打盘.py --盘 game-v7.1.iso --字库 FONT00-粗圆.lzss --输出 out.iso

  # 只看效果不出盘
  python 自定义字库打盘.py --盘 game-v7.1.iso --字体 FZ.ttf --预览

  # 不带参数启动图形界面
  python 自定义字库打盘.py

注意：本工具只换字库，不改剧情文本。输入盘必须是**已经汉化过**的盘；
拿原版日文盘来换字库没有意义（日文正文会用到被我们覆写的槽位）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import queue
import shutil
import struct
import sys
import tempfile
import threading
from pathlib import Path

ETC_LBA = 159082            # ETC.AFS 在 ISO 里的起始 LBA
ETC_ALLOCATION = 17889280   # ETC.AFS 的槽位大小
FONT_ENTRY = 4              # FONT00.FOP 在 ETC.AFS 里的条目号
FONT_RAW_SIZE = 1200128     # FONT00 解压态大小
AFS_MAGIC = b'AFS\0'
CHUNK = 4 * 1024 * 1024

# 预览用的样张（都取自游戏里真实出现过的句子，故意包含「一」和各类标点）
SAMPLES = [
    '「不好意思，咖啡厅的那是不可能的事。可别当真啊」',
    '伊织在我静静地一句断喝后停下了脚步。',
    '因为家离得很近所以经常一起玩耍，但看到季子这样的表情却是第一次',
    '一贵',
]


class ToolError(Exception):
    """能直接讲给用户听的错误。"""


# --------------------------------------------------------------------------- #
# 定位仓库 / 载入共用的字库生成器
# --------------------------------------------------------------------------- #
def repo_root() -> Path:
    """找到仓库根（含 修复/字库/制作粗圆修复字库.py 的那一层）。"""
    here = Path(__file__).resolve().parent
    cands = []
    if getattr(sys, '_MEIPASS', None):
        cands.append(Path(sys._MEIPASS))
    cands += [here.parent, here, Path.cwd(), here.parent.parent]
    for c in cands:
        if (c / '修复' / '字库' / '制作粗圆修复字库.py').is_file():
            return c
    raise ToolError('找不到 修复/字库/制作粗圆修复字库.py。\n'
                    '请把本工具放在仓库里运行（例如 <仓库>/工具/自定义字库打盘.py）。')


def load_generator(root: Path | None = None):
    """把字库生成器当模块载入，保证生成规则只有一份。"""
    root = root or repo_root()
    path = root / '修复' / '字库' / '制作粗圆修复字库.py'
    spec = importlib.util.spec_from_file_location('_is_fontgen', path)
    if spec is None or spec.loader is None:
        raise ToolError(f'无法载入字库生成器：{path}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# AFS / ISO
# --------------------------------------------------------------------------- #
def afs_span(blob: bytes) -> int:
    """ETC.AFS 的真实长度：条目数据与元数据表的末端，向上对齐到 2048。

    实测这个算法给出的长度与仓库里 etc-v6.afs(17729536)、
    现 v7.1 用的 etc-v6-粗圆.afs(17737728) 完全一致。
    """
    if len(blob) < 16:
        raise ToolError('ETC.AFS 太小，无法解析。')
    count = struct.unpack_from('<I', blob, 4)[0]
    if count <= 0 or count > 100000:
        raise ToolError(f'ETC.AFS 条目数异常：{count}')
    meta, metalen = struct.unpack_from('<II', blob, 8 + count * 8)
    end = meta + metalen
    for i in range(count):
        off, size = struct.unpack_from('<II', blob, 8 + i * 8)
        end = max(end, off + size)
    return (end + 2047) // 2048 * 2048


def read_disc_afs(disc: Path) -> bytes:
    """从 ISO 里取出 ETC.AFS（按真实长度截断）。"""
    size = disc.stat().st_size
    if size < (ETC_LBA + 1) * 2048:
        raise ToolError('这个镜像太小，不像 PS2 光盘镜像。')
    with disc.open('rb') as f:
        f.seek(ETC_LBA * 2048)
        blob = f.read(ETC_ALLOCATION)
    if len(blob) < ETC_ALLOCATION:
        raise ToolError('读 ETC.AFS 时提前遇到文件末尾。')
    if blob[:4] != AFS_MAGIC:
        raise ToolError(f'在 LBA {ETC_LBA} 处没找到 AFS 归档（魔数 {blob[:4]!r}）。\n'
                        '请确认选的是 I’s Pure（SLPM-66570）的镜像。')
    span = afs_span(blob)
    return blob[:span]


def font_lzss_in_afs(afs: bytes) -> bytes:
    count = struct.unpack_from('<I', afs, 4)[0]
    meta, _ = struct.unpack_from('<II', afs, 8 + count * 8)
    name = afs[meta + FONT_ENTRY * 48:meta + FONT_ENTRY * 48 + 32].split(b'\0')[0]
    if name != b'FONT00.FOP':
        raise ToolError(f'ETC.AFS 第 {FONT_ENTRY} 号条目是 {name!r}，不是 FONT00.FOP。')
    off, size = struct.unpack_from('<II', afs, 8 + FONT_ENTRY * 8)
    return afs[off:off + size]


# --------------------------------------------------------------------------- #
# 生成新字库
# --------------------------------------------------------------------------- #
def render_font(gen, source_raw: bytes, font_path: Path, workdir: Path,
                zh_px: int, latin_px: int, punct_px: int, progress) -> tuple[bytes, dict]:
    """调用共用的生成器，产出 (lzss 压缩字库, 报告)。"""
    gen.CHINESE_PX, gen.LATIN_PX, gen.PUNCT_PX = zh_px, latin_px, punct_px
    src = workdir / 'FONT00-字库源.FOP.bin'
    src.write_bytes(source_raw)
    out = workdir / '新字库'
    out.mkdir(exist_ok=True)
    progress('正在用自定义字体渲染字形…', 20)
    gen.build(src, Path(font_path), out, False)
    lzss = (out / 'FONT00-粗圆.lzss').read_bytes()
    raw = (out / 'FONT00-粗圆.FOP.bin').read_bytes()
    report = json.loads((out / '字符替换清单.json').read_text('utf-8'))
    report['_lzss'] = lzss
    report['_raw'] = raw
    return lzss, report


def load_font_blob(path: Path, gen) -> tuple[bytes, bytes]:
    """接受现成字库：解压态（1200128 字节）或 LZSS 压缩态。返回 (lzss, raw)。"""
    data = path.read_bytes()
    if len(data) == FONT_RAW_SIZE:
        raw = data
        lzss = gen.compress_lzss(raw)
        if gen.unpack(lzss) != raw:
            raise ToolError('字库压缩往返校验失败。')
        return lzss, raw
    if len(data) < 8:
        raise ToolError('这个字库文件太小了。')
    want = struct.unpack_from('<I', data, 0)[0]
    if want != FONT_RAW_SIZE:
        raise ToolError(f'这个文件既不是 {FONT_RAW_SIZE} 字节的解压态字库，'
                        f'也不是 FONT00 的 LZSS 压缩态（头部期望长度 {want}）。')
    raw = gen.unpack(data)
    return data, raw


# --------------------------------------------------------------------------- #
# 打包与写盘
# --------------------------------------------------------------------------- #
def build_afs(afs: bytes, lzss: bytes, gen) -> bytes:
    """把新字库打进 ETC.AFS（复用 修复/字库/替换字库.py 的实现）。"""
    root = repo_root()
    path = root / '修复' / '字库' / '替换字库.py'
    spec = importlib.util.spec_from_file_location('_is_afs', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    try:
        return mod.patch_afs(afs, lzss)
    except SystemExit as exc:                      # 替换字库.py 用 sys.exit 报错
        raise ToolError(str(exc)) from None


def write_iso(disc: Path, out: Path, afs: bytes, progress) -> None:
    """把输入镜像原样抄一份，只把 ETC.AFS 槽位换成新的。"""
    if len(afs) > ETC_ALLOCATION:
        raise ToolError(f'新的 ETC.AFS 有 {len(afs)} 字节，超过槽位 {ETC_ALLOCATION}。')
    at = ETC_LBA * 2048
    total = disc.stat().st_size
    if out.exists():
        out.unlink()
    with disc.open('rb') as src, out.open('wb') as dst:
        done = 0
        while done < at:
            chunk = src.read(min(CHUNK, at - done))
            if not chunk:
                raise ToolError('读输入镜像时提前遇到文件末尾。')
            dst.write(chunk)
            done += len(chunk)
            progress('正在写入新镜像…', 55 + 30 * done / max(total, 1))
        dst.write(afs)
        dst.write(bytes(ETC_ALLOCATION - len(afs)))
        src.seek(at + ETC_ALLOCATION)
        done = at + ETC_ALLOCATION
        while True:
            chunk = src.read(CHUNK)
            if not chunk:
                break
            dst.write(chunk)
            done += len(chunk)
            progress('正在写入新镜像…', 55 + 30 * done / max(total, 1))
    if out.stat().st_size != total:
        raise ToolError('输出镜像大小与输入不一致。')


def verify_output(out: Path, expect_raw: bytes, progress) -> None:
    progress('正在回读校验…', 88)
    afs = read_disc_afs(out)
    gen = load_generator()
    blob = font_lzss_in_afs(afs)
    if gen.unpack(blob) != expect_raw:
        raise ToolError('回读校验失败：写入的字库与预期不一致。')


def hashes(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(CHUNK):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


# --------------------------------------------------------------------------- #
# 预览图
# --------------------------------------------------------------------------- #
def cell_of(raw: bytes, index: int):
    slot, plane = divmod(index, 2)
    base = 0x5000 + slot * 288
    if base + 288 > len(raw):
        return None
    shift = 0 if plane == 0 else 2
    grid = []
    for y in range(24):
        row = []
        for x in range(24):
            b = raw[base + y * 12 + (x * 4) // 8]
            nib = (b >> ((x % 2) * 4)) & 0b1111
            row.append((nib >> shift) & 0b11)
        grid.append(row)
    return grid


def index_of(lead: int, trail: int) -> int:
    row = lead - 0x81 if lead <= 0x9F else lead - 0xE0 + 31
    return row * 188 + (trail - 0x40 - (1 if trail > 0x7F else 0))


def preview_sheet(old_raw: bytes, new_raw: bytes, mapping: dict,
                  replaced_codes: set | None, dest: Path, title: str) -> Path:
    """按实际生成的字库画预览：每格 24×24，「换之前 / 换之后」上下对照。

    只画**真正会被替换**的字码（replaced_codes）；没被替换的槽位仍然是原版日文
    字形，画出来只会误导。replaced_codes 为 None 时（直接喂现成字库）退回全表。
    """
    from PIL import Image, ImageDraw, ImageFont as PILFont

    scale = 4
    cell = 24 * scale
    pad = 3
    per_row = 24
    label_w = 86
    row_h = 26

    by_char = {}
    for code, v in mapping.items():
        if replaced_codes is not None and code not in replaced_codes:
            continue
        by_char.setdefault(v[0][0], code)

    pool = mapping if replaced_codes is None else {
        c: v for c, v in mapping.items() if c in replaced_codes}
    ranked = sorted(((v[0][0], v[0][1]) for v in pool.values()
                     if '\u4e00' <= v[0][0] <= '\u9fff'), key=lambda t: -t[1])
    chinese = [ch for ch, _ in ranked[:per_row * 5]]
    others = [v[0][0] for v in pool.values() if not ('\u4e00' <= v[0][0] <= '\u9fff')]

    sections = [('常用汉字', chinese), ('标点与全角拉丁', others)]
    sections += [('样张', list(s)) for s in SAMPLES]

    # 版面
    W = 24 + label_w + per_row * (cell + pad) + 16
    y = 76
    plan = []
    for label, chars in sections:
        rows = max(1, (len(chars) + per_row - 1) // per_row)
        plan.append((label, chars, y, rows))
        y += rows * 2 * (cell + pad + row_h) + 26
    H = y + 20
    img = Image.new('RGB', (W, H), (26, 26, 30))
    d = ImageDraw.Draw(img)
    try:
        f_big = PILFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
        f_small = PILFont.truetype('C:/Windows/Fonts/msyh.ttc', 15)
    except Exception:
        f_big = f_small = PILFont.load_default()

    d.text((16, 10), title, fill=(255, 220, 130), font=f_big)
    d.text((16, 38), f'只显示会被替换的 {len(by_char)} 个字码　|　'
                     f'每格 24×24　绿线=第11–12行(原盘「一」的位置)　蓝线=第23行(格子底)　'
                     f'空格子=该槽位未替换',
           fill=(170, 200, 255), font=f_small)

    def strip(x, y, chars, raw, offset):
        for i, ch in enumerate(chars):
            cx = x + (i % per_row) * (cell + pad)
            cy = y + (i // per_row) * (cell + pad + row_h)
            code = by_char.get(ch)
            grid = None
            if code is not None:
                grid = cell_of(raw, index_of(int(code[:2], 16), int(code[2:], 16)))
            for gy in range(24):
                for gx in range(24):
                    xx = cx + gx * scale
                    yy = cy + gy * scale
                    if grid and grid[gy][gx]:
                        col = (255, 255, 255)
                    else:
                        col = (44, 44, 50) if (gx + gy) % 2 == 0 else (37, 37, 43)
                    d.rectangle([xx, yy, xx + scale - 1, yy + scale - 1], fill=col)
            d.line([(cx, cy + 11 * scale), (cx + cell - 1, cy + 11 * scale)], fill=(80, 200, 120))
            d.line([(cx, cy + 23 * scale), (cx + cell - 1, cy + 23 * scale)], fill=(80, 140, 240))

    for label, chars, y0, rows in plan:
        d.text((16, y0), label, fill=(150, 255, 190), font=f_big)
        block = rows * (cell + pad + row_h)
        for k, (tag, raw, colour) in enumerate(
                (('换之前', old_raw, (200, 170, 140)), ('换之后', new_raw, (140, 220, 255)))):
            yy = y0 + 30 + k * block
            d.text((16, yy + cell // 2 - 8), tag, fill=colour, font=f_small)
            strip(24 + label_w, yy, chars, raw, k)

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    return dest


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def summarize(gen, report: dict | None, lzss: bytes, old_lzss_len: int) -> list[str]:
    lines = []
    if report is None:
        lines.append(f'直接使用现成字库：压缩 {old_lzss_len} → {len(lzss)} 字节')
        return lines
    replaced = report.get('replaced', [])
    skipped = report.get('skipped', [])
    kinds = {'chinese': 0, 'latin': 0, 'punct': 0}
    for item in replaced:
        ch = item[1]
        kinds['chinese' if '\u4e00' <= ch <= '\u9fff'
              else ('latin' if ch in gen.FULLWIDTH else 'punct')] += 1
    lines.append(f'替换 {len(replaced)} 个字形：汉字 {kinds["chinese"]}、'
                 f'标点 {kinds["punct"]}、全角拉丁 {kinds["latin"]}')
    reasons: dict[str, list[str]] = {}
    for code, ch, why in skipped:
        reasons.setdefault(why, []).append(ch)
    for why, chars in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        note = {
            'no glyph in font': '★ 这个字体缺少这些字形',
            'glyph larger than cell': '★ 字号太大，字形超出 24×24 格',
            'empty glyph box': '★ 这个字体画不出这些字',
            'kana or unclassified kept as original': '非汉字/标点，保持原样（正常）',
            'low confidence': '字码置信度不足，保持原样（正常）',
            'invalid original glyph bounds': '槽位字距数据异常（正常）',
            'outside font': '字码超出字库范围（正常）',
            'invalid lead': '字码非法（正常）',
            'invalid trail': '字码非法（正常）',
        }.get(why, why)
        head = ''.join(chars[:40])
        more = f' …等 {len(chars)} 个' if len(chars) > 40 else ''
        lines.append(f'      跳过 {len(chars)} 个：{note}  {head}{more}')
    lines.append(f'字库压缩：{old_lzss_len} → {len(lzss)} 字节 '
                 f'（槽位余量 {ETC_ALLOCATION} 字节，够用）')
    return lines


def run(disc: Path, font: Path | None, blob: Path | None, out: Path | None,
        zh_px: int, latin_px: int, punct_px: int, source_font: Path | None,
        preview: Path | None, dump_font: Path | None, progress) -> list[str]:
    disc = Path(disc).resolve(strict=True)
    if not disc.is_file():
        raise ToolError(f'找不到镜像：{disc}')
    if font is not None:
        font = Path(font).resolve(strict=True)
        if not font.is_file():
            raise ToolError(f'找不到字体文件：{font}')
    gen = load_generator()
    mapping = json.loads(
        (repo_root() / '修复' / '字库' / '字码频率证据.json').read_text('utf-8'))['mapping']

    progress('正在读取镜像里的 ETC.AFS…', 5)
    afs = read_disc_afs(disc)
    old_lzss = font_lzss_in_afs(afs)
    base_raw = gen.unpack(old_lzss)
    if len(base_raw) != FONT_RAW_SIZE:
        raise ToolError(f'盘上的字库大小异常：{len(base_raw)}')

    report = None
    with tempfile.TemporaryDirectory(prefix='is-font-') as tmp:
        tmpdir = Path(tmp)
        if blob is not None:
            progress('正在载入现成字库…', 15)
            lzss, raw = load_font_blob(Path(blob).resolve(strict=True), gen)
        else:
            if source_font is not None:
                src_raw = Path(source_font).resolve(strict=True).read_bytes()
                if len(src_raw) != FONT_RAW_SIZE:
                    raise ToolError(f'字库源应是 {FONT_RAW_SIZE} 字节的解压态 FONT00，'
                                    f'实际 {len(src_raw)} 字节。')
            else:
                src_raw = base_raw
            lzss, report = render_font(gen, src_raw, font, tmpdir, zh_px, latin_px,
                                       punct_px, progress)
            raw = report['_raw']

    lines = [f'输入镜像：{disc}',
             f'输入字库：{len(old_lzss)} 字节（压缩态）']
    lines += summarize(gen, report, lzss, len(old_lzss))

    if dump_font is not None:
        dump_font = Path(dump_font)
        dump_font.parent.mkdir(parents=True, exist_ok=True)
        dump_font.write_bytes(lzss)
        lines.append(f'已导出字库：{dump_font}')

    if preview is not None:
        name = font.name if font is not None else Path(blob).name
        title = f'自定义字库预览  ·  {name}  ·  汉字 {zh_px}px'
        replaced = ({item[0] for item in report['replaced']} if report else None)
        dest = preview_sheet(base_raw, raw, mapping, replaced, Path(preview), title)
        lines.append(f'已写出预览图：{dest}')

    if out is None:
        return lines

    progress('正在替换 ETC.AFS 里的字库…', 45)
    new_afs = build_afs(afs, lzss, gen)
    lines.append(f'ETC.AFS：{len(afs)} → {len(new_afs)} 字节 '
                 f'（槽位 {ETC_ALLOCATION}，余量 {ETC_ALLOCATION - len(new_afs)}）')
    out = Path(out)
    if out.resolve() == disc:
        raise ToolError('输出路径不能和输入镜像相同。')
    write_iso(disc, out, new_afs, progress)
    verify_output(out, raw, progress)
    md5, sha = hashes(out)
    lines += [f'已写出镜像：{out}',
              f'  大小   {out.stat().st_size} 字节',
              f'  md5    {md5}',
              f'  sha256 {sha}']
    return lines


# --------------------------------------------------------------------------- #
# 图形界面
# --------------------------------------------------------------------------- #
def gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title('I’s Pure 自定义字库打盘')
    root.resizable(False, False)

    disc_var = tk.StringVar()
    font_var = tk.StringVar()
    blob_var = tk.StringVar()
    out_var = tk.StringVar()
    zh_var = tk.StringVar(value='20')
    pu_var = tk.StringVar(value='18')
    la_var = tk.StringVar(value='18')

    frm = ttk.Frame(root, padding=16)
    frm.pack(fill='both', expand=True)

    def row(r, label, var, browse, hint=''):
        ttk.Label(frm, text=label).grid(row=r, column=0, sticky='w', pady=4)
        ttk.Entry(frm, textvariable=var, width=52).grid(row=r, column=1, sticky='we', pady=4)
        ttk.Button(frm, text='浏览…', command=browse).grid(row=r, column=2, padx=(6, 0))
        if hint:
            ttk.Label(frm, text=hint, foreground='#666').grid(row=r + 1, column=1, sticky='w')

    def pick_disc():
        p = filedialog.askopenfilename(title='选择已经汉化好的 ISO 镜像',
                                       filetypes=[('ISO 镜像', '*.iso'), ('所有文件', '*.*')])
        if p:
            disc_var.set(p)
            if not out_var.get():
                s = Path(p)
                out_var.set(str(s.with_name(s.stem + '-自定义字库.iso')))

    def pick_font():
        p = filedialog.askopenfilename(title='选择字体文件',
                                       filetypes=[('字体', '*.ttf *.otf *.ttc'), ('所有文件', '*.*')])
        if p:
            font_var.set(p)
            blob_var.set('')

    def pick_blob():
        p = filedialog.askopenfilename(title='选择现成字库',
                                       filetypes=[('字库', '*.lzss *.bin *.FOP'),
                                                  ('所有文件', '*.*')])
        if p:
            blob_var.set(p)
            font_var.set('')

    def pick_out():
        p = filedialog.asksaveasfilename(title='输出镜像', defaultextension='.iso',
                                         filetypes=[('ISO 镜像', '*.iso')])
        if p:
            out_var.set(p)

    row(0, '输入镜像', disc_var, pick_disc, '必须是已经汉化过的盘（原版日文盘换字库没有意义）')
    row(2, '自定义字体', font_var, pick_font, '或者下面直接给一个现成字库，二选一')
    row(4, '现成字库', blob_var, pick_blob, '.lzss 压缩态，或 1200128 字节的解压态 FONT00')
    row(6, '输出镜像', out_var, pick_out)

    sizes = ttk.Frame(frm)
    sizes.grid(row=8, column=1, sticky='w', pady=(8, 0))
    ttk.Label(sizes, text='汉字').pack(side='left')
    ttk.Entry(sizes, textvariable=zh_var, width=4).pack(side='left', padx=(4, 12))
    ttk.Label(sizes, text='标点').pack(side='left')
    ttk.Entry(sizes, textvariable=pu_var, width=4).pack(side='left', padx=(4, 12))
    ttk.Label(sizes, text='全角拉丁').pack(side='left')
    ttk.Entry(sizes, textvariable=la_var, width=4).pack(side='left', padx=(4, 0))
    ttk.Label(sizes, text='像素').pack(side='left', padx=(4, 0))

    status = ttk.Label(frm, text='准备就绪', foreground='#333')
    status.grid(row=9, column=0, columnspan=3, sticky='w', pady=(14, 4))
    bar = ttk.Progressbar(frm, maximum=100)
    bar.grid(row=10, column=0, columnspan=3, sticky='we')

    buttons = ttk.Frame(frm)
    buttons.grid(row=11, column=0, columnspan=3, sticky='e', pady=(14, 0))
    events: queue.Queue = queue.Queue()
    busy = {'v': False}

    def workload(kind):
        if busy['v']:
            return
        disc, font, blob = disc_var.get().strip(), font_var.get().strip(), blob_var.get().strip()
        if not disc:
            messagebox.showerror('无法开始', '请先选择输入镜像。', parent=root)
            return
        if not font and not blob:
            messagebox.showerror('无法开始', '请选择自定义字体，或者一个现成字库。', parent=root)
            return
        try:
            zh, pu, la = int(zh_var.get()), int(pu_var.get()), int(la_var.get())
        except ValueError:
            messagebox.showerror('无法开始', '字号必须是整数。', parent=root)
            return
        out = out_var.get().strip() or None
        if kind == 'build' and not out:
            messagebox.showerror('无法开始', '请先指定输出镜像路径。', parent=root)
            return
        if kind == 'build' and Path(out).exists():
            if not messagebox.askyesno('输出已存在', f'{out}\n已存在，覆盖它吗？', parent=root):
                return
        preview = None
        if kind == 'preview':
            s = Path(out or disc)
            preview = s.with_name(s.stem + '-预览.png')
        busy['v'] = True

        def work():
            try:
                lines = run(Path(disc), Path(font) if font else None,
                            Path(blob) if blob else None,
                            Path(out) if (out and kind == 'build') else None,
                            zh, la, pu, None, preview, None,
                            lambda text, value: events.put(('progress', text, value)))
                events.put(('done', kind, '\n'.join(lines), preview))
            except Exception as exc:                       # noqa: BLE001 报给用户看
                events.put(('error', str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            while True:
                ev = events.get_nowait()
                if ev[0] == 'progress':
                    status.config(text=ev[1])
                    bar['value'] = ev[2]
                elif ev[0] == 'done':
                    busy['v'] = False
                    bar['value'] = 100
                    status.config(text='完成')
                    if ev[1] == 'preview':
                        messagebox.showinfo('预览已生成', ev[2] + f'\n\n预览图：\n{ev[3]}', parent=root)
                    else:
                        messagebox.showinfo('打盘完成', ev[2], parent=root)
                elif ev[0] == 'error':
                    busy['v'] = False
                    bar['value'] = 0
                    status.config(text='失败')
                    messagebox.showerror('失败', ev[1], parent=root)
        except queue.Empty:
            root.after(120, poll)

    ttk.Button(buttons, text='只看预览', command=lambda: workload('preview')).pack(side='left', padx=6)
    ttk.Button(buttons, text='开始打盘', command=lambda: workload('build')).pack(side='left')

    ttk.Label(frm, text='本工具只换字库，不改剧情文本；输入镜像不会被修改。',
              foreground='#666').grid(row=12, column=0, columnspan=3, sticky='w', pady=(12, 0))

    # 按内容实际需要定尺寸：写死高度会把底部按钮切掉（不同 DPI 下更明显）
    root.update_idletasks()
    root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())

    root.after(120, poll)
    root.mainloop()
    return 0


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(
        description='把任意字体做成游戏字库并打进已经汉化好的 I’s Pure 镜像')
    ap.add_argument('--盘', dest='disc', type=Path, help='输入镜像（已汉化的 ISO）')
    ap.add_argument('--字体', dest='font', type=Path, help='自定义字体 .ttf/.otf/.ttc')
    ap.add_argument('--字库', dest='blob', type=Path, help='现成字库：.lzss 或解压态 FONT00')
    ap.add_argument('--输出', dest='out', type=Path, help='输出镜像路径')
    ap.add_argument('--字库源', dest='source_font', type=Path,
                    help='改用这份解压态 FONT00 作为槽位与字距基准（默认用盘上那份）')
    ap.add_argument('--汉字字号', dest='zh', type=int, default=20)
    ap.add_argument('--标点字号', dest='punct', type=int, default=18)
    ap.add_argument('--拉丁字号', dest='latin', type=int, default=18)
    ap.add_argument('--预览', dest='preview', nargs='?', const='', default=None,
                    metavar='PNG', help='生成预览图；不给路径则与输出同名 .png')
    ap.add_argument('--导出字库', dest='dump', type=Path, help='额外把生成的字库写到这个路径')
    args = ap.parse_args()

    if args.disc is None:
        if len(sys.argv) > 1:
            ap.print_help()
            return 1
        return gui()

    if bool(args.font) == bool(args.blob):
        print('错误：--字体 与 --字库 必须且只能给一个。', file=sys.stderr)
        return 1
    if args.out is None and args.preview is None and args.dump is None:
        print('错误：请给 --输出（或 --预览 / --导出字库 至少一个）。', file=sys.stderr)
        return 1

    preview = None
    if args.preview is not None:
        preview = Path(args.preview) if args.preview else \
            (args.out.with_suffix('.png') if args.out else
             Path(args.disc).with_name(Path(args.disc).stem + '-预览.png'))

    def progress(text, value):
        print(f'[{value:5.1f}%] {text}', flush=True)

    try:
        for line in run(args.disc, args.font, args.blob, args.out,
                        args.zh, args.latin, args.punct, args.source_font,
                        preview, args.dump, progress):
            print(line)
    except ToolError as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f'错误：找不到文件 {exc.filename}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
