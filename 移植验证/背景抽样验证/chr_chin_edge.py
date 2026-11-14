"""部件纵向错位检验：相邻两件在共享竖边上必须连续。

对每对左右相邻的部件（x_a+w_a == x_b），在两者都有内容的行上比较共享边两侧的 RGB 差；
再把右边（或左边）的件整体上下平移 dy ∈ {-96..96 step 32}，看哪个 dy 让边界最连续。
dy=0 最小 => 该件纵向摆放正确；若某件的最佳 dy != 0，它就是错位来源。
"""
import sys

import numpy as np

sys.path.insert(0, ".")
import chr_body as B  # noqa: E402


def edge_cost(c, a, b, dy):
    """b 件相对 a 件平移 dy 后，共享竖边处的不连续度（越低越连续）"""
    x = b["x"]
    y0 = max(a["y"], b["y"] + dy)
    y1 = min(a["y"] + a["real_h"], b["y"] + b["real_h"] + dy)
    if y1 - y0 < 8:
        return None, 0
    left = c[y0:y1, x - 1].astype(np.int16)
    right_rows = np.clip(np.arange(y0, y1) - dy, 0, c.shape[0] - 1)
    right = c[right_rows, x].astype(np.int16)
    m = (left[:, 3] > 0) & (right[:, 3] > 0)
    if m.sum() < 8:
        return None, int(m.sum())
    d = np.abs(left[m, :3] - right[m, :3]).mean()
    return float(d), int(m.sum())


def run(idx, verbose=True):
    raw = B.entry(idx)
    c, used = B.build(raw)
    print(f"\n=== CHR {idx} ===")
    bad = []
    for k, b in enumerate(used):
        # 找左邻居（右边界正好贴着我）
        left = [a for a in used if a is not b and a["x"] + a["w"] == b["x"]]
        if not left:
            continue
        a = max(left, key=lambda p: min(p["y"] + p["real_h"], b["y"] + b["real_h"]) - max(p["y"], b["y"]))
        res = {}
        for dy in (-96, -64, -32, 0, 32, 64, 96):
            cost, n = edge_cost(c, a, b, dy)
            if cost is not None:
                res[dy] = (cost, n)
        if not res:
            continue
        best = min(res, key=lambda d: res[d][0])
        s = " ".join(f"{d:+d}:{res[d][0]:.1f}" for d in sorted(res))
        flag = "" if best == 0 else "  <== 最佳位移非 0"
        print(f"  P{b['index']}(x={b['x']},y={b['y']}) 贴 P{a['index']}(x={a['x']},y={a['y']}): "
              f"best dy={best:+d}  [{s}]{flag}")
        if best != 0 and res[0][0] - res[best][0] > 3:
            bad.append((b["index"], best, res[0][0], res[best][0]))
    if bad:
        print("  疑似纵向错位部件:", bad)
    else:
        print("  所有相邻件的共享边在 dy=0 处最连续（无纵向错位）")
    return used


for a in sys.argv[1:]:
    run(int(a))
