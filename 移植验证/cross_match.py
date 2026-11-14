from pathlib import Path
import numpy as np
from PIL import Image
from scipy.spatial.distance import cdist

p=Path(__file__).parent/'提取测试'
score=None
target_shape=(28,40)
for n in (12,14,16,18):
    raw=np.array(Image.frombytes('RGBA',(1024,352),(p/f'BG_{n:03}.bin').read_bytes()[256:]))[:,:,:3]
    thumb=np.array(Image.open(p/f'BG_{n+1:03}.png').convert('RGB'))
    tiles=raw.reshape(22,16,64,16,3).transpose(0,2,1,3,4).reshape(-1,16,16,3)
    src=tiles.reshape(-1,4,4,4,4,3).mean(axis=(2,4)).reshape(-1,48)
    target=thumb.reshape(28,4,40,4,3).transpose(0,2,1,3,4).reshape(-1,48)
    d=cdist(target,src,metric='sqeuclidean')
    score=d if score is None else score+d
idx=score.argmin(axis=1)
print('error',float(np.mean(score.min(axis=1)/4/48)), 'unique source',len(set(idx)))
for n in (12,14,16,18):
    raw=np.array(Image.frombytes('RGBA',(1024,352),(p/f'BG_{n:03}.bin').read_bytes()[256:]))[:,:,:3]
    tiles=raw.reshape(22,16,64,16,3).transpose(0,2,1,3,4).reshape(-1,16,16,3)
    out=tiles[idx].reshape(28,40,16,16,3).transpose(0,2,1,3,4).reshape(448,640,3)
    Image.fromarray(out).save(p/f'BG_{n:03}_多图匹配试验.png')
