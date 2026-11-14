from pathlib import Path
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

p=Path(__file__).parent/'提取测试'
raw=np.array(Image.frombytes('RGBA',(1024,352),(p/'BG_012.bin').read_bytes()[256:]))[:,:,:3]
thumb=np.array(Image.open(p/'BG_013.png').convert('RGB'))
tiles=raw.reshape(22,16,64,16,3).transpose(0,2,1,3,4).reshape(-1,16,16,3)
smalls=tiles.reshape(-1,4,4,4,4,3).mean(axis=(2,4)).reshape(-1,48)
targets=thumb.reshape(28,4,40,4,3).transpose(0,2,1,3,4).reshape(-1,48)
dist,idx=cKDTree(smalls).query(targets)
out=tiles[idx].reshape(28,40,16,16,3).transpose(0,2,1,3,4).reshape(448,640,3)
Image.fromarray(out).save(p/'BG_012_16px试验.png')
print('mean error',np.mean(dist**2/48),'median',np.median(dist**2/48))
