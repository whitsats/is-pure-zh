from pathlib import Path
import numpy as np
from PIL import Image
from scipy.spatial.distance import cdist

p=Path(__file__).parent/'提取测试'
score=None
for n in (12,14,16,18):
    raw=np.array(Image.frombytes('RGBA',(1024,352),(p/f'BG_{n:03}.bin').read_bytes()[256:]))[:,:,:3]
    thumb=np.array(Image.open(p/f'BG_{n+1:03}.png').convert('RGB'))[11:79]
    tiles=raw.reshape(22,16,64,16,3).transpose(0,2,1,3,4).reshape(-1,16,16,3)
    src=tiles.reshape(-1,4,4,4,4,3).mean(axis=(2,4)).reshape(-1,48)
    target=thumb.reshape(17,4,40,4,3).transpose(0,2,1,3,4).reshape(-1,48)
    d=cdist(target,src,metric='sqeuclidean')
    score=d if score is None else score+d
idx=score.argmin(axis=1)
err=score.min(axis=1)/192
yy,xx=np.indices((17,40)); xx=xx.ravel(); yy=yy.ravel()
good=np.flatnonzero(err<100)
matrix=np.column_stack((xx,yy,np.ones(len(xx))))
rng=np.random.default_rng(17); best=None
for _ in range(4000):
    take=rng.choice(good,3,replace=False)
    try: coef=np.linalg.solve(matrix[take],idx[take])
    except np.linalg.LinAlgError: continue
    inside=good[np.abs(matrix[good]@coef-idx[good])<3]
    if best is None or len(inside)>len(best): best=inside
if best is not None and len(best)>3:
    coef=np.linalg.lstsq(matrix[best],idx[best],rcond=None)[0]
    print('linear fit',coef, 'inliers',len(best),'of',len(good))
print('error',np.mean(score.min(axis=1)/4/48),'unique',len(set(idx)))
for row in (0,3,6,9,12,15):
    print('row',row,[(int(idx[row*40+x]%64),int(idx[row*40+x]//64),round(float(score[row*40+x,idx[row*40+x]]/192))) for x in range(0,40,4)])
raw=np.array(Image.frombytes('RGBA',(1024,352),(p/'BG_012.bin').read_bytes()[256:]))[:,:,:3]
tiles=raw.reshape(22,16,64,16,3).transpose(0,2,1,3,4).reshape(-1,16,16,3)
out=tiles[idx].reshape(17,40,16,16,3).transpose(0,2,1,3,4).reshape(272,640,3)
Image.fromarray(out).save(p/'BG_012_裁切匹配试验.png')
pred=np.clip(np.rint(matrix@coef).astype(int),0,len(tiles)-1)
out=tiles[pred].reshape(17,40,16,16,3).transpose(0,2,1,3,4).reshape(272,640,3)
Image.fromarray(out).save(p/'BG_012_线性排列试验.png')
