from pathlib import Path
import numpy as np
from PIL import Image

p=Path(__file__).parent/'提取测试'
for n in (12,14,16,18):
    data=(p/f'BG_{n:03}.bin').read_bytes()[256:]
    tiles=np.frombuffer(data,dtype=np.uint8).reshape(-1,128,128,4)
    out=np.zeros((512,640,4),dtype=np.uint8)
    for i in range(20):
        y,x=divmod(i,5)
        out[y*128:(y+1)*128,x*128:(x+1)*128]=tiles[i]
    out[:,:,3]=np.minimum(255,out[:,:,3].astype('uint16')*2)
    Image.fromarray(out).save(p/f'BG_{n:03}_128测试.png')
