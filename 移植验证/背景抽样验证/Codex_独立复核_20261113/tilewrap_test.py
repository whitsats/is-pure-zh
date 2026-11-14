from pathlib import Path
import sys,csv
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import chr_body as c
out=Path(__file__).resolve().parent
indices=[1272,1416,1488,1632,1344,1560,1734,2334,634,334,784,2416,2468,2800,1386]

def png_alpha(a):
    b=a.copy(); b[:,:,3]=np.minimum((a[:,:,3].astype(np.uint16)*255+64)//128,255).astype(np.uint8);return b

def tilewrap(raw):
    hs=c.header_len(raw); recs=c.records(raw,hs)
    px=np.frombuffer(raw,dtype=np.uint8,offset=hs).reshape(-1,1024,4)
    canvas=np.zeros((480,704,4),dtype=np.uint8); tile=0; warnings=[]
    for i,r in enumerate(recs):
        w,h=r['w'],r['h']; seg=np.zeros((h,w,4),dtype=np.uint8)
        if not w or not h or w%32 or h%32: raise ValueError(f'bad dimensions {r}')
        for y in range(0,h,32):
            for x in range(0,w,32):
                sy=(tile//32)*32; sx=(tile%32)*32; tile+=1
                if sy+32>px.shape[0]: raise ValueError('tile beyond buffer')
                seg[y:y+32,x:x+32]=px[sy:sy+32,sx:sx+32]
        if r['end'] and r['end']!=tile: warnings.append(f'record {i}: expected {r["end"]}, actual {tile}')
        x,y=r['x'],r['y']; H=min(h,480-y); W=min(w,704-x)
        if H<=0 or W<=0 or H!=h or W!=w: warnings.append(f'record {i}: out of canvas')
        if H>0 and W>0:
            s=seg[:H,:W]; m=s[:,:,3]>0; canvas[y:y+H,x:x+W][m]=s[m]
    return canvas, warnings, tile, px.size//(32*32*4)

def preview(a, size=(150,150)):
    im=Image.fromarray(png_alpha(a),'RGBA'); im.thumbnail(size,Image.Resampling.LANCZOS)
    bg=Image.new('RGBA',size,(238,238,238,255)); bg.alpha_composite(im,((size[0]-im.width)//2,(size[1]-im.height)//2));return bg.convert('RGB')

sheet=Image.new('RGB',(900,((len(indices)+1)//2)*180),'white'); d=ImageDraw.Draw(sheet)
rows=[]
for n,idx in enumerate(indices):
    try:
        raw=c.entry(idx); new,warn,nt,avail=tilewrap(raw); old,_=c.build(raw); thumb,_,_=c.thumb(idx+1)
        if np.max(new[:,:,3])>128: warn.append('alpha exceeds 128')
        Image.fromarray(png_alpha(new),'RGBA').save(out/f'tilewrap_{idx}.png')
        iou0=c.silhouette_iou(old,thumb[:,:,3]>0);iou1=c.silhouette_iou(new,thumb[:,:,3]>0)
        x=(n%2)*450; y=(n//2)*180
        d.text((x+2,y+2),f'{idx}  old {iou0:.3f} / new {iou1:.3f}   old | new | ref',fill='black')
        for k,a in enumerate((old,new,thumb)):sheet.paste(preview(a),(x+k*150,y+25))
        rows.append([idx,round(iou0,4),round(iou1,4),nt,avail,'; '.join(warn)])
        print(rows[-1])
    except Exception as e:
        rows.append([idx,'ERROR','','','',str(e)]);print(idx,'ERROR',e)
sheet.save(out/'old_new_reference_contact.png')
with (out/'tilewrap_results.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['index','old_iou','new_iou','tiles','available','warnings']);w.writerows(rows)
