from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import winreg
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

HP='http://www.hancom.co.kr/hwpml/2011/paragraph'
HS='http://www.hancom.co.kr/hwpml/2011/section'
HC='http://www.hancom.co.kr/hwpml/2011/core'
OPF='http://www.idpf.org/2007/opf/'
NS={'hp':HP,'hs':HS,'hc':HC,'opf':OPF}
for p,u in [('hp',HP),('hs',HS),('hc',HC),('opf',OPF)]: ET.register_namespace(p,u)

PLACEHOLDER_FMT='GPTTIKZPLACE{:04d}END'
CREATE_NO_WINDOW=0x08000000

@dataclass
class TikzBlock:
    index:int
    code:str
    placeholder:str
    image_path:Path|None=None
    media_type:str|None=None
    natural_w:int=0
    natural_h:int=0
    error:str|None=None


def resource(name:str)->Path:
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/name


def desktop_dir()->Path:
    try:
        q=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders')
        v,_=winreg.QueryValueEx(q,'Desktop'); winreg.CloseKey(q)
        return Path(os.path.expandvars(v))
    except Exception:
        return Path.home()/'Desktop'


def preprocess_tags(text:str):
    text=text.replace('\r\n','\n').replace('\r','\n')
    blocks=[]
    def tikz_repl(m):
        idx=len(blocks)+1; ph=PLACEHOLDER_FMT.format(idx)
        blocks.append(TikzBlock(idx,m.group(1).strip(),ph))
        return f'\n{ph}\n'
    text=re.sub(r'\[\[TIKZ\]\](.*?)\[\[/TIKZ\]\]',tikz_repl,text,flags=re.S|re.I)
    text=re.sub(r'\[\[INLINE_EQ\]\](.*?)\[\[/INLINE_EQ\]\]',lambda m:'$'+m.group(1).strip()+'$',text,flags=re.S|re.I)
    text=re.sub(r'\[\[DISPLAY_EQ\]\](.*?)\[\[/DISPLAY_EQ\]\]',lambda m:'\n$$\n'+m.group(1).strip()+'\n$$\n',text,flags=re.S|re.I)
    text=re.sub(r'\[\[ANSWER\]\](.*?)\[\[/ANSWER\]\]',lambda m:'\n[정답] '+' '.join(m.group(1).strip().splitlines())+'\n',text,flags=re.S|re.I)
    text=re.sub(r'\n{3,}','\n\n',text)
    for b in blocks:
        text=re.sub(r'\n\s*\n('+re.escape(b.placeholder)+r')\n\s*\n',r'\n\1\n',text)
    return text.strip(),blocks


def _exe_candidates(name:str):
    found=shutil.which(name)
    if found: yield Path(found)
    local=Path(os.environ.get('LOCALAPPDATA',''))
    pf=Path(os.environ.get('ProgramFiles','C:/Program Files'))
    pf86=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))
    for base in [local/'Programs/MiKTeX/miktex/bin/x64',pf/'MiKTeX/miktex/bin/x64',pf86/'MiKTeX/miktex/bin/x64']:
        p=base/name
        if p.exists(): yield p
    texroot=Path('C:/texlive')
    if texroot.exists():
        for year in sorted(texroot.glob('20*'),reverse=True):
            for sub in ['bin/windows','bin/win32']:
                p=year/sub/name
                if p.exists(): yield p


def find_tex_engine(code:str):
    has_ko=bool(re.search(r'[가-힣]',code))
    names=['xelatex.exe','lualatex.exe','pdflatex.exe'] if has_ko else ['pdflatex.exe','xelatex.exe','lualatex.exe']
    for name in names:
        for p in _exe_candidates(name): return p
    return None


def find_inkscape():
    p=shutil.which('inkscape.exe')
    if p:return Path(p)
    for base in [Path(os.environ.get('ProgramFiles','C:/Program Files')),Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))]:
        q=base/'Inkscape/bin/inkscape.exe'
        if q.exists():return q
    return None


