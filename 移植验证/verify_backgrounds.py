from pathlib import Path
import numpy as np
from PIL import Image

p=Path(__file__).parent/'完整背景验证'
q=Path(__file__).parent/'提取测试'
for n in (12,14,16,18):
    im=Image.open(p/f'BG_{n:03}.png')
    original=im.crop(im.getchannel('A').getbbox()).convert('RGB').resize((160,70),Image.Resampling.LANCZOS)
    reference=Image.open(q/f'BG_{n+1:03}.png').convert('RGB').crop((0,11,160,81))
    e=np.abs(np.asarray(original).astype(float)-np.asarray(reference).astype(float))
    print(n,'mean RGB difference',round(float(e.mean()),2),'95th percentile',round(float(np.percentile(e,95)),1))
