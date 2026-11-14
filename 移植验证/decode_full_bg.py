from pathlib import Path
import struct
import sys
import numpy as np
from PIL import Image
from extract_bg import unpack

root=Path(__file__).resolve().parent
output=root/'完整背景验证'
output.mkdir(exist_ok=True)
indices=[int(v) for v in sys.argv[1:]] or [12,14,16,18]
with (root.parent/'game-v5.iso').open('rb') as f:
    for index in indices:
        base=636928
        f.seek(base+8+index*8)
        offset,length=struct.unpack('<II',f.read(8))
        f.seek(base+offset)
        raw=unpack(f.read(length))
        if len(raw)!=0x160100 or raw[:4]!=b'\x05\x00\x00\x00':
            print(index,'unsupported layout',len(raw)); continue
        # The 1024x352 stored buffer is made of 64x32 blocks, arranged as
        # an 11-column (704px) image with 16 block rows (512px).
        pixels=np.frombuffer(raw,dtype=np.uint8,offset=256).reshape(11,32,16,64,4)
        tiles=pixels.transpose(0,2,1,3,4).reshape(16,11,32,64,4)
        image=tiles.transpose(0,2,1,3,4).reshape(512,704,4).copy()
        image[:,:,3]=np.minimum(image[:,:,3].astype(np.uint16)*2,255).astype(np.uint8)
        result=Image.fromarray(image)
        result.save(output/f'BG_{index:03}.png')
        print(index,'size',result.size,'alpha bounding box',result.getchannel('A').getbbox())
