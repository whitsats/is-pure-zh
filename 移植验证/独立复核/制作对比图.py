"""生成角色拼接前后的直观对照，仅用于当前调查。"""
from pathlib import Path
import sys
import numpy as np
from PIL import Image, ImageDraw

here = Path(__file__).resolve().parent
base = here.parent / "背景抽样验证"
sys.path.insert(0, str(base))
import chr_body  # noqa: E402

index = 634
old = Image.open(base / "chr_body" / f"full_{index:04}.png").convert("RGBA")
new = Image.open(base / "Codex_独立复核_20261113" / f"tilewrap_{index}.png").convert("RGBA")
thumb, _, _ = chr_body.thumb(index + 1)
thumb = thumb.copy()
thumb[:, :, 3] = np.minimum(thumb[:, :, 3].astype(np.uint16) * 2, 255).astype(np.uint8)
reference = Image.fromarray(thumb, "RGBA")
out = Image.new("RGB", (1074, 300), "white")
draw = ImageDraw.Draw(out)
for x, label, img in ((0, "Old extraction", old), (358, "32x32 experiment", new), (716, "Game thumbnail", reference)):
    img.thumbnail((340, 260), Image.Resampling.LANCZOS)
    out.paste(img, (x + (340 - img.width) // 2, 30 + (260 - img.height) // 2), img)
    draw.text((x + 12, 8), label, fill="black")
out.save(here / "634_拼接前后对照.png")