def build_tex_document(code:str,engine:Path):
    body=code.strip()
    if r'\begin{tikzpicture}' not in body:
        body='\\begin{tikzpicture}\n'+body+'\n\\end{tikzpicture}'
    uni=engine.name.lower() in ('xelatex.exe','lualatex.exe')
    font=''
    if uni:
        font=r'''\usepackage{fontspec}
\IfFontExistsTF{Malgun Gothic}{\setmainfont{Malgun Gothic}}{}'''
    return rf'''\documentclass[tikz,border=2pt]{{standalone}}
\usepackage{{tikz}}
\usetikzlibrary{{calc,intersections,angles,quotes,arrows.meta,patterns,positioning,decorations.pathreplacing}}
{font}
\begin{{document}}
{body}
\end{{document}}
'''


def render_tikz(block:TikzBlock,workdir:Path,log:list[str],prefer_vector=True,dpi=360):
    engine=find_tex_engine(block.code)
    if not engine:
        block.error='TikZ 그림을 만들려면 TeX Live 또는 MiKTeX 설치가 필요합니다.'
        log.append(f'[{block.index}] {block.error}')
        return
    d=workdir/f'tikz_{block.index:04d}'; d.mkdir(parents=True,exist_ok=True)
    tex=d/'figure.tex'; tex.write_text(build_tex_document(block.code,engine),encoding='utf-8')
    log.append(f'[{block.index}] LaTeX 엔진: {engine}')
    try:
        r=subprocess.run([str(engine),'-interaction=nonstopmode','-halt-on-error','-file-line-error',tex.name],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=120,creationflags=CREATE_NO_WINDOW)
    except Exception as e:
        block.error=f'LaTeX 실행 실패: {e}'; log.append(f'[{block.index}] {block.error}'); return
    (d/'compile_stdout.txt').write_text(r.stdout or '',encoding='utf-8')
    pdf=d/'figure.pdf'
    if r.returncode!=0 or not pdf.exists():
        block.error=f'LaTeX 컴파일 실패 (코드 {r.returncode})'; log.append(f'[{block.index}] {block.error}'); return
    try:
        import fitz
        doc=fitz.open(pdf); page=doc[0]
        block.natural_w=max(1,int(round(page.rect.width*100)))
        block.natural_h=max(1,int(round(page.rect.height*100)))
        doc.close()
    except Exception:
        block.natural_w=20000; block.natural_h=12000
    if prefer_vector:
        inkscape=find_inkscape()
        if inkscape:
            emf=d/'figure.emf'
            rr=subprocess.run([str(inkscape),str(pdf),'--export-type=emf',f'--export-filename={emf}'],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=90,creationflags=CREATE_NO_WINDOW)
            (d/'inkscape_stdout.txt').write_text(rr.stdout or '',encoding='utf-8')
            if rr.returncode==0 and emf.exists() and emf.stat().st_size>100:
                block.image_path=emf; block.media_type='image/x-emf'; log.append(f'[{block.index}] EMF 생성 성공'); return
    try:
        import fitz
        doc=fitz.open(pdf); page=doc[0]; scale=dpi/72.0
        pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=True)
        png=d/'figure.png'; pix.save(png); doc.close()
        block.image_path=png; block.media_type='image/png'; log.append(f'[{block.index}] PNG {dpi}dpi 생성 성공')
    except Exception as e:
        block.error=f'PNG 변환 실패: {e}'; log.append(f'[{block.index}] {block.error}')


