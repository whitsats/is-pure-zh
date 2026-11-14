"""导出保留透明度的角色样本；角色拼接仍沿用未验证的旧算法。"""
from pathlib import Path
import sys

import numpy as np
from PIL import Image

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parent / "背景抽样验证"))
import chr_body  # noqa: E402

for index in (634, 1272):
    canvas, _ = chr_body.build(chr_body.entry(index))
    if canvas is None:
        raise RuntimeError(f"无法读取角色 {index}")
    alpha = canvas[:, :, 3]
    count = int(((alpha > 0) & (alpha < 128)).sum())
    canvas[:, :, 3] = np.minimum(alpha.astype(np.uint16) * 2, 255).astype(np.uint8)
    target = here / f"{index}_保留透明度_拼接仍有误.png"
    Image.fromarray(canvas, "RGBA").save(target)
    print(f"{index}: 半透明像素 {count}，已写入 {target}")
