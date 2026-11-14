"""CHR 部件表自洽校验 + 最低分条目对照表。

用法：
    python chr_check.py validate [idx ...]   # 逐条校验部件表（默认全部 879）
    python chr_check.py worst [N]            # 取 IoU 最低的 N 条出对照表（默认 20）

校验项（都是纯结构性的，与摆放/比对逻辑无关）：
  C1 count 字段与真正读到的记录数一致，且表不越界
  C2 每条记录 B 严格递增（末条 B=0）
  C3 由 B 差分算出的 h 为 32 的整数倍且 > 0
  C4 sum(h*w) 恰好等于像素流长度（无剩余、无越界）
  C5 x+w <= 704、y+h <= 480（画布边界）
"""
from __future__ import annotations

import csv
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402

OUT = B.OUT


def load(idx: int):
    raw = B.entry(idx)
    hs = B.header_len(raw)
    total = (len(raw) - hs) // 4
    cnt = struct.unpack_from("<I", raw, 0x80)[0]
    recs = B.records(raw, hs)
    return raw, hs, total, cnt, recs


def validate(idx: int):
    raw, hs, total, cnt, recs = load(idx)
    issues = []
    if len(recs) != cnt:
        issues.append(f"C1 count={cnt} 实读={len(recs)}")
    if cnt == 0 or 0x90 + cnt * 8 > hs:
        issues.append(f"C1 表越界 cnt={cnt} hs={hs:#x}")

    pos = 0
    last_b = -1
    for k, r in enumerate(recs):
        last = k == len(recs) - 1
        if last:
            if r["end"] != 0:
                issues.append(f"C2 末条 end={r['end']} 非 0")
            h = (total - pos) // r["w"]
            if (total - pos) % r["w"]:
                issues.append(f"C4 末条剩余 {total - pos} 不能被 w={r['w']} 整除")
        else:
            if r["end"] <= last_b:
                issues.append(f"C2 p{k} end={r['end']} 未递增（上一条 {last_b}）")
            last_b = r["end"]
            span = r["end"] * 1024 - pos
            if span <= 0 or span % r["w"]:
                issues.append(f"C3 p{k} 跨度 {span} 不能被 w={r['w']} 整除")
                h = 0
            else:
                h = span // r["w"]
                if h % 32:
                    issues.append(f"C3 p{k} h={h} 不是 32 的倍数")
                if r["h"] != h:
                    issues.append(f"C3 p{k} 图上 h={r['h']} 差分解 h={h}")
        if r["x"] + r["w"] > 704:
            issues.append(f"C5 p{k} x+w={r['x'] + r['w']} > 704")
        if r["y"] + r["h"] > 480:
            issues.append(f"C5 p{k} y+h={r['y'] + r['h']} > 480")
        pos += h * r["w"]
    if pos != total:
        issues.append(f"C4 累计 {pos} != 总长 {total}")
    return issues, recs, total


def cmd_validate(args):
    with open(B.ISO, "rb") as f:
        f.seek(B.BASE + 4)
        n = struct.unpack("<I", f.read(4))[0]
    idxs = [int(a) for a in args] if args else [i for i in range(0, n, 2) if B.is_body(i)]
    bad = 0
    for idx in idxs:
        issues, recs, total = validate(idx)
        if issues:
            bad += 1
            print(f"CHR {idx}: {len(issues)} 项")
            for s in issues[:6]:
                print("    ", s)
    print(f"\n校验 {len(idxs)} 条，有问题 {bad} 条")


def cmd_worst(args):
    n = int(args[0]) if args else 20
    rows = [r for r in csv.DictReader(open(OUT / "chr_body.csv", encoding="utf-8"))]
    rows.sort(key=lambda r: float(r["iou"]))
    rows = rows[:n]
    render(rows, f"montage_worst{len(rows)}.png")


def cmd_sheet(args):
    """按给定条目号出对照表：python chr_check.py sheet 1260 1404 ..."""
    want = {int(a) for a in args}
    rows = [r for r in csv.DictReader(open(OUT / "chr_body.csv", encoding="utf-8")) if int(r["index"]) in want]
    rows.sort(key=lambda r: float(r["iou"]))
    render(rows, "montage_sample.png")


def render(rows, name):

    cell_w, cell_h = 176, 232          # 每张立绘格
    head = 18
    sheet = Image.new("RGBA", (cell_w * 4 + 8 * 5, (cell_h + head) * 5 + 8 * 6), (255, 255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        idx = int(r["index"])
        iou = float(r["iou"])
        canvas, used = B.build(B.entry(idx))
        t, w, h = B.thumb(idx + 1)
        col, row = i % 4, i // 4
        x0 = 8 + col * (cell_w + 8)
        y0 = 8 + row * (cell_h + head + 8)
        d.text((x0, y0), f"CHR {idx}  IoU {iou:.3f}  {len(used)}p", fill=(0, 0, 0, 255))
        # 重建
        ys, xs = np.where(canvas[:, :, 3] > 0)
        if ys.size:
            crop = canvas[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            im = Image.fromarray(crop, "RGBA")
            im.thumbnail((cell_w // 2 - 6, cell_h - 6), Image.Resampling.LANCZOS)
            bg = Image.new("RGBA", (cell_w // 2 - 6, cell_h - 6), (255, 255, 255, 255))
            bg.alpha_composite(im, ((bg.width - im.width) // 2, (bg.height - im.height) // 2))
            sheet.alpha_composite(bg, (x0, y0 + head))
        # 缩略图
        ref = Image.fromarray(t, "RGBA")
        ref.thumbnail((cell_w // 2 - 6, cell_h - 6), Image.Resampling.NEAREST)
        bg2 = Image.new("RGBA", (cell_w // 2 - 6, cell_h - 6), (255, 255, 255, 255))
        bg2.alpha_composite(ref, ((bg2.width - ref.width) // 2, (bg2.height - ref.height) // 2))
        sheet.alpha_composite(bg2, (x0 + cell_w // 2, y0 + head))
    path = OUT / name
    sheet.save(path)
    print("saved", path, "rows:", [(int(r["index"]), float(r["iou"])) for r in rows])


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if mode == "validate":
        cmd_validate(sys.argv[2:])
    elif mode == "sheet":
        cmd_sheet(sys.argv[2:])
    else:
        cmd_worst(sys.argv[2:])
