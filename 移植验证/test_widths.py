from pathlib import Path
from PIL import Image, ImageDraw

b = (Path(__file__).parent / '提取测试/BG_012.bin').read_bytes()[256:]
out = Image.new('RGB', (1200, 900), '#222222')
d = ImageDraw.Draw(out)
for i, w in enumerate([128,160,256,320,512,640,768,1024]):
    n = len(b) // (w * 4)
    im = Image.frombytes('RGBA', (w,n), b[:w*n*4]).convert('RGB')
    im.thumbnail((290,420))
    x,y=(i%4)*300,(i//4)*450
    out.paste(im,(x,y+20))
    d.text((x,y),str(w),fill='white')
out.save(Path(__file__).parent/'提取测试/宽度对照.png')
