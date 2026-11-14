"""CHR.AFS 全身类条目（部件图集）解析器 —— 已破解。

格式（由 CHR 6/10/0/4/1386/634 实测确认，全部数值逐个对上）：

1. 条目 = 0x100 或 0x180 字节头 + RGBA8888 像素流。
2. 像素流按 **1024 px 行宽** 切成 32 行高的「条带行」，行内按部件宽度从左到右摆放条带。
3. 头部：
     +0x80  u32         部件数量 count
     +0x90   count × 8B 部件记录，每条：
             +0  u8 x/32
             +1  u8 y/32
             +2  u8 w/32
             +3  u8 h/32
             +4  u16 =2（末条为 0）
             +6  u16 B = 该部件结束位置的累计行偏移（行 = 1024 px，末条为 0）
   最后一段长度 = 流总长 - 前一条的 B*1024。
4. 块号模型（2026-11-13 修正，取代旧「货架」模型）：像素流切成 1024×32 的**存储行**，
   每行 = 32 个 32×32 块；所有部件共用连续块号 tile（**不在部件边界清零**）：
       sx = (tile % 32) * 32,  sy = (tile // 32) * 32
   部件内按 y=0,32,…、x=0,32,… 逐块取回，拼成 w×h 再按 (x,y) 贴上画布。
   旧模型「一条宽 w 的条带整条换行」在 w=32/64/128/256 时与它等价，但在 w=96/160/192 时会
   跳过行尾剩余块，使 477/879 条错位（中位 IoU 0.850 vs 修正后 0.963）。
5. 把各部件按 (x, y) 贴到画布上即得整张立绘。**画布 704×480**：对 879 个条目统计得到
   max(x+w)=704、max(y+h)=480，与 BG.AFS 的 704 宽内部画布一致；头部 12 字节段的
   640×448 是显示帧，不是画布。
6. alpha 实测最大只有 **128**（7 位），输出 PNG 时需 ×255/128 才能还原半透明边缘。

校验：与配对奇数条目的 TIM2 缩略图做剪影 IoU（两边各剔除小于主连通域 2% 的碎屑、
裁到内容包围盒后归一化比较）。
"""
from __future__ import annotations

import csv
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from extract_bg import unpack  # noqa: E402

# 镜像文件名会随打盘版本变化（game-v5 → v7 → v7.1），优先用未改动的原盘；
# 需要指定时设环境变量 CHR_ISO。
def _find_iso() -> Path:
    import os
    env = os.environ.get("CHR_ISO")
    if env:
        return Path(env)
    root = Path(__file__).resolve().parent.parent.parent
    for name in ("game-original.iso", "game-v7.1.iso", "game-v7.iso", "game-v5.iso"):
        p = root / name
        if p.exists():
            return p
    return root / "game-original.iso"


ISO = _find_iso()
BASE = 106958848
OUT = Path(__file__).resolve().parent / "chr_body"
CANVAS = (704, 480)  # 实测：全部 879 个条目中 max(x+w)=704、max(y+h)=480


_FH = None


def entry(index: int) -> bytes:
    global _FH
    if _FH is None:
        _FH = open(ISO, "rb")
    _FH.seek(BASE + 8 + index * 8)
    off, ln = struct.unpack("<II", _FH.read(8))
    _FH.seek(BASE + off)
    return unpack(_FH.read(ln))


def header_len(raw: bytes) -> int:
    for hs in (0x100, 0x180):
        if len(raw) > hs and (len(raw) - hs) % 8192 == 0:
            return hs
    return 0x100


def records(raw: bytes, hs: int):
    cnt = struct.unpack_from("<I", raw, 0x80)[0]
    if not (1 <= cnt <= 40) or 0x90 + cnt * 8 > hs:
        return []
    out = []
    for k in range(cnt):
        o = 0x90 + k * 8
        b0, b1, b2, b3 = raw[o : o + 4]
        flag = struct.unpack_from("<H", raw, o + 4)[0]
        bval = struct.unpack_from("<H", raw, o + 6)[0]
        out.append({"x": b0 * 32, "y": b1 * 32, "w": b2 * 32, "h": b3 * 32, "flag": flag, "end": bval})
    return out


