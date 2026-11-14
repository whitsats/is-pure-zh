from pathlib import Path
import cv2
import numpy as np

p=Path(__file__).parent/'提取测试'
a=cv2.imdecode(np.fromfile(p/'BG_012_stride1024.png',dtype=np.uint8),cv2.IMREAD_COLOR)
t=cv2.imdecode(np.fromfile(p/'BG_013.png',dtype=np.uint8),cv2.IMREAD_COLOR)
t=cv2.resize(t,(640,448),interpolation=cv2.INTER_CUBIC)
s=cv2.SIFT_create(contrastThreshold=0.015)
ka,da=s.detectAndCompute(a,None); kt,dt=s.detectAndCompute(t,None)
pairs=cv2.BFMatcher().knnMatch(dt,da,k=2)
good=[m for m,n in pairs if m.distance < 0.72*n.distance]
print('features',len(kt),len(ka),'good',len(good))
for m in sorted(good,key=lambda m:m.distance)[:30]:
 print('target', tuple(round(x,1) for x in kt[m.queryIdx].pt),'atlas', tuple(round(x,1) for x in ka[m.trainIdx].pt),'scale',round(kt[m.queryIdx].size/ka[m.trainIdx].size,2),'d',round(m.distance))
cv2.imencode('.png',cv2.drawMatches(t,kt,a,ka,good[:40],None,flags=2))[1].tofile(p/'特征匹配.png')
