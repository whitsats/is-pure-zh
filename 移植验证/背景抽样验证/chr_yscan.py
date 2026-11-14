"""全量扫描：部件横向边界（y 或 y+h）处有没有真实的横向错位。

对 879 个全身类条目：
  1. 同列多件是否重叠（重叠 = 后画的会盖住前画的，可能产生接缝）；
  2. 同列多件之间的空隙是否落在剪影内部（上下都实、中间透明 = 被切掉一条横带）；
  3. 部件边界行 y 的行间跳变，与该行 ±40 行内其它行跳变的中位数之比（ratio）；
     ratio 大 = 边界处颜色突变，肉眼会看成“错位线”。
输出 chr_body/yscan.csv，按 ratio 排序。
"""
import csv
import statistics as st
import sys

import numpy as np

sys.path.insert(0, ".")
import chr_body as B  # noqa: E402


def scan(idx):
    raw = B.entry(idx)
    c, used = B.build(raw)
    if c is None:
        return None
    rgb = c[:, :, :3].astype(np.int16)
    a = c[:, :, 3] > 0
    j = {}
    for y in range(1, c.shape[0]):
        m = a[y] & a[y - 1]
        if m.sum() >= 20:
            j[y] = float(np.abs(rgb[y][m] - rgb[y - 1][m]).mean())
    edges = sorted({p["y"] for p in used} | {p["y"] + p["real_h"] for p in used})
    edges = [y for y in edges if 0 < y < 480]
    worst, worst_y = 0.0, 0
    for y in edges:
        if y not in j:
            continue
        band = [v for k, v in j.items() if 3 < abs(k - y) <= 40]
        if len(band) < 8:
            continue
        ref = st.median(band)
        r = j[y] / ref if ref > 0 else 0.0
        if r > worst:
            worst, worst_y = r, y
    # 重叠 / 缺口
    over = 0
    cut = 0
    for i, p in enumerate(used):
        for q in used[i + 1:]:
            ox = min(p["x"] + p["w"], q["x"] + q["w"]) - max(p["x"], q["x"])
            oy = min(p["y"] + p["real_h"], q["y"] + q["real_h"]) - max(p["y"], q["y"])
            if ox > 0 and oy > 0:
                over += 1
    by = {}
    for p in used:
        by.setdefault(p["x"], []).append(p)
    for x, ps in by.items():
        ps.sort(key=lambda p: p["y"])
        for u, v in zip(ps, ps[1:]):
            ya, yb = u["y"] + u["real_h"], v["y"]
            if ya >= yb:
                continue
            above = (c[ya - 1, x:x + u["w"], 3] > 0).mean()
            below = (c[yb, x:x + v["w"], 3] > 0).mean()
            inside = (c[ya:yb, x:x + u["w"], 3] > 0).mean()
            if above > 0.2 and below > 0.2 and inside < 0.05:
                cut += 1
    return {"index": idx, "parts": len(used), "edges": len(edges),
            "worst_ratio": round(worst, 2), "worst_y": worst_y,
            "overlaps": over, "cuts": cut}


def main():
    with open(B.ISO, "rb") as f:
        f.seek(B.BASE + 4)
        n = int.from_bytes(f.read(4), "little")
    out = []
    for idx in range(0, n, 2):
        if not B.is_body(idx):
            continue
        try:
            r = scan(idx)
        except Exception as e:  # noqa: BLE001
            print("ERR", idx, type(e).__name__, e)
            continue
        if r:
            out.append(r)
        if len(out) % 50 == 0:
            print("...", len(out), flush=True)
    keys = ["index", "parts", "edges", "worst_ratio", "worst_y", "overlaps", "cuts"]
    with open(B.OUT / "yscan.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out)
    r = np.array([x["worst_ratio"] for x in out])
    print(f"总计 {len(out)}；跨部件重叠的条目 {(np.array([x['overlaps'] for x in out]) > 0).sum()}；"
          f"剪影内被切横带的条目 {(np.array([x['cuts'] for x in out]) > 0).sum()}")
    for t in (1.5, 2.0, 3.0, 4.0):
        print(f"  边界处跳变/邻域中位 >= {t}: {(r >= t).sum()}")
    top = sorted(out, key=lambda x: -x["worst_ratio"])[:12]
    for x in top:
        print(f"  CHR {x['index']:4d} ratio={x['worst_ratio']:.2f} y={x['worst_y']} "
              f"parts={x['parts']} edges={x['edges']}")
    print("ALLDONE")


main()
