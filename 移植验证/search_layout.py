from pathlib import Path
import cv2
import numpy as np

p=Path(__file__).parent/'提取测试'
b=(p/'BG_012.bin').read_bytes()[256:]
raw=np.frombuffer(b,dtype=np.uint8).reshape(352,1024,4)[:,:,:3]
tiles=raw.reshape(22,16,64,16,3).transpose(0,2,1,3,4).reshape(-1,16,16,3)
thumb=cv2.imdecode(np.fromfile(p/'BG_013.png',dtype=np.uint8),cv2.IMREAD_COLOR)
thumb=cv2.cvtColor(thumb,cv2.COLOR_BGR2RGB)[11:81]
rank=[]
for w in range(40,65):
    rows=(len(tiles)+w-1)//w
    padded=np.zeros((rows*w,16,16,3),dtype=np.uint8);padded[:len(tiles)]=tiles
    a=padded.reshape(rows,w,16,16,3).transpose(0,2,1,3,4).reshape(rows*16,w*16,3)
    a=cv2.resize(a,(w*4,rows*4),interpolation=cv2.INTER_AREA)
    for factor in (0.8,0.85,0.9,0.95,1.0,1.05):
        t=cv2.resize(thumb,None,fx=factor,fy=factor,interpolation=cv2.INTER_AREA)
        if t.shape[0]>a.shape[0] or t.shape[1]>a.shape[1]:continue
        _,v,_,loc=cv2.minMaxLoc(cv2.matchTemplate(a,t,cv2.TM_CCOEFF_NORMED))
        rank.append((round(v,4),w,factor,loc))
print(sorted(rank,reverse=True)[:15])
