from pathlib import Path
import cv2
import numpy as np

p=Path(__file__).parent/'提取测试'
raw=np.frombuffer((p/'BG_012.bin').read_bytes()[256:],dtype=np.uint8).reshape(352,1024,4)[:,:,:3]
thumb=cv2.imdecode(np.fromfile(p/'BG_013.png',dtype=np.uint8),1)
thumb=cv2.cvtColor(thumb,cv2.COLOR_BGR2RGB)[11:81]
rank=[]
for th in (8,16,32):
  for tw in (8,16,32,64,128,256):
    tiles=raw.reshape(352//th,th,1024//tw,tw,3).transpose(0,2,1,3,4).reshape(-1,th,tw,3)
    for cols in (640//tw,704//tw,1024//tw):
      if not cols: continue
      rows=(len(tiles)+cols-1)//cols
      z=np.zeros((rows*cols,th,tw,3),dtype=np.uint8);z[:len(tiles)]=tiles
      a=z.reshape(rows,cols,th,tw,3).transpose(0,2,1,3,4).reshape(rows*th,cols*tw,3)
      a=cv2.resize(a,(max(1,cols*tw//4),max(1,rows*th//4)),interpolation=cv2.INTER_AREA)
      for fac in (.8,.9,1.0):
        t=cv2.resize(thumb,None,fx=fac,fy=fac,interpolation=cv2.INTER_AREA)
        if min(a.shape[0]-t.shape[0],a.shape[1]-t.shape[1])<0: continue
        _,v,_,loc=cv2.minMaxLoc(cv2.matchTemplate(a,t,cv2.TM_CCOEFF_NORMED))
        rank.append((round(v,4),tw,th,cols,fac,loc))
print(sorted(rank,reverse=True)[:20])