def build(raw: bytes, stats: dict | None = None):
    """返回 (canvas RGBA, 部件列表)。失败返回 (None, [])

    高度一律以表里的 h 为准（旧版对最后一件用 (total-pos)//w 反推，会多读十几个块）；
    把 stats 传进来可以拿到 {tiles_total, tiles_used, leftover}。
    """
    if stats is not None:
        stats.clear()
    hs = header_len(raw)
    px = np.frombuffer(raw, np.uint8, offset=hs, count=((len(raw) - hs) // 4) * 4)
    total = px.size // 4
    rows = total // 1024
    recs = records(raw, hs)
    if not recs or rows < 1:
        return None, []
    canvas = np.zeros((CANVAS[1], CANVAS[0], 4), np.uint8)
    used = []

    # 像素流按 1024 px 宽、32 行高切成「存储行」，每行 = 32 个 32×32 块。
    # 所有部件共用连续的块号 tile（不在部件边界清零）：
    #     sx = (tile % 32) * 32,  sy = (tile // 32) * 32
    # 部件内部按 y=0,32,…,h-32、x=0,32,…,w-32 的顺序把块贴回一个 w×h 的图，
    # 再按表中的 (x, y) 放到画布上。
    # 注意：这与旧「货架」模型（一条宽 w 的条带整条换行）在 w=32/64/128/256 时等价，
    # 在 w=96/160/192 时不同——旧模型会跳过行尾剩余块，导致 477/879 条错位。
    nband = rows // 32                      # 每 32 条 1024 像素行 = 一个存储行（32 个 32×32 块）
    block = px[: nband * 1024 * 32 * 4].reshape(nband, 32, 1024, 4)
    total_tiles = nband * 32
    tile = 0
    pos = 0
    for k, r in enumerate(recs):
        w = r["w"]
        if w <= 0 or not (1 <= w <= 1024):
            return None, used
        h = r["h"]
        if h <= 0:                       # 表里没给高度：退回用剩余长度
            h = (total - pos) // w
        if h <= 0:
            continue
        tw, th = max(1, w // 32), max(1, h // 32)
        piece = np.zeros((th * 32, tw * 32, 4), np.uint8)
        for j in range(th):
            for i in range(tw):
                if tile >= total_tiles:
                    break
                sy, sx = tile // 32, tile % 32
                piece[j * 32 : (j + 1) * 32, i * 32 : (i + 1) * 32] = block[sy, :, sx * 32 : (sx + 1) * 32]
                tile += 1
        pos += h * w
        x, y = r["x"], r["y"]
        H = min(h, canvas.shape[0] - y)
        W = min(w, canvas.shape[1] - x)
        if H <= 0 or W <= 0 or x >= canvas.shape[1] or y >= canvas.shape[0]:
            continue
        sub = piece[:H, :W]
        m = sub[:, :, 3] > 0
        canvas[y : y + H, x : x + W][m] = sub[m]
        used.append({**r, "real_h": h, "index": k})
    if stats is not None:
        stats.update({"tiles_total": total_tiles, "tiles_used": tile,
                      "leftover": total_tiles - tile, "px_left": total - pos})
    return canvas, used


def thumb(index: int):
    raw = entry(index)
    hs = struct.unpack_from("<H", raw, 0x1C)[0]
    w, h = struct.unpack_from("<HH", raw, 0x24)
    d = np.frombuffer(raw, np.uint8, offset=0x10 + hs, count=w * h * 4).reshape(h, w, 4)
    return d, w, h


def _main_blob(mask: np.ndarray, keep: float = 0.02) -> np.ndarray:
    """丢掉小于主连通域 2% 的碎屑（保留不相连的肢体/道具）。"""
    try:
        from scipy import ndimage
    except Exception:  # noqa: BLE001
        return mask
    lab, n = ndimage.label(mask)
    if n <= 1:
        return mask
    sizes = np.asarray(ndimage.sum(mask, lab, range(1, n + 1)))
    thresh = sizes.max() * keep
    keep_ids = np.nonzero(sizes >= thresh)[0] + 1
    return np.isin(lab, keep_ids)


def silhouette_iou(canvas: np.ndarray, tref: np.ndarray) -> float:
    """两边取主连通域、裁到包围盒后归一化再比（缩略图留白与小件不惩罚）。"""
    crop = _main_blob(canvas[:, :, 3] > 0)
    ys, xs = np.where(crop)
    if not ys.size:
        return 0.0
    crop = crop[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    t = _main_blob(tref)
    ty, tx = np.where(t)
    if not ty.size:
        return 0.0
    t = t[ty.min() : ty.max() + 1, tx.min() : tx.max() + 1]
    h, w = t.shape
    m = np.asarray(Image.fromarray(crop.astype(np.uint8) * 255, "L").resize((w, h), Image.Resampling.BILINEAR)) > 96
    return float(np.logical_and(m, t).sum() / max(1, np.logical_or(m, t).sum()))


def save(canvas, path: Path):
    """alpha 在源数据里最大只有 128（7 位），必须放大到 0..255 才能正确显示半透明边缘。"""
    al = canvas[:, :, 3].astype(np.uint16)
    a = np.clip((al * 255 + 64) // 128, 0, 255).astype(np.uint8)
    Image.fromarray(np.dstack([canvas[:, :, :3], a]), "RGBA").save(path)


def comparison(canvas, t: np.ndarray, path: Path):
    """三联：拼好的立绘 | 缩略图 | 剪影重叠。"""
    ys, xs = np.where(canvas[:, :, 3] > 0)
    if not ys.size:
        return
    crop = canvas[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h, w = t.shape[:2]
    big = Image.fromarray(crop, "RGBA").resize((w * 2, h * 2), Image.Resampling.LANCZOS)
    left = Image.new("RGBA", (w * 2, h * 2), (255, 255, 255, 255))
    left.alpha_composite(big)
    ref = Image.fromarray(t, "RGBA").resize((w * 2, h * 2), Image.Resampling.NEAREST)
    rm = np.frombuffer(ref.tobytes(), np.uint8).reshape(h * 2, w * 2, 4)[:, :, 3] > 0
    sm = np.frombuffer(big.tobytes(), np.uint8).reshape(h * 2, w * 2, 4)[:, :, 3] > 0
    ov = np.zeros((h * 2, w * 2, 3), np.uint8)
    ov[rm] = [60, 60, 220]
    ov[sm & rm] = [40, 200, 90]
    shot = Image.new("RGBA", (w * 6 + 16, h * 2), (255, 255, 255, 255))
    shot.alpha_composite(left, (0, 0))
    shot.alpha_composite(ref, (w * 2 + 8, 0))
    shot.alpha_composite(Image.fromarray(ov, "RGB").convert("RGBA"), (w * 4 + 16, 0))
    shot.save(path)


def is_body(index: int) -> bool:
    """配对缩略图为 160x112 的条目 = 全身/半身类。"""
    try:
        _, w, h = thumb(index + 1)
    except Exception:
        return False
    return (w, h) == (160, 112)


def main():
    OUT.mkdir(exist_ok=True)
    args = [int(a) for a in sys.argv[1:]]
    if args:
        for idx in args:
            raw = entry(idx)
            st: dict = {}
            canvas, used = build(raw, st)
            t, w, h = thumb(idx + 1)
            tref = t[:, :, :3].astype(np.int16).mean(axis=2) > 24
            iou = silhouette_iou(canvas, tref) if canvas is not None else 0
            print(f"CHR {idx}: parts {len(used)} IoU {iou:.3f} "
                  f"leftover {st.get('leftover', 0)} 块 ({st.get('px_left', 0)} px)")
            if canvas is not None:
                save(canvas, OUT / f"full_{idx:04d}.png")
                comparison(canvas, t, OUT / f"cmp_{idx:04d}.png")
        return

    with open(ISO, "rb") as f:
        f.seek(BASE + 4)
        n_entries = struct.unpack("<I", f.read(4))[0]
    rows = []
    for idx in range(0, n_entries, 2):
        if not is_body(idx):
            continue
        try:
            raw = entry(idx)
            st: dict = {}
            canvas, used = build(raw, st)
            t, w, h = thumb(idx + 1)
            tref = t[:, :, :3].astype(np.int16).mean(axis=2) > 24
            iou = silhouette_iou(canvas, tref) if canvas is not None else 0.0
            ok = canvas is not None and len(used) >= 1
            rows.append([idx, "ok" if ok else "fail", round(iou, 4), len(used), w, h,
                         st.get("leftover", 0)])
        except Exception as e:  # noqa: BLE001
            rows.append([idx, f"error:{type(e).__name__}", 0.0, 0, 0, 0, 0])
    with open(OUT / "chr_body.csv", "w", newline="", encoding="utf-8") as f:
        wri = csv.writer(f)
        wri.writerow(["index", "status", "iou", "parts", "thumb_w", "thumb_h", "leftover_tiles"])
        wri.writerows(rows)
    good = [r for r in rows if r[1] == "ok"]
    ious = np.array([r[2] for r in good]) if good else np.array([0.0])
    print(f"总计 {len(rows)}  可解析 {len(good)}")
    if good:
        for t in (0.90, 0.85, 0.80, 0.70, 0.60):
            print(f"  IoU >= {t:.2f}: {int((ious >= t).sum())}")
    left = np.array([r[6] for r in rows], dtype=int)
    nz = left[left > 0]
    print(f"未消费块：{int((left > 0).sum())}/{len(rows)} 条有条尾未用块，总计 {int(left.sum())} 块"
          f"（中位 {int(np.median(nz)) if nz.size else 0}、最大 {int(left.max()) if left.size else 0}）")
    if nz.size:
        print(f"  每条未用块数 中位 {int(np.median(nz))}  最大 {int(nz.max())}  "
              f"（1 块 = 32×32 = 1024 px）")
        vals, cnts = np.unique(nz, return_counts=True)
        top = sorted(zip(cnts, vals), reverse=True)[:6]
        print("  最常见: " + ", ".join(f"{int(v)} 块×{int(c)} 条" for c, v in top))


if __name__ == "__main__":
    main()
