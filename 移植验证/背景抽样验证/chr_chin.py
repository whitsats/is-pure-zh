"""下巴/颈部一带（y=120–220）错位定位：重建 vs 缩略图，并标出部件边界。

用法：python chr_chin.py 6 2778 2850 1506
产物：chr_body/chin_{idx}.png   上=重建 ×2（红线=部件上下边，虚线=32 的倍数），下=缩略图同带
      chr_body/chin_{idx}_tint.png 同一带，每件用不同色调，直接看出哪一件的像素在这条带上
"""
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, ".")
import chr_body as B  # noqa: E402

Y0, Y1 = 120, 220
SC = 3
argv = [a for a in sys.argv[1:] if not a.startswith("--")]
if "--y" in sys.argv:
    k = sys.argv.index("--y")
    Y0, Y1 = int(sys.argv[k + 1]), int(sys.argv[k + 2])
    argv = [a for a in argv if a not in (sys.argv[k + 1], sys.argv[k + 2])]
TINTS = [(255, 0, 0), (0, 160, 0), (0, 0, 255), (255, 140, 0),
         (160, 0, 160), (0, 160, 160), (120, 80, 0), (255, 0, 160)]


def row_jumps(c):
    """每一行的 RGB 变化量（只算两侧都不透明的像素），返回 {y: 平均差}"""
    rgb = c[:, :, :3].astype(np.int16)
    a = c[:, :, 3] > 0
    out = {}
    for y in range(1, c.shape[0]):
        m = a[y] & a[y - 1]
        if m.sum() < 20:
            continue
        out[y] = float(np.abs(rgb[y][m] - rgb[y - 1][m]).mean())
    return out


def tint(c, used):
    t = np.zeros_like(c)
    for k, p in enumerate(used):
        sub = c[p["y"]:p["y"] + p["real_h"], p["x"]:p["x"] + p["w"]]
        m = sub[:, :, 3] > 0
        region = t[p["y"]:p["y"] + p["real_h"], p["x"]:p["x"] + p["w"]]
        col = np.array(TINTS[k % len(TINTS)], np.uint8)
        region[m] = np.concatenate([col, [255]]).astype(np.uint8)
        t[p["y"]:p["y"] + p["real_h"], p["x"]:p["x"] + p["w"]] = region
    return t


def band_thumb(idx):
    t, w, h = B.thumb(idx + 1)
    a = (t[:, :, 3:4].astype(np.uint16) * 255 + 64) // 128
    a = np.clip(a, 0, 255).astype(np.uint8)
    img = Image.fromarray(np.dstack([t[:, :, :3], a]), "RGBA").resize((704, 480), Image.Resampling.NEAREST)
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img)
    return bg.convert("RGB")


def run(idx):
    raw = B.entry(idx)
    st = {}
    c, used = B.build(raw, st)
    print(f"\n=== CHR {idx}  parts={len(used)} leftover={st.get('leftover')} ===")
    for k, p in enumerate(used):
        mark = " <-- 覆盖 y=%d..%d" % (p["y"], p["y"] + p["real_h"]) if p["y"] <= Y1 and p["y"] + p["real_h"] >= Y0 else ""
        print(f"  P{k}: x={p['x']:3d} y={p['y']:3d} w={p['w']:3d} h={p['real_h']:3d}"
              f"  (y/w/32 整除: {p['y'] % 32 == 0}/{p['w'] % 32 == 0}){mark}")

    # 重建带
    al = np.clip((c[:, :, 3].astype(np.uint16) * 255 + 64) // 128, 0, 255).astype(np.uint8)
    rec = Image.new("RGBA", (704, 480), (255, 255, 255, 255))
    rec.alpha_composite(Image.fromarray(np.dstack([c[:, :, :3], al]), "RGBA"))
    W = 704 * SC
    H = (Y1 - Y0) * SC
    rec = rec.convert("RGB").crop((0, Y0, 704, Y1)).resize((W, H), Image.Resampling.NEAREST)

    th = band_thumb(idx).crop((0, Y0, 704, Y1)).resize((W, H), Image.Resampling.LANCZOS)

    # tint 带 + 边界线
    tt = tint(c, used)
    tt = Image.fromarray(tt, "RGBA")
    tt = tt.crop((0, Y0, 704, Y1)).resize((W, H), Image.Resampling.NEAREST)
    d = ImageDraw.Draw(tt)
    for y in range(Y0, Y1 + 1, 32):
        py = (y - Y0) * SC
        d.line([(0, py), (W, py)], fill=(0, 0, 0, 120), width=1)
        d.text((4, py + 1), str(y), fill=(0, 0, 0, 255))

    out = Image.new("RGB", (W, H * 3 + 8), (240, 240, 240))
    out.paste(rec, (0, 0))
    out.paste(th, (0, H + 4))
    out.paste(tt.convert("RGB"), (0, H * 2 + 8))
    d = ImageDraw.Draw(out)
    d.text((8, 2), f"CHR {idx}  y={Y0}-{Y1}   panel1=rebuild  panel2=thumb  panel3=part tint",
           fill=(0, 0, 0))
    out.save(B.OUT / f"chin_{idx}.png")

    # 行跳变，看是否落在 32 的倍数
    j = row_jumps(c)
    band = {y: v for y, v in j.items() if Y0 - 20 <= y <= Y1 + 20}
    top = sorted(band.items(), key=lambda kv: -kv[1])[:8]
    print("  行间差最大的行:", ", ".join(f"y={y}({v:.1f}, {'32k' if y % 32 == 0 else '非'})" for y, v in top))
    edges = {p["y"] for p in used} | {p["y"] + p["real_h"] for p in used}
    hits = [y for y, v in band.items() if y in edges and v > 12]
    print("  部件横边且跳变>12 的行:", hits if hits else "无")
    return used

for a in argv:
    run(int(a))
print("\nsaved:", ", ".join(f"chr_body/chin_{a}.png" for a in argv))