def _text_width_and_columns(root):
    secpr=root.find('.//hp:secPr',NS); pagepr=root.find('.//hp:pagePr',NS); margin=root.find('.//hp:pagePr/hp:margin',NS)
    if pagepr is None or margin is None:return 42520,1
    pw=int(pagepr.get('width','59528')); left=int(margin.get('left','8504')); right=int(margin.get('right','8504'))
    content=max(1000,pw-left-right); colpr=root.find('.//hp:colPr',NS)
    cols=max(1,int(colpr.get('colCount','1'))) if colpr is not None else 1
    gap=int(secpr.get('spaceColumns','1134')) if secpr is not None else 1134
    return max(1000,(content-gap*(cols-1))//cols),cols


def _scaled_size(nw,nh,colw):
    maxw=int(colw*.86); minw=int(colw*.50); tw=min(max(nw,minw),maxw); th=max(1,int(round(nh*tw/max(1,nw))))
    maxh=int(colw*1.10)
    if th>maxh: th=maxh; tw=max(1,int(round(nw*th/max(1,nh))))
    return tw,th


def _picture_run(block:TikzBlock,image_id:str,pic_id:int,z:int,colw:int):
    nw,nh=max(1,block.natural_w),max(1,block.natural_h); w,h=_scaled_size(nw,nh,colw)
    run=ET.Element(f'{{{HP}}}run',{'charPrIDRef':'0'})
    pic=ET.SubElement(run,f'{{{HP}}}pic',{'id':str(pic_id),'zOrder':str(z),'numberingType':'PICTURE','textWrap':'TOP_AND_BOTTOM','textFlow':'BOTH_SIDES','lock':'0','dropcapstyle':'None','href':'','groupLevel':'0','instid':str(pic_id+7000),'reverse':'0'})
    ET.SubElement(pic,f'{{{HP}}}offset',{'x':'0','y':'0'}); ET.SubElement(pic,f'{{{HP}}}orgSz',{'width':str(nw),'height':str(nh)}); ET.SubElement(pic,f'{{{HP}}}curSz',{'width':str(w),'height':str(h)})
    ET.SubElement(pic,f'{{{HP}}}flip',{'horizontal':'0','vertical':'0'}); ET.SubElement(pic,f'{{{HP}}}rotationInfo',{'angle':'0','centerX':str(w//2),'centerY':str(h//2),'rotateimage':'0'})
    ri=ET.SubElement(pic,f'{{{HP}}}renderingInfo'); ET.SubElement(ri,f'{{{HC}}}transMatrix',{'e1':'1','e2':'0','e3':'0','e4':'0','e5':'1','e6':'0'})
    ET.SubElement(ri,f'{{{HC}}}scaMatrix',{'e1':f'{w/nw:.8f}','e2':'0','e3':'0','e4':'0','e5':f'{h/nh:.8f}','e6':'0'}); ET.SubElement(ri,f'{{{HC}}}rotMatrix',{'e1':'1','e2':'0','e3':'0','e4':'0','e5':'1','e6':'0'})
    ir=ET.SubElement(pic,f'{{{HP}}}imgRect')
    for tag,x,y in [('pt0',0,0),('pt1',nw,0),('pt2',nw,nh),('pt3',0,nh)]: ET.SubElement(ir,f'{{{HC}}}{tag}',{'x':str(x),'y':str(y)})
    ET.SubElement(pic,f'{{{HP}}}imgClip',{'left':'0','right':str(nw),'top':'0','bottom':str(nh)}); ET.SubElement(pic,f'{{{HP}}}inMargin',{'left':'0','right':'0','top':'0','bottom':'0'}); ET.SubElement(pic,f'{{{HP}}}imgDim',{'dimwidth':str(nw),'dimheight':str(nh)})
    ET.SubElement(pic,f'{{{HC}}}img',{'binaryItemIDRef':image_id,'bright':'0','contrast':'0','effect':'REAL_PIC','alpha':'0'}); ET.SubElement(pic,f'{{{HP}}}effects')
    ET.SubElement(pic,f'{{{HP}}}sz',{'width':str(w),'widthRelTo':'ABSOLUTE','height':str(h),'heightRelTo':'ABSOLUTE','protect':'0'})
    ET.SubElement(pic,f'{{{HP}}}pos',{'treatAsChar':'0','affectLSpacing':'0','flowWithText':'1','allowOverlap':'0','holdAnchorAndSO':'0','vertRelTo':'PARA','horzRelTo':'COLUMN','vertAlign':'TOP','horzAlign':'CENTER','vertOffset':'0','horzOffset':'0'})
    ET.SubElement(pic,f'{{{HP}}}outMargin',{'left':'0','right':'0','top':'120','bottom':'120'}); sc=ET.SubElement(pic,f'{{{HP}}}shapeComment'); sc.text='TikZ 해설 그림입니다.'; ET.SubElement(run,f'{{{HP}}}t')
    return run


def _add_manifest_item(blob:bytes,image_id:str,href:str,media_type:str):
    root=ET.fromstring(blob); man=root.find(f'{{{OPF}}}manifest')
    if man is None:raise ValueError('content.hpf manifest를 찾지 못했습니다.')
    ET.SubElement(man,f'{{{OPF}}}item',{'id':image_id,'href':href,'media-type':media_type,'isEmbeded':'1'})
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def inject_tikz_images(path:Path,blocks:list[TikzBlock],log:list[str]):
    with zipfile.ZipFile(path,'r') as zin:
        infos=zin.infolist(); data={i.filename:zin.read(i.filename) for i in infos}
    sec=ET.fromstring(data['Contents/section0.xml']); colw,cols=_text_width_and_columns(sec); log.append(f'단 수={cols}, 자동 단폭={colw} HWPUNIT')
    hpf=ET.fromstring(data['Contents/content.hpf']); ids=[x.get('id','') for x in hpf.findall(f'.//{{{OPF}}}item')]
    nums=[int(m.group(1)) for s in ids if (m:=re.fullmatch(r'image(\d+)',s))]; next_img=max(nums+[0])+1
    additions=[]; pic_id=1900000000; z=100
    for b in blocks:
        para=None
        for p in sec.findall('.//hp:p',NS):
            if b.placeholder in ''.join((t.text or '') for t in p.findall('.//hp:t',NS)):para=p;break
        if para is None:log.append(f'[{b.index}] 그림 위치 자리표시자를 찾지 못했습니다.');continue
        if b.error or not b.image_path:
            for t in para.findall('.//hp:t',NS):
                if t.text and b.placeholder in t.text:t.text=t.text.replace(b.placeholder,f'[TikZ 그림 생성 실패: {b.index}번]')
            continue
        image_id=f'image{next_img}'; next_img+=1; href=f'BinData/{image_id}{b.image_path.suffix.lower()}'
        additions.append((href,b.image_path.read_bytes())); data['Contents/content.hpf']=_add_manifest_item(data['Contents/content.hpf'],image_id,href,b.media_type or 'image/png')
        for c in list(para):
            if c.tag==f'{{{HP}}}run':para.remove(c)
        para.insert(0,_picture_run(b,image_id,pic_id,z,colw)); pic_id+=1; z+=1; log.append(f'[{b.index}] HWPX 그림 삽입 성공: {href}')
    data['Contents/section0.xml']=ET.tostring(sec,encoding='utf-8',xml_declaration=True)
    if 'Preview/PrvText.txt' in data:
        prv=data['Preview/PrvText.txt'].decode('utf-8',errors='replace')
        for b in blocks:prv=prv.replace(b.placeholder,'[그림]' if not b.error else f'[TikZ 그림 생성 실패: {b.index}번]')
        data['Preview/PrvText.txt']=prv.encode('utf-8')
    tmp=path.with_suffix('.tikz.tmp.hwpx')
    with zipfile.ZipFile(tmp,'w') as zout:
        for info in infos:
            zi=zipfile.ZipInfo(info.filename,date_time=info.date_time); zi.external_attr=info.external_attr; zi.create_system=info.create_system; zi.compress_type=zipfile.ZIP_STORED if info.filename=='mimetype' else zipfile.ZIP_DEFLATED
            zout.writestr(zi,data[info.filename])
        for href,blob in additions:zout.writestr(href,blob,compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp,path)


def validate_hwpx(path:Path):
    with zipfile.ZipFile(path) as z:
        bad=z.testzip()
        if bad:raise ValueError('HWPX ZIP CRC 오류: '+bad)
        names=set(z.namelist())
        for n in names:
            if n.lower().endswith(('.xml','.hpf')):ET.fromstring(z.read(n))
        sec=z.read('Contents/section0.xml').decode('utf-8',errors='replace')
        forbidden=['[[TIKZ]]','[[/TIKZ]]','[[INLINE_EQ]]','[[DISPLAY_EQ]]','[[ANSWER]]','GPTTIKZPLACE']
        if any(x in sec for x in forbidden):raise ValueError('변환 태그가 최종 문서에 남아 있습니다.')
        hpf=ET.fromstring(z.read('Contents/content.hpf')); man={x.get('id'):(x.get('href'),x.get('media-type')) for x in hpf.findall(f'.//{{{OPF}}}item')}
        root=ET.fromstring(z.read('Contents/section0.xml'))
        for img in root.findall('.//hc:img',NS):
            rid=img.get('binaryItemIDRef')
            if rid and rid.startswith('image'):
                if rid not in man:raise ValueError('그림 manifest 누락: '+rid)
                href,_=man[rid]
                if href not in names:raise ValueError('그림 BinData 누락: '+str(href))
    return True


def call_existing_converter(normalized:str,outdir:Path):
    inner=resource('GPT_HWPX_원클릭_기하기호보정.exe')
    if not inner.exists():raise RuntimeError('기존 HWPX 변환 엔진을 찾지 못했습니다.')
    outdir.mkdir(parents=True,exist_ok=True)
    before=set(outdir.glob('*.hwpx'))
    src=outdir/'_normalized_input.md'; src.write_text(normalized,encoding='utf-8')
    si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    p=subprocess.run([str(inner),'--test-input',str(src),'--output-dir',str(outdir),'--no-open'],startupinfo=si,creationflags=CREATE_NO_WINDOW,timeout=240)
    if p.returncode!=0:raise RuntimeError(f'기존 HWPX 변환 엔진 실행 실패 (코드 {p.returncode})')
    after=[x for x in outdir.glob('*.hwpx') if x not in before]
    if not after:after=list(outdir.glob('*.hwpx'))
    if not after:raise RuntimeError('HWPX 결과 파일이 생성되지 않았습니다.')
    return max(after,key=lambda p:p.stat().st_mtime)


def convert_all(raw:str,target:Path,prefer_vector=True):
    log=[f'GPT → HWPX TikZ 확장 로그 / {datetime.now():%Y-%m-%d %H:%M:%S}']
    normalized,blocks=preprocess_tags(raw); log.append(f'TikZ 블록 수: {len(blocks)}')
    with tempfile.TemporaryDirectory(prefix='GPT_HWPX_TikZ_') as td:
        td=Path(td); rendered=td/'rendered'; rendered.mkdir()
        for b in blocks:render_tikz(b,rendered,log,prefer_vector=prefer_vector)
        coreout=td/'coreout'; core=call_existing_converter(normalized,coreout)
        inject_tikz_images(core,blocks,log); validate_hwpx(core)
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(core,target)
    validate_hwpx(target); log.append('최종 HWPX 무결성 검사: 통과')
    log_path=target.with_name(target.stem+'_변환로그.txt'); log_path.write_text('\n'.join(log),encoding='utf-8')
    return target,log_path,blocks


def default_output():
    d=desktop_dir()/'GPT_HWPX'; d.mkdir(parents=True,exist_ok=True)
    return d/f'GPT해설_TikZ_{datetime.now():%Y%m%d_%H%M%S}.hwpx'


class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('GPT → HWPX 수식 + TikZ 자동조판'); self.geometry('1040x800'); self.minsize(800,600)
        top=tk.Frame(self,padx=14,pady=10);top.pack(fill='x')
        tk.Label(top,text='GPT → HWPX 수식 + TikZ 자동조판',font=('맑은 고딕',16,'bold')).pack(anchor='w')
        tk.Label(top,text='ChatGPT 응답 전체를 붙여넣으면 본문·수식·TikZ 그림을 원래 순서대로 HWPX에 조판합니다.',font=('맑은 고딕',9)).pack(anchor='w',pady=(4,0))
        bar=tk.Frame(self,padx=14);bar.pack(fill='x')
        tk.Button(bar,text='클립보드에서 가져오기',command=self.from_clipboard,width=20).pack(side='left')
        tk.Button(bar,text='TXT/MD 열기',command=self.open_text,width=13).pack(side='left',padx=6)
        tk.Button(bar,text='비우기',command=lambda:self.text.delete('1.0','end'),width=9).pack(side='left')
        self.vector=tk.BooleanVar(value=True); tk.Checkbutton(bar,text='가능하면 EMF 벡터 사용',variable=self.vector).pack(side='left',padx=12)
        self.go=tk.Button(bar,text='한글로 변환',command=self.start_convert,width=16,font=('맑은 고딕',10,'bold'));self.go.pack(side='right')
        self.text=ScrolledText(self,wrap='word',undo=True,font=('맑은 고딕',11),padx=10,pady=10);self.text.pack(fill='both',expand=True,padx=14,pady=10)
        bottom=tk.Frame(self,padx=14,pady=8);bottom.pack(fill='x');self.status=tk.StringVar(value='준비됨');tk.Label(bottom,textvariable=self.status,anchor='w').pack(fill='x')

    def from_clipboard(self):
        try:s=self.clipboard_get();self.text.delete('1.0','end');self.text.insert('1.0',s);self.status.set('클립보드에서 가져왔습니다.')
        except tk.TclError:messagebox.showwarning('클립보드','텍스트 클립보드가 비어 있습니다.')

    def open_text(self):
        p=filedialog.askopenfilename(filetypes=[('텍스트/마크다운','*.txt *.md'),('모든 파일','*.*')])
        if not p:return
        s=Path(p).read_text(encoding='utf-8-sig');self.text.delete('1.0','end');self.text.insert('1.0',s);self.status.set(Path(p).name+' 불러옴')

    def start_convert(self):
        raw=self.text.get('1.0','end-1c')
        if not raw.strip():messagebox.showwarning('입력 없음','ChatGPT 응답을 먼저 붙여넣어 주세요.');return
        p=filedialog.asksaveasfilename(initialfile=default_output().name,initialdir=default_output().parent,defaultextension='.hwpx',filetypes=[('HWPX 문서','*.hwpx')])
        if not p:return
        self.go.config(state='disabled');self.status.set('변환 중... TikZ가 있으면 LaTeX 컴파일에 잠시 시간이 걸립니다.')
        threading.Thread(target=self._worker,args=(raw,Path(p),self.vector.get()),daemon=True).start()

    def _worker(self,raw,target,prefer_vector):
        try:
            out,log,blocks=convert_all(raw,target,prefer_vector)
            failed=sum(1 for b in blocks if b.error)
            self.after(0,lambda:self._done(out,log,failed))
        except Exception as e:self.after(0,lambda:self._fail(str(e)))

    def _done(self,out,log,failed):
        self.go.config(state='normal');self.status.set('완료: '+str(out))
        note=f'\nTikZ 실패 {failed}개는 문서에 오류 표기로 남기고 나머지는 계속 조판했습니다.' if failed else ''
        messagebox.showinfo('완료',f'HWPX 생성이 완료되었습니다.\n{out}\n\n로그: {log}{note}')
        try:os.startfile(str(out))
        except Exception:pass

    def _fail(self,msg):
        self.go.config(state='normal');self.status.set('오류: '+msg);messagebox.showerror('변환 오류',msg)


def cli_main(args):
    inp=Path(args[0]);out=Path(args[1]);convert_all(inp.read_text(encoding='utf-8-sig'),out,prefer_vector='--png' not in args);print(out);return 0

if __name__=='__main__':
    if len(sys.argv)>=3 and sys.argv[1]=='--cli':raise SystemExit(cli_main(sys.argv[2:]))
    App().mainloop()
