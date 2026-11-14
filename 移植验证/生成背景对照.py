from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent
full = Image.open(root / '完整背景验证' / 'BG_016.png').convert('RGBA')
thumb = Image.open(root / '提取测试' / 'BG_017.png').convert('RGBA')
full = full.crop(full.getchannel('A').getbbox())
thumb = thumb.crop((0, 11, 160, 81))
size = (684, 298)
full = full.resize(size, Image.Resampling.LANCZOS)
thumb = thumb.resize(size, Image.Resampling.NEAREST)
canvas = Image.new('RGB', (1400, 385), '#f3f3f3')
draw = ImageDraw.Draw(canvas)
font_path = Path('C:/Windows/Fonts/msyh.ttc')
font = ImageFont.truetype(str(font_path), 22) if font_path.exists() else ImageFont.load_default()
small = ImageFont.truetype(str(font_path), 16) if font_path.exists() else ImageFont.load_default()
draw.text((10, 10), '游戏自带缩略图（160×70，放大显示）', font=font, fill='#111')
draw.text((706, 10), '解包重排后的背景（可见区域约 684×298）', font=font, fill='#111')
canvas.paste(thumb.convert('RGB'), (10, 48))
canvas.paste(full.convert('RGB'), (706, 48))
draw.text((10, 352), '注：左侧是游戏资源中自带的缩略预览，不是游戏运行截图。两侧均裁去周边区域后对照。', font=small, fill='#444')
target = root / '背景解包前后对照.png'
canvas.save(target)
print(target)
