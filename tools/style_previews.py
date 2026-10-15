"""강사 자료 없이 코드로 만든 데모를 실제 네 렌더러로 미리보기한다."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from shorts import FF

ROOT = Path(__file__).resolve().parent.parent


def build():
    work = ROOT / "work" / "style_demo"
    work.mkdir(parents=True, exist_ok=True)
    docs = ROOT / "docs" / "styles"
    docs.mkdir(parents=True, exist_ok=True)
    # Schematic presenter; no person, private image, or sample lecture is used.
    img = np.full((1080,1920,3), (67,63,58), dtype=np.uint8)
    for x in range(100,1850,180):
        cv2.rectangle(img,(x,150),(x+80,760),(92,88,80),-1)
    cv2.ellipse(img,(960,850),(270,340),0,0,360,(115,125,136),-1)
    cv2.circle(img,(960,380),125,(180,190,200),-1)
    cv2.putText(img,"SAMPLE / CODE DEMO",(95,100),cv2.FONT_HERSHEY_SIMPLEX,1.3,(230,230,230),2)
    cv2.imencode('.png',img)[1].tofile(str(work/'source.png'))
    subprocess.run([FF,'-nostdin','-v','error','-y','-loop','1','-i',str(work/'source.png'),
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','5','-r','15',
                    '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(work/'source.mp4')],check=True)
    (work/'words.json').write_text(json.dumps({'words':[{'s':.3,'e':1.8,'w':'핵심을'},{'s':1.8,'e':3.8,'w':'쉽게 전달합니다'}]},ensure_ascii=False),encoding='utf-8')
    for number, theme in [(1,'night'),(3,'elearn')]:
        effects = [{'type':'subs','words':'words.json','offset':0,'t0':0,'t1':5,'style':'card' if number==1 else 'flat','one_line':True},
                   {'type':'caption','t0':0,'t1':5,'html':'핵심을 <mark>쉽게 전달</mark>합니다','pos':'top'}]
        if number==3:
            effects.pop()
            effects.extend([
                {'type':'reframe','t0':0,'t1':5,'speaker_x':960,'to_x':1390,'scale':1.1,'top':0,'board_side':'left'},
                {'type':'def','t0':0,'t1':5,'title':'오늘의 핵심','label':'한 번에 한 메시지','x':100,'y':250,'w':850,'lines':[{'t':.4,'html':'핵심을 <b>쉽게 전달</b>합니다'}]}])
            effects.append({'type':'badge','t0':0,'t1':5,'course':'학습 핵심 정리','org':'SAMPLE'})
        spec={'src':'source.mp4','out':f'{number}.mp4','t0':0,'t1':5,'theme':theme,'scene_guard':False,'sfx':False,'effects':effects}
        path=work/f'{number}.json'
        path.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
        subprocess.run([sys.executable,str(ROOT/'tools/landscape.py'),str(path),'--preview','--at','2.5'],check=True)
        shutil.copy2(work/f'{number}_preview.jpg',docs/f'{number}.jpg')
    for number in [2,4]:
        segment={'in':0,'out':5,'layout':'speaker','speaker':{'cx':960,'cy':20,'cw':860},
                 'titles':[{'t':0,'html':'핵심을 <mark>쉽게</mark><br>전달하는 영상','size':92}]}
        if number==4:
            segment.update({'style':'cc','cap_mode':'box','cap_size':80,
                            'fx':[{'type':'chip','t':0,'t1':5,'html':'핵심만 쏙!','x':270,'y':650}],
                            'cam':[{'t':0,'z':1.12,'mode':'cut'}]})
        spec={'src':'source.mp4','words':'words.json','out':f'{number}.mp4','fps':15,'sfx':False,'segments':[segment]}
        path=work/f'{number}.json'
        path.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
        subprocess.run([sys.executable,str(ROOT/'tools/shorts.py'),str(path),'--preview'],check=True)
        shutil.copy2(work/f'{number}_preview.jpg',docs/f'{number}.jpg')
    names=['나이트 스튜디오','기본 쇼츠','한국 이러닝','캡컷식 쇼츠']
    cards=''.join(f'<article><h2>{i}. {n}</h2><p>{"가로 1920×1080" if i in (1,3) else "세로 1080×1920"}</p><img src="{i}.jpg" alt="{n} 실제 렌더러 시안"></article>' for i,n in enumerate(names,1))
    (docs/'index.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>대표 양식 4종</title><style>body{font:16px sans-serif;background:#17191d;color:#fff;margin:32px}main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}article{background:#252932;padding:20px;border-radius:16px}img{width:100%;height:450px;object-fit:contain}p{color:#c8cbd2}@media(max-width:750px){main{grid-template-columns:1fr}}</style><h1>대표 양식 4종 — 이미지로 고르기</h1><p>실제 렌더러로 만든 도식 데모입니다. 강사 자료가 필요 없습니다. 인물·발언·사진을 재현하지 않습니다.</p><main>'+cards+'</main></html>',encoding='utf-8')
    print(docs/'index.html')
    return work


if __name__=='__main__':
    build()
