#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 对照/*.tsv 的译文烘焙进 MAC.AFS（章节剧本归档）。

数据链路
--------
* 对白在 MAC.AFS：74 个条目（IS01_1.bip … SHORTCUT02.bip），每条是一段 LZSS 剧本。
* 槽位定位：`原始解包/日文原始文本/*.BIP.bin.txt`（原作者工程文件，UTF-16）
  给出每条台词的偏移；原文按 cp932 编码后应与原盘字节逐字节相同 —— 以此自证定位正确。
* 槽位（帧）长度 = 原盘日文的字节数；汉化盘把中文写进这段，不足处补 0xFF，
  后面的控制符（%K%P 等）位置不动。
* 中文字码：先从「上一版译文（git）↔ 现役汉化盘字节」反推，再用原作者的
  `输出码表.txt`（3127 字）补上新译文才用到的字。

用法
----
  python 打盘/烘焙文本.py --检
  python 打盘/烘焙文本.py --写 --输出 一键打盘/patch/mac-v6.afs
"""
from __future__ import annotations

import argparse
import re
import struct
import difflib
import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_COMMIT = '8bdf69f'
JP_TEXT_DIR = Path(r'D:\Code\IS汉化\日文原始文本')
AUTHOR_TABLE = Path(r'D:\Code\IS汉化\原始解包\输出码表.txt')
MAC_LBA = 192346
MAC_SLOT = 1081344


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
    size = int.from_bytes(blob[:4], 'little')
    ring, at, pos, out = bytearray(4096), 0xfee, 4, bytearray()
    while pos < len(blob) and len(out) < size:
        flag = blob[pos]
        pos += 1
        for _ in range(8):
            if pos >= len(blob) or len(out) >= size:
                break
            if flag & 1:
                b = blob[pos]; pos += 1
                out.append(b); ring[at] = b; at = (at + 1) & 4095
            else:
                a, b = blob[pos], blob[pos + 1]; pos += 2
                src = a | ((b & 0xf0) << 4)
                for j in range((b & 15) + 3):
                    v = ring[(src + j) & 4095]
                    out.append(v); ring[at] = v; at = (at + 1) & 4095
            flag >>= 1
    if len(out) != size:
        raise ValueError(f'LZSS 解压长度不符：期望 {size}，得到 {len(out)}')
    return bytes(out)


# --------------------------------------------------------------------------- #
class Afs:
    def __init__(self, data: bytes):
        self.data = data
        self.magic, self.count = struct.unpack_from('<4sI', data, 0)
        if self.magic != b'AFS\x00':
            raise ValueError(f'不是 AFS：魔数 {self.magic!r}')
        self.meta, self.metalen = struct.unpack_from('<II', data, 8 + self.count * 8)
        self.entries = []
        for i in range(self.count):
            off, size = struct.unpack_from('<II', data, 8 + i * 8)
            nm = data[self.meta + i * 48: self.meta + i * 48 + 32].split(b'\0')[0].decode('ascii', 'replace')
            self.entries.append({'i': i, 'name': nm, 'off': off, 'size': size})
        self._dec = {}

    def by_name(self) -> dict:
        return {e['name'].lower(): e for e in self.entries}

    def blob(self, e) -> bytes:
        return self.data[e['off']:e['off'] + e['size']]

    def dec(self, e) -> bytes:
        if e['i'] not in self._dec:
            self._dec[e['i']] = unpack(self.blob(e))
        return self._dec[e['i']]

    def allocation(self, e):
        later = [x['off'] for x in self.entries if x['off'] > e['off']]
        end = min(later) if later else len(self.data)
        return end - e['off'], end


def load_mac_from_iso(iso: Path, lba: int = MAC_LBA, size: int = MAC_SLOT) -> Afs:
    with iso.open('rb') as f:
        f.seek(lba * 2048)
        return Afs(f.read(size))


# --------------------------------------------------------------------------- #
# 读各种文本
# --------------------------------------------------------------------------- #
def read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode('utf-16')
    for enc in ('utf-8-sig', 'gbk'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', 'replace')


JP_RE = re.compile(
    r'No\.(\d+)\n([0-9A-Fa-f]{8}),([0-9A-Fa-f]{2})\n'
    r'\uff0d{16}\n(.*?)\n\uff0d{16}\n(.*?)\n\uff0d{16}', re.S)


def parse_project_file(path: Path):
    """解析原作者的工程文件：返回 (目标文件, [(No, 偏移, 长度, 原文, 译文)])"""
    txt = read_text_any(path).replace('\r\n', '\n').replace('\r', '\n')
    m = re.search(r'文件名称[：:]\s*(\S+)', txt)
    target = (m.group(1) if m else path.name).lower()
    if target.endswith('.bin'):
        target = target[:-4]
    items = []
    for mm in JP_RE.finditer(txt):
        items.append((int(mm.group(1)), int(mm.group(2), 16), int(mm.group(3), 16),
                      mm.group(4).strip(), mm.group(5).strip()))
    return target, items


def load_jp_locations(d: Path):
    """{文件: {No: (偏移, 日文原文)}}"""
    out = {}
    for p in sorted(d.glob('*.txt')):
        target, items = parse_project_file(p)
        out[target] = {no: (off, jp) for no, off, ln, jp, _cn in items}
    return out


def parse_duizhao_text(txt: str):
    out, cur = {}, None
    for line in txt.replace('\r\n', '\n').split('\n'):
        if line.startswith('#'):
            cur = line[1:].strip().lower()
            if cur:
                out.setdefault(cur, {})
            continue
        if not cur or not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) < 3 or not parts[0].startswith('No.'):
            continue
        try:
            no = int(parts[0][3:])
        except ValueError:
            continue
        out[cur][no] = (parts[1], parts[2])
    return out


def load_duizhao(d: Path):
    out = {}
    for p in sorted(d.glob('*.tsv')):
        out.update(parse_duizhao_text(read_text_any(p)))
    return out


def load_duizhao_old(commit: str = OLD_COMMIT):
    out = {}
    files = subprocess.run(['git', 'ls-tree', '--name-only', f'{commit}', '对照/'],
                           cwd=ROOT, capture_output=True, text=True, encoding='utf-8').stdout.split()
    for f in files:
        if not f.endswith('.tsv'):
            continue
        txt = subprocess.run(['git', 'show', f'{commit}:{f}'], cwd=ROOT,
                             capture_output=True).stdout.decode('utf-8', 'replace')
        out.update(parse_duizhao_text(txt))
    return out


def load_author_table(path: Path):
    """作者码表：XXXX=字 → {字: [码, ...]}"""
    tbl = defaultdict(list)
    if not path.exists():
        return tbl
    for line in read_text_any(path).splitlines():
        line = line.strip()
        if '=' not in line:
            continue
        code, ch = line.split('=', 1)
        code = code.strip().lower()
        if len(code) == 4 and ch:
            tbl[ch].append(code)
    return tbl


# --------------------------------------------------------------------------- #
def encode(text: str, table: dict):
    """中文 → 盘上字节；ASCII 按单字节。返回 (字节, 缺字)"""
    out, miss = bytearray(), []
    for ch in text:
        if ord(ch) < 0x80:
            out.append(ord(ch)); continue
        code = table.get(ch)
        if code is None:
            miss.append(ch); continue
        out.append(int(code, 16) >> 8 if isinstance(code, str) else code >> 8)
        out.append((int(code, 16) if isinstance(code, str) else code) & 0xFF)
    return bytes(out), miss


def decode_cn(seg: bytes, rev: dict):
    """槽位字节 → 中文（用于自检）"""
    out, i, n = [], 0, len(seg)
    while i < n:
        b = seg[i]
        if b == 0xFF:
            break
        if b < 0x80:
            out.append(chr(b)); i += 1
        else:
            code = (seg[i] << 8) | seg[i + 1]
            out.append(rev.get(code, f'<{code:04X}>')); i += 2
    return ''.join(out)


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description='把对照译文烘焙进 MAC.AFS')
    ap.add_argument('--对照', dest='duizhao', type=Path, default=ROOT / '对照')
    ap.add_argument('--日文', dest='jpdir', type=Path, default=JP_TEXT_DIR)
    ap.add_argument('--作者码表', dest='authortable', type=Path, default=AUTHOR_TABLE)
    ap.add_argument('--mac', dest='mac', type=Path, default=ROOT / '一键打盘' / 'patch' / 'mac-v6.afs')
    ap.add_argument('--原盘', dest='orig', type=Path, default=ROOT / 'game-original.iso')
    ap.add_argument('--旧提交', dest='old_commit', default=OLD_COMMIT)
    ap.add_argument('--输出', dest='out', type=Path, default=None)
    ap.add_argument('--检', dest='check', action='store_true')
    ap.add_argument('--写', dest='write', action='store_true')
    args = ap.parse_args()

    dz_new = load_duizhao(args.duizhao)
    dz_old = load_duizhao_old(args.old_commit)
    jp_loc = load_jp_locations(args.jpdir)
    author = load_author_table(args.authortable)
    orig = load_mac_from_iso(args.orig)
    mac7 = Afs(args.mac.read_bytes())
    print(f'对照 {len(dz_new)} 段 / {sum(len(v) for v in dz_new.values())} 行；'
          f'旧版 {len(dz_old)} 段')
    print(f'日文工程文件 {len(jp_loc)} 个；作者码表 {len(author)} 字')
    print(f'原盘 MAC {orig.count} 条；汉化 MAC {mac7.count} 条，{len(mac7.data):,} 字节')

    # ---- 第 1 步：定位（按号匹配 + 日文字节自证；缺号的按内容回退）----
    print('\n=== 第 1 步：定位槽位 ===')
    author_rev = {}
    for ch, codes in author.items():
        for c in codes:
            author_rev.setdefault(int(c, 16), ch)

    def decoded_jp(s: str) -> str:
        """把工程文件的真日文，按作者码表转成「对照里那种写法」。"""
        try:
            b = s.encode('cp932')
        except UnicodeEncodeError:
            return s
        out, i = [], 0
        while i < len(b):
            c = b[i]
            if 0x81 <= c <= 0x9f or 0xe0 <= c <= 0xfc:
                code = (b[i] << 8) | b[i + 1]
                out.append(author_rev.get(code, '?'))
                i += 2
            else:
                out.append(chr(c)); i += 1
        return ''.join(out)

    slots = defaultdict(dict)
    problems = []
    by_no = 0
    for fname in sorted(dz_new):
        afs_name = fname if fname.endswith('.bip') else fname + '.bip'
        e = orig.by_name().get(afs_name)
        if e is None:
            problems.append(f'{fname}: 原盘没有 {afs_name}')
            continue
        dec = orig.dec(e)
        loc = jp_loc.get(afs_name) or {}
        if not loc:
            problems.append(f'{fname}: 没有日文工程文件')
            continue
        unresolved = []
        for no in sorted(dz_new[fname]):
            cand = loc.get(no)
            if cand is not None:
                off, jp = cand
                jpb = jp.encode('cp932')
                if dec[off:off + len(jpb)] == jpb:
                    slots[fname][no] = {'off': off, 'ext': len(jpb), 'jp': jp, 'src': '同号'}
                    by_no += 1
                    continue
            unresolved.append(no)
        # 回退：按日文内容在工程文件里找（唯一才收）
        index = defaultdict(list)
        for k, (off, jp) in loc.items():
            if k in slots[fname]:
                continue
            index[decoded_jp(jp)].append((k, off, jp))
        for no in unresolved:
            jp_line = dz_new[fname][no][0]
            if no in loc:
                problems.append(f'{fname} No.{no}: 同号偏移 0x{loc[no][0]:X} 原盘字节不符')
                continue
            got = index.get(jp_line)
            if got and len(got) == 1:
                k, off, jp = got[0]
                jpb = jp.encode('cp932')
                if dec[off:off + len(jpb)] == jpb:
                    slots[fname][no] = {'off': off, 'ext': len(jpb), 'jp': jp, 'src': f'换号{k}'}
                    index[jp_line] = []
                    continue
            problems.append(f'{fname} No.{no}: 找不到对应日文「{jp_line[:24]}」')
    print(f'  按号定位 {by_no} 条；合计定位 {sum(len(v) for v in slots.values())} 条；'
          f'问题 {len(problems)} 条')
    for x in problems[:10]:
        print(f'    ! {x}')

    # ---- 第 2 步：旧译文 ↔ 汉化盘字节，反推中文码表 ----
    print('\n=== 第 2 步：反推中文码表（旧译文 ↔ 汉化盘）===')
    mac7n = mac7.by_name()
    t_cn, ok_lines, cn_bad = {}, 0, []
    rev_used = {}
    for fname, nos in slots.items():
        e = mac7n.get(fname if fname.endswith('.bip') else fname + '.bip')
        dec = mac7.dec(e)
        old = dz_old.get(fname, {})
        for no in sorted(nos):
            s = nos[no]
            if no not in old:
                cn_bad.append(f'{fname} No.{no}: 旧版对照里没有这一行')
                continue
            cn = old[no][1]
            seg = dec[s['off']:s['off'] + s['ext']]
            body = seg[:len(seg) - len(seg.lstrip(b''))]
            # 逐字对齐：中文双字节，ASCII 单字节，遇 0xFF 结束
            i, pairs, bad = 0, [], None
            for ch in cn:
                if ord(ch) < 0x80:
                    if i >= len(seg) or seg[i] != ord(ch):
                        bad = f'{ch!r} 位置不符'; break
                    pairs.append((ch, seg[i])); i += 1
                else:
                    if i + 1 >= len(seg) or seg[i] == 0xFF:
                        bad = '字节不足/提前结束'; break
                    pairs.append((ch, (seg[i] << 8) | seg[i + 1])); i += 2
            if bad:
                cn_bad.append(f'{fname} No.{no}: {bad}')
                continue
            for ch, code in pairs:
                if ord(ch) < 0x80:
                    continue
                prev = t_cn.get(ch)
                if prev is None:
                    t_cn[ch] = code
                elif prev != code:
                    cn_bad.append(f'{fname} No.{no}: {ch!r} 盘上 0x{code:04X} vs 表里 0x{prev:04X}')
            ok_lines += 1
    print(f'  对齐 {ok_lines} 条；码表 {len(t_cn)} 字；问题 {len(cn_bad)} 条')
    for x in cn_bad[:6]:
        print(f'    ! {x}')

    # ---- 第 2.5 步：用盘上旧译文找回「工程文件里没有」的条目 ----
    print('\n=== 第 2.5 步：夹逼找回缺号条目 ===')
    def slot_extent(dec, off, end):
        i = end
        while i < len(dec) and dec[i] == 0xFF:
            i += 1
        return i - off

    recovered = 0
    for fname in sorted(dz_new):
        afs_name = fname if fname.endswith('.bip') else fname + '.bip'
        if afs_name not in mac7n:
            continue
        dec_v = mac7.dec(mac7n[afs_name])
        old = dz_old.get(fname, {})
        todo = [no for no in sorted(dz_new[fname]) if no not in slots[fname]]
        if not todo:
            continue
        anchors = sorted([(s['off'], no) for no, s in slots[fname].items()])
        for no in todo:
            if no not in old:
                continue
            enc, miss = encode(old[no][1], t_cn)
            if miss or len(enc) < 6:
                continue
            # 用比它小的最近锚点做下界，比它大的最近锚点做上界
            lo = 0
            hi = len(dec_v)
            for off, k in anchors:
                if k < no:
                    lo = max(lo, off)
                elif k > no:
                    hi = min(hi, off)
            hits = []
            pat = enc[:max(6, len(enc) - 4)]
            i = dec_v.find(pat, lo)
            while 0 <= i < hi:
                hits.append(i)
                i = dec_v.find(pat, i + 1)
            if len(hits) != 1:
                problems.append(f'{fname} No.{no}: 夹逼命中 {len(hits)} 处')
                continue
            off = hits[0]
            ext = slot_extent(dec_v, off, off + len(enc))
            # 闸门一：必须像个台词起点（前一字节是句尾控制码/填充）
            if off > 0 and dec_v[off - 1] not in (0x00, 0xFF):
                problems.append(f'{fname} No.{no}: 夹逼位置 0x{off:X} 不像起点')
                continue
            # 闸门二：不得与已定槽位重叠
            clash = False
            for other, os_ in slots[fname].items():
                if off < os_['off'] + os_['ext'] and os_['off'] < off + ext:
                    clash = True
                    break
            if clash:
                problems.append(f'{fname} No.{no}: 夹逼位置 0x{off:X} 与已有槽位重叠')
                continue
            slots[fname][no] = {'off': off, 'ext': ext, 'jp': '', 'src': '夹逼'}
            anchors.append((off, no))
            anchors.sort()
            recovered += 1
            # 顺便把这一条的码表补上
            i2, seg = 0, dec_v[off:off + ext]
            for ch in old[no][1]:
                step = 1 if ord(ch) < 0x80 else 2
                if i2 + step > len(seg) or (step == 2 and seg[i2] == 0xFF):
                    break
                if step == 2:
                    t_cn.setdefault(ch, (seg[i2] << 8) | seg[i2 + 1])
                i2 += step
    print(f'  找回 {recovered} 条；仍缺 {sum(1 for f in dz_new for no in dz_new[f] if no not in slots[f])} 条')
    for x in problems[-6:]:
        print(f'    ! {x}')

    # ---- 第 3 步：往返校验 ----
    print('\n=== 第 3 步：往返校验（旧译文重编码 == 汉化盘字节）===')
    same = diff = 0
    for fname, nos in slots.items():
        e = mac7n.get(fname if fname.endswith('.bip') else fname + '.bip')
        dec = mac7.dec(e)
        old = dz_old.get(fname, {})
        for no in sorted(nos):
            s = nos[no]
            if no not in old:
                continue
            seg = dec[s['off']:s['off'] + s['ext']]
            body = seg.split(b'\xff')[0]
            enc, miss = encode(old[no][1], t_cn)
            if miss:
                diff += 1
                continue
            # 盘上可能用 0xFF 填充到帧末
            if enc == body or (seg.startswith(enc) and set(seg[len(enc):]) <= {0xFF}):
                same += 1
            else:
                diff += 1
                if diff <= 5:
                    print(f'    ! {fname} No.{no}\n        盘上 {body.hex(" ")}\n        重编 {enc.hex(" ")}')
    print(f'  完全一致 {same} 条；不一致 {diff} 条')

    # ---- 第 4 步：新译文检查（补作者码表）----
    print('\n=== 第 4 步：新译文检查 ===')
    t_full = dict(t_cn)
    borrowed = Counter()
    changed, overflow = 0, 0
    missing = Counter()
    over_rows = []
    for fname, nos in slots.items():
        new = dz_new.get(fname, {})
        old = dz_old.get(fname, {})
        for no in sorted(nos):
            s = nos[no]
            if no not in new:
                continue
            cn_new = new[no][1]
            cn_old = old.get(no, (None, None))[1]
            if cn_new == cn_old:
                continue
            changed += 1
            need = {}
            enc, miss = encode(cn_new, t_full)
            for ch in miss:
                codes = author.get(ch)
                if codes:
                    t_full[ch] = int(codes[0], 16)
                    borrowed[ch] += 1
                else:
                    missing[ch] += 1
            enc, miss = encode(cn_new, t_full)
            if len(enc) > s['ext']:
                overflow += 1
                over_rows.append((fname, no, s['ext'], len(enc), cn_old, cn_new))
    print(f'  译文改动 {changed} 条')
    if borrowed:
        print(f'  借作者码表补了 {len(borrowed)} 个字：'
              + '、'.join(f'{c}=0x{t_full[c]:04X}×{k}' for c, k in borrowed.most_common(12)))
    if missing:
        print(f'  作者码表也没有的字 {len(missing)} 个：'
              + '、'.join(f'{c}(U+{ord(c):04X})×{k}' for c, k in missing.most_common(20)))
    else:
        print('  改动行用到的字全部有码 ✓')
    if overflow:
        print(f'  槽位装不下 {overflow} 条：')
        for f, no, ext, need, co, cn in over_rows[:15]:
            print(f'      {f} No.{no}: 帧 {ext} 字节，需要 {need}')
            print(f'          旧 «{co}»')
            print(f'          新 «{cn}»')
    else:
        print('  所有改动行都装得进原帧 ✓')

    if args.write:
        if missing:
            raise SystemExit('还有缺字，先解决再写盘')
        print('\n=== 第 5 步：写出新 MAC.AFS ===')
        out = args.out or (args.mac.parent / 'mac-v6-新.afs')
        bake(mac7, slots, dz_new, dz_old, t_full, out, allow_overflow=overflow)
    return 0


def bake(mac7, slots, dz_new, dz_old, t_cn, out: Path, allow_overflow: int = 0) -> None:
    by_name = mac7.by_name()
    new_blobs, skipped = {}, []
    written = []
    for fname, nos in slots.items():
        afs_name = fname if fname.endswith('.bip') else fname + '.bip'
        e = by_name[afs_name]
        dec = bytearray(mac7.dec(e))
        new = dz_new.get(fname, {})
        old = dz_old.get(fname, {})
        n = 0
        for no in sorted(nos):
            s = nos[no]
            if no not in new:
                continue
            cn_new = new[no][1]
            if cn_new == old.get(no, (None, None))[1]:
                continue
            enc, miss = encode(cn_new, t_cn)
            if miss:
                raise SystemExit(f'{fname} No.{no} 缺字 {miss}')
            if len(enc) > s['ext']:
                skipped.append((fname, no, s['ext'], len(enc)))
                continue
            dec[s['off']:s['off'] + s['ext']] = enc + b'\xff' * (s['ext'] - len(enc))
            written.append({'file': afs_name, 'no': no, 'off': s['off'], 'ext': s['ext'],
                            'old': old.get(no, (None, ''))[1], 'new': cn_new})
            n += 1
        blob = compress_lzss(bytes(dec))
        new_blobs[e['i']] = blob
        print(f'  {afs_name}: 改 {n} 条，压缩后 {len(blob):,} 字节')
    data = bytearray(mac7.data)
    # 先试原地替换（不动其它条目）
    inplace_ok = True
    for e in mac7.entries:
        blob = new_blobs.get(e['i'])
        if blob is None:
            continue
        alloc, _end = mac7.allocation(e)
        if len(blob) > alloc:
            inplace_ok = False
            break
    if inplace_ok:
        for e in mac7.entries:
            blob = new_blobs.get(e['i'])
            if blob is None:
                continue
            alloc, _end = mac7.allocation(e)
            data[e['off']:e['off'] + len(blob)] = blob
            data[e['off'] + len(blob):e['off'] + alloc] = b'\x00' * (alloc - len(blob))
            struct.pack_into('<II', data, 8 + e['i'] * 8, e['off'], len(blob))
            struct.pack_into('<I', data, mac7.meta + e['i'] * 48 + 44, len(blob))
        print('  布局：原地替换，未移动其它条目')
    else:
        # 有条目变大，整体重排（2048 对齐），元数据表挪到末尾
        data = repack(mac7, new_blobs)
        print('  布局：整体重排（2048 对齐），元数据表移到末尾')
    if len(data) > MAC_SLOT:
        raise SystemExit(f'新 MAC.AFS {len(data):,} > ISO 槽位 {MAC_SLOT:,}')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(data))
    print(f'  已写出 {out}（{len(data):,} 字节）')
    if skipped:
        print(f'  跳过装不下的 {len(skipped)} 条：{skipped[:8]}')

    chk = Afs(out.read_bytes())
    rev = {v: k for k, v in t_cn.items()}
    ok = 0
    for fname, nos in slots.items():
        afs_name = fname if fname.endswith('.bip') else fname + '.bip'
        dec = chk.dec(chk.by_name()[afs_name])
        new = dz_new.get(fname, {})
        old = dz_old.get(fname, {})
        for no in sorted(nos):
            s = nos[no]
            if no not in new or new[no][1] == old.get(no, (None, None))[1]:
                continue
            enc, _ = encode(new[no][1], t_cn)
            if len(enc) > s['ext']:
                continue
            seg = dec[s['off']:s['off'] + s['ext']]
            # 逐字节比对（比解码更严格：绕开「织/織 共用同一码」这类反查歧义）
            if seg[:len(enc)] != enc or set(seg[len(enc):]) - {0xFF}:
                raise SystemExit(
                    f'自检失败 {fname} No.{no}\n    期望 {enc.hex(" ")}\n    盘上 {seg.hex(" ")}')
            ok += 1
    print(f'  自检通过：{ok} 条改动行在新 AFS 里逐字节核对一致')
    import json as _json
    man = out.with_name('烘焙清单.json')
    man.write_text(_json.dumps({'written': written, 'skipped': skipped},
                               ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'  清单已写出：{man}（{len(written)} 条）')


def repack(mac7: Afs, new_blobs: dict) -> bytearray:
    """按 2048 对齐重排全部条目，更新条目表与元数据表。"""
    first_off = min(e['off'] for e in mac7.entries)
    count = mac7.count
    out = bytearray(mac7.data[:first_off])          # 头 + 条目表 + 前置数据
    meta = bytearray(mac7.data[mac7.meta:mac7.meta + mac7.metalen])
    for e in mac7.entries:
        blob = new_blobs.get(e['i'], mac7.blob(e))
        while len(out) % 2048:
            out.append(0)
        off = len(out)
        out += blob
        struct.pack_into('<II', out, 8 + e['i'] * 8, off, len(blob))
        struct.pack_into('<I', meta, e['i'] * 48 + 44, len(blob))
    meta_off = len(out)
    out += meta
    struct.pack_into('<II', out, 8 + count * 8, meta_off, len(meta))
    return out


if __name__ == '__main__':
    raise SystemExit(main())
