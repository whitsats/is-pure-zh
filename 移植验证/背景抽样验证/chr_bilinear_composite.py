"""双线性合成：把解码出的 CHR 精灵按“游戏渲染”的方式放大并合成，复现第一张的观感。

用途：验证“下巴/耳边台阶是源画锯齿、被引擎滤波磨平”的结论。
我们的 PNG 是 1:1 原生像素图；游戏以双线性（bilinear）放大并合成到背景上，
对角线锯齿被滤波抹平。脚本提供两种放大：
  - nearest ：复现我们 PNG 的生硬台阶（6x 放大看最明显）
  - bilinear：复现游戏的平滑观感

用法：
    python chr_bilinear_composite.py 2840 --scale 4 --filter bilinear --out out.png
    python chr_bilinear_composite.py 2840 --scale 4 --filter nearest  --out out_nn.png
    # 合成到背景上（背景图需另行提供；不提供则用纯色底）
    python chr_bilinear_composite.py 2792 --scale 1.3 --bg bg.png --dx 10 --dy 24

参数：
    entry            CHR 偶数条目号（半身头像类，部件 160x160）
    --scale          放大倍率（默认 4.0）
    --filter         bilinear | nearest（默认 bilinear）
    --bg             背景图路径（默认纯色 #dddddd）
    --dx/--dy        合成时在背景上的左上角偏移（像素，默认 0）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chr_body as B  # noqa: E402


def sprite(idx: int, crop_content: bool = True) -> Image.Image:
    raw = B.entry(idx)
    canvas, _ = B.build(raw)
    if canvas is None:
        raise SystemExit(f"CHR {idx}: 解码失败")
    if crop_content:
        ys, xs = np.where(canvas[:, :, 3] > 0)
        canvas = canvas[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    al = canvas[:, :, 3].astype(np.uint16)
    a = np.clip((al * 255 + 64) // 128, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([canvas[:, :, :3], a]), "RGBA")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("entry", type=int)
    ap.add_argument("--scale", type=float, default=4.0)
    ap.add_argument("--filter", choices=("bilinear", "nearest"), default="bilinear")
    ap.add_argument("--bg", type=str, default=None)
    ap.add_argument("--dx", type=int, default=0)
    ap.add_argument("--dy", type=int, default=0)
    ap.add_argument("--out", type=str, required=True)
    args = ap.parse_args()

    sp = sprite(args.entry)
    nw, nh = max(1, round(sp.width * args.scale)), max(1, round(sp.height * args.scale))
    resample = Image.Resampling.BILINEAR if args.filter == "bilinear" else Image.Resampling.NEAREST
    big = sp.resize((nw, nh), resample)

    if args.bg:
        base = Image.open(args.bg).convert("RGB")
        canvas = Image.new("RGB", base.size, (221, 221, 221))
        canvas.paste(base, (0, 0))
    else:
        canvas = Image.new("RGB", (nw + 2 * args.dx, nh + 2 * args.dy), (221, 221, 221))
    # 用 alpha 合成（精灵背景在源数据里是不透明的，合成后仍为实色底）
    canvas_rgb = canvas.convert("RGBA")
    canvas_rgb.alpha_composite(big, (args.dx, args.dy))
    canvas_rgb.convert("RGB").save(args.out)
    print(f"saved {args.out} ({canvas_rgb.size[0]}x{canvas_rgb.size[1]}) "
          f"scale={args.scale} filter={args.filter} entry={args.entry}")


if __name__ == "__main__":
    main()
