from pathlib import Path
import numpy as np
from PIL import Image

p=Path(__file__).parent/'提取测试'
data=np.frombuffer((p/'BG_012.bin').read_bytes()[256:],dtype=np.uint8).reshape(-1,4)
blocks=np.array([[0,1,4,5,16,17,20,21],[2,3,6,7,18,19,22,23],[8,9,12,13,24,25,28,29],[10,11,14,15,26,27,30,31]])
words=np.array([[0,1,4,5,8,9,12,13],[2,3,6,7,10,11,14,15]])
y,x=np.indices((448,640))
for pagewidth in (10,11,12,16):
    idx=((y//32)*pagewidth+x//64)*2048+blocks[(y%32)//8,(x%64)//8]*64+((y%8)//2)*16+words[y%2,x%8]
    valid=idx<len(data)
    out=np.zeros((448,640,4),dtype=np.uint8)
    out[valid]=data[idx[valid]]
    out[:,:,3]=255
    Image.fromarray(out).save(p/f'BG_012_swizzle_{pagewidth}.png')
