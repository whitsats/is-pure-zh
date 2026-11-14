"""为一次 PCSX2 纹理转储生成小图索引，保留原文件。"""
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

root = Path(__file__).resolve().parents[2]
folder = root / 'PCSX2' / 'textures' / 'SLPM-66570' / 'dumps'
files = sorted(folder.glob('*.png'), key=lambda p: p.stat().st_mtime)
strips = []
for path in files:
    with Image.open(path) as im:
        if im.size == (1024, 32):
            strips.append((path, im.convert('RGBA').copy()))
sheet = Image.new('RGB', (1200, max(1, len(strips)) * 36), 'white')
draw = ImageDraw.Draw(sheet)
for i, (path, im) in enumerate(strips):
    pix = np.asarray(im).copy()
    if pix[:, :, 3].max() <= 128:
        pix[:, :, 3] = np.minimum(pix[:, :, 3].astype(np.uint16) * 2, 255).astype(np.uint8)
    im = Image.fromarray(pix, 'RGBA')
    sheet.paste(im, (175, i * 36), im)
    draw.text((0, i * 36 + 8), path.name[:18], fill='black')
target = Path(__file__).parent / 'PCSX2_纹理长条索引.png'
sheet.save(target)
print('所有纹理:', len(files), '长条:', len(strips), '输出:', target)
