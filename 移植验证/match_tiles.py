from pathlib import Path
import numpy as np
from PIL import Image

p = Path(__file__).parent/'提取测试'
b = (p/'BG_012.bin').read_bytes()[256:]
raw = np.array(Image.frombytes('RGBA',(1024,352),b))[:,:,:3]
thumb = np.array(Image.open(p/'BG_013.png').convert('RGB'))
source = []
for y in range(16,336,32):
    for x in range(0,1024,64):
        tile = raw[y:y+32,x:x+64]
        small = np.array(Image.fromarray(tile).resize((16,8),Image.Resampling.BOX)).astype(np.float32)
        source.append((small,tile))
out = Image.new('RGB',(640,448))
errors = []
for ty in range(2,12):
    for tx in range(10):
        target = thumb[ty*8:ty*8+8,tx*16:tx*16+16].astype(np.float32)
        scores = [np.mean((v-target)**2) for v,_ in source]
        best = int(np.argmin(scores)); errors.append(scores[best])
        out.paste(Image.fromarray(source[best][1]), (tx*64,ty*32))
out.save(p/'BG_012_匹配试验.png')
print('MSE mean:',np.mean(errors),'median:',np.median(errors))
