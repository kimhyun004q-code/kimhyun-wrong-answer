from __future__ import annotations
import os, re, shutil, subprocess, tempfile, zipfile, random
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

HP='http://www.hancom.co.kr/hwpml/2011/paragraph'
HS='http://www.hancom.co.kr/hwpml/2011/section'
HC='http://www.hancom.co.kr/hwpml/2011/core'
OPF='http://www.idpf.org/2007/opf/'
NS={'hp':HP,'hs':HS,'hc':HC,'opf':OPF}
for p,u in [('hp',HP),('hs',HS),('hc',HC),('opf',OPF)]: ET.register_namespace(p,u)

PLACEHOLDER_FMT='GPTTIKZPLACE{:04d}END'

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


def preprocess_tags(text:str):
    """Convert explicit tags to existing converter syntax, extract TikZ as placeholders."""
    text=text.replace('\r\n','\n').replace('\r','\n')
    blocks=[]
    def tikz_repl(m):
        idx=len(blocks)+1
        ph=PLACEHOLDER_FMT.format(idx)
        code=m.group(1).strip()
        blocks.append(TikzBlock(idx,code,ph))
        # Force a dedicated paragraph while keeping exact source order.
        return f'\n{ph}\n'
    text=re.sub(r'\[\[TIKZ\]\](.*?)\[\[/TIKZ\]\]',tikz_repl,text,flags=re.S|re.I)

    def inline_repl(m):
        return '$'+m.group(1).strip()+'$'
    def display_repl(m):
        return '\n$$\n'+m.group(1).strip()+'\n$$\n'
    def answer_repl(m):
        ans=' '.join(m.group(1).strip().splitlines()).strip()
        return f'\n[정답] {ans}\n'
    text=re.sub(r'\[\[INLINE_EQ\]\](.*?)\[\[/INLINE_EQ\]\]',inline_repl,text,flags=re.S|re.I)
    text=re.sub(r'\[\[DISPLAY_EQ\]\](.*?)\[\[/DISPLAY_EQ\]\]',display_repl,text,flags=re.S|re.I)
    text=re.sub(r'\[\[ANSWER\]\](.*?)\[\[/ANSWER\]\]',answer_repl,text,flags=re.S|re.I)
    # Avoid large blank gaps caused by tag blocks.
    text=re.sub(r'\n{3,}','\n\n',text)
    return text.strip(),blocks


def _exe_candidates(name:str):
    found=shutil.which(name)
    if found: yield str(found)
    if os.name=='nt':
        local=Path(os.environ.get('LOCALAPPDATA',''))
        pf=Path(os.environ.get('ProgramFiles','C:/Program Files'))
        pf86=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))
        for base in [local/'Programs/MiKTeX/miktex/bin/x64',pf/'MiKTeX/miktex/bin/x64',pf86/'MiKTeX/miktex/bin/x64']:
            q=base/name
            if q.exists(): yield str(q)
        texroot=Path('C:/texlive')
        if texroot.exists():
            for year in sorted(texroot.glob('20*'),reverse=True):
                for sub in ['bin/windows','bin/win32']:
                    q=year/sub/name
                    if q.exists(): yield str(q)

def find_tex_engine(code:str):
    has_ko=bool(re.search(r'[가-힣]',code))
    order=['xelatex.exe','lualatex.exe','pdflatex.exe'] if has_ko and os.name=='nt' else (['pdflatex.exe','xelatex.exe','lualatex.exe'] if os.name=='nt' else (['xelatex','lualatex','pdflatex'] if has_ko else ['pdflatex','xelatex','lualatex']))
    for name in order:
        for q in _exe_candidates(name): return q
    return None


def build_tex_document(code:str, engine_name:str):
    # If user/model gave only TikZ body, wrap it. If it already includes tikzpicture, retain it.
    body=code.strip()
    if r'\begin{tikzpicture}' not in body:
        body='\\begin{tikzpicture}\n'+body+'\n\\end{tikzpicture}'
    unicode_engine=Path(engine_name).name.lower() in ('xelatex','xelatex.exe','lualatex','lualatex.exe')
    font=''
    if unicode_engine:
        # Font choice is guarded; Korean labels are discouraged but supported when available.
        font=r'''
\usepackage{fontspec}
\IfFontExistsTF{Malgun Gothic}{\setmainfont{Malgun Gothic}}{}
'''
    return rf'''\documentclass[tikz,border=2pt]{{standalone}}
\usepackage{{tikz}}
\usetikzlibrary{{calc,intersections,angles,quotes,arrows.meta,patterns,positioning,decorations.pathreplacing}}
{font}
\begin{{document}}
{body}
\end{{document}}
'''


def render_tikz(block:TikzBlock, workdir:Path, prefer_vector=True, dpi=360):
    engine=find_tex_engine(block.code)
    if not engine:
        block.error='TikZ 그림을 만들려면 TeX Live 또는 MiKTeX 설치가 필요합니다.'
        return block
    d=workdir/f'tikz_{block.index:04d}'; d.mkdir(parents=True,exist_ok=True)
    tex=d/'figure.tex'; tex.write_text(build_tex_document(block.code,engine),encoding='utf-8')
    cmd=[engine,'-interaction=nonstopmode','-halt-on-error','-file-line-error',tex.name]
    r=subprocess.run(cmd,cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',timeout=90,creationflags=(0x08000000 if os.name=='nt' else 0))
    (d/'compile_stdout.txt').write_text(r.stdout,encoding='utf-8')
    pdf=d/'figure.pdf'
    if r.returncode!=0 or not pdf.exists():
        block.error=f'LaTeX 컴파일 실패 (코드 {r.returncode})'
        return block

    # PDF physical dimensions -> HWPUNIT (1 pt = 100 HWPUNIT).
    try:
        import pymupdf as fitz
        doc=fitz.open(pdf); page=doc[0]
        block.natural_w=max(1,int(round(page.rect.width*100)))
        block.natural_h=max(1,int(round(page.rect.height*100)))
        doc.close()
    except Exception:
        block.natural_w=20000; block.natural_h=12000

    # Vector first when Inkscape is available; EMF is stable in desktop Hangul.
    if prefer_vector:
        inkscape=shutil.which('inkscape') or shutil.which('inkscape.exe')
        if inkscape:
            emf=d/'figure.emf'
            rr=subprocess.run([inkscape,str(pdf),'--export-type=emf',f'--export-filename={emf}'],cwd=d,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',timeout=60,creationflags=(0x08000000 if os.name=='nt' else 0))
            (d/'inkscape_stdout.txt').write_text(rr.stdout or '',encoding='utf-8')
            if rr.returncode==0 and emf.exists() and emf.stat().st_size>100:
                block.image_path=emf; block.media_type='image/x-emf'; return block

    # Guaranteed fallback: high-resolution PNG via PyMuPDF.
    try:
        import pymupdf as fitz
        doc=fitz.open(pdf); page=doc[0]
        scale=dpi/72.0
        pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=True)
        png=d/'figure.png'; pix.save(png); doc.close()
        block.image_path=png; block.media_type='image/png'; return block
    except Exception as e:
        block.error=f'PNG 변환 실패: {e}'
        return block


def _text_width_and_columns(section_root):
    secpr=section_root.find('.//hp:secPr',NS)
    pagepr=section_root.find('.//hp:pagePr',NS)
    margin=section_root.find('.//hp:pagePr/hp:margin',NS)
    if pagepr is None or margin is None:
        return 42520,1
    pw=int(pagepr.get('width','59528'))
    left=int(margin.get('left','8504')); right=int(margin.get('right','8504'))
    content=max(1000,pw-left-right)
    colpr=section_root.find('.//hp:colPr',NS)
    cols=max(1,int(colpr.get('colCount','1'))) if colpr is not None else 1
    gap=int(secpr.get('spaceColumns','1134')) if secpr is not None else 1134
    colw=max(1000,(content-gap*(cols-1))//cols)
    return colw,cols


def _scaled_size(nw,nh,colw):
    if nw<=0 or nh<=0:return int(colw*.72),int(colw*.45)
    maxw=int(colw*.86)
    minw=int(colw*.48)
    tw=min(nw,maxw)
    if tw<minw:tw=minw
    th=max(1,int(round(nh*tw/nw)))
    # avoid pathological tall figures
    maxh=int(colw*1.10)
    if th>maxh:
        th=maxh; tw=max(1,int(round(nw*th/nh)))
    return tw,th


def _picture_run(block:TikzBlock,image_id:str,pic_id:int,z:int,colw:int):
    nw,nh=max(1,block.natural_w),max(1,block.natural_h)
    w,h=_scaled_size(nw,nh,colw)
    run=ET.Element(f'{{{HP}}}run',{'charPrIDRef':'0'})
    pic=ET.SubElement(run,f'{{{HP}}}pic',{
        'id':str(pic_id),'zOrder':str(z),'numberingType':'PICTURE','textWrap':'TOP_AND_BOTTOM','textFlow':'BOTH_SIDES',
        'lock':'0','dropcapstyle':'None','href':'','groupLevel':'0','instid':str(pic_id+7000),'reverse':'0'
    })
    ET.SubElement(pic,f'{{{HP}}}offset',{'x':'0','y':'0'})
    ET.SubElement(pic,f'{{{HP}}}orgSz',{'width':str(nw),'height':str(nh)})
    ET.SubElement(pic,f'{{{HP}}}curSz',{'width':str(w),'height':str(h)})
    ET.SubElement(pic,f'{{{HP}}}flip',{'horizontal':'0','vertical':'0'})
    ET.SubElement(pic,f'{{{HP}}}rotationInfo',{'angle':'0','centerX':str(w//2),'centerY':str(h//2),'rotateimage':'0'})
    ri=ET.SubElement(pic,f'{{{HP}}}renderingInfo')
    ET.SubElement(ri,f'{{{HC}}}transMatrix',{'e1':'1','e2':'0','e3':'0','e4':'0','e5':'1','e6':'0'})
    sx=w/nw; sy=h/nh
    ET.SubElement(ri,f'{{{HC}}}scaMatrix',{'e1':f'{sx:.8f}','e2':'0','e3':'0','e4':'0','e5':f'{sy:.8f}','e6':'0'})
    ET.SubElement(ri,f'{{{HC}}}rotMatrix',{'e1':'1','e2':'0','e3':'0','e4':'0','e5':'1','e6':'0'})
    ir=ET.SubElement(pic,f'{{{HP}}}imgRect')
    for tag,x,y in [('pt0',0,0),('pt1',nw,0),('pt2',nw,nh),('pt3',0,nh)]:
        ET.SubElement(ir,f'{{{HC}}}{tag}',{'x':str(x),'y':str(y)})
    ET.SubElement(pic,f'{{{HP}}}imgClip',{'left':'0','right':str(nw),'top':'0','bottom':str(nh)})
    ET.SubElement(pic,f'{{{HP}}}inMargin',{'left':'0','right':'0','top':'0','bottom':'0'})
    ET.SubElement(pic,f'{{{HP}}}imgDim',{'dimwidth':str(nw),'dimheight':str(nh)})
    ET.SubElement(pic,f'{{{HC}}}img',{'binaryItemIDRef':image_id,'bright':'0','contrast':'0','effect':'REAL_PIC','alpha':'0'})
    ET.SubElement(pic,f'{{{HP}}}effects')
    ET.SubElement(pic,f'{{{HP}}}sz',{'width':str(w),'widthRelTo':'ABSOLUTE','height':str(h),'heightRelTo':'ABSOLUTE','protect':'0'})
    ET.SubElement(pic,f'{{{HP}}}pos',{
        'treatAsChar':'0','affectLSpacing':'0','flowWithText':'1','allowOverlap':'0','holdAnchorAndSO':'0',
        'vertRelTo':'PARA','horzRelTo':'COLUMN','vertAlign':'TOP','horzAlign':'CENTER','vertOffset':'0','horzOffset':'0'
    })
    ET.SubElement(pic,f'{{{HP}}}outMargin',{'left':'0','right':'0','top':'120','bottom':'120'})
    sc=ET.SubElement(pic,f'{{{HP}}}shapeComment'); sc.text='TikZ 해설 그림입니다.'
    ET.SubElement(run,f'{{{HP}}}t')
    return run


def _add_manifest_item(content_hpf:bytes,image_id:str,href:str,media_type:str):
    root=ET.fromstring(content_hpf)
    manifest=root.find(f'{{{OPF}}}manifest')
    if manifest is None: raise ValueError('content.hpf manifest 없음')
    ET.SubElement(manifest,f'{{{OPF}}}item',{'id':image_id,'href':href,'media-type':media_type,'isEmbeded':'1'})
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def inject_tikz_images(hwpx_path:Path, blocks:list[TikzBlock], log_lines:list[str]):
    with zipfile.ZipFile(hwpx_path,'r') as zin:
        infos=zin.infolist(); data={i.filename:zin.read(i.filename) for i in infos}
    sec=ET.fromstring(data['Contents/section0.xml'])
    colw,cols=_text_width_and_columns(sec)
    log_lines.append(f'문서 단 수={cols}, 계산 단폭={colw} HWPUNIT')

    # Collect current IDs.
    existing_imgs=[]
    try:
        ch=ET.fromstring(data['Contents/content.hpf'])
        for x in ch.findall(f'.//{{{OPF}}}item'):
            if (x.get('id') or '').startswith('image'): existing_imgs.append(x.get('id'))
    except Exception: pass
    nums=[int(m.group(1)) for s in existing_imgs if (m:=re.fullmatch(r'image(\d+)',s or ''))]
    next_img=max(nums+[0])+1
    pic_id=1900000000; z=100
    additions=[]

    for b in blocks:
        # Find paragraph containing placeholder.
        para=None
        for p in sec.findall('.//hp:p',NS):
            txt=''.join((t.text or '') for t in p.findall('.//hp:t',NS))
            if b.placeholder in txt:
                para=p; break
        if para is None:
            log_lines.append(f'[{b.index}] 자리표시자 문단을 찾지 못함')
            continue
        if b.error or not b.image_path:
            # Keep rest of conversion alive; replace marker with readable small error text.
            for t in para.findall('.//hp:t',NS):
                if t.text and b.placeholder in t.text:
                    t.text=t.text.replace(b.placeholder,f'[TikZ 그림 생성 실패: {b.index}번]')
            log_lines.append(f'[{b.index}] 실패: {b.error}')
            continue
        image_id=f'image{next_img}'; next_img+=1
        ext=b.image_path.suffix.lower()
        href=f'BinData/{image_id}{ext}'
        additions.append((href,b.image_path.read_bytes()))
        data['Contents/content.hpf']=_add_manifest_item(data['Contents/content.hpf'],image_id,href,b.media_type or 'image/png')

        # Replace all ordinary runs in that dedicated placeholder paragraph.
        for child in list(para):
            if child.tag==f'{{{HP}}}run': para.remove(child)
        para.insert(0,_picture_run(b,image_id,pic_id,z,colw)); pic_id+=1; z+=1
        log_lines.append(f'[{b.index}] 삽입 성공: {href}, natural={b.natural_w}x{b.natural_h}')

    data['Contents/section0.xml']=ET.tostring(sec,encoding='utf-8',xml_declaration=True)
    # Remove internal markers/tags from preview text as well.
    if 'Preview/PrvText.txt' in data:
        prv=data['Preview/PrvText.txt'].decode('utf-8',errors='replace')
        for b in blocks: prv=prv.replace(b.placeholder,'[그림]')
        prv=re.sub(r'\[\[(?:TIKZ|INLINE_EQ|DISPLAY_EQ|ANSWER)\]\]|\[\[/(?:TIKZ|INLINE_EQ|DISPLAY_EQ|ANSWER)\]\]','',prv,flags=re.I)
        data['Preview/PrvText.txt']=prv.encode('utf-8')

    tmp=hwpx_path.with_suffix('.tikz.tmp.hwpx')
    with zipfile.ZipFile(tmp,'w') as zout:
        for info in infos:
            zi=zipfile.ZipInfo(info.filename,date_time=info.date_time)
            zi.external_attr=info.external_attr; zi.create_system=info.create_system
            zi.compress_type=zipfile.ZIP_STORED if info.filename=='mimetype' else zipfile.ZIP_DEFLATED
            zout.writestr(zi,data[info.filename])
        for href,blob in additions:
            zout.writestr(href,blob,compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp,hwpx_path)


def validate_hwpx(path:Path, blocks:list[TikzBlock]):
    with zipfile.ZipFile(path) as z:
        bad=z.testzip()
        if bad: raise ValueError('ZIP CRC 오류: '+bad)
        names=set(z.namelist())
        for n in names:
            if n.lower().endswith(('.xml','.hpf')):
                ET.fromstring(z.read(n))
        sec=z.read('Contents/section0.xml').decode('utf-8',errors='replace')
        if '[[TIKZ]]' in sec or 'GPTTIKZPLACE' in sec:
            raise ValueError('TikZ 태그/자리표시자가 최종 section에 남음')
        hpf=ET.fromstring(z.read('Contents/content.hpf'))
        manifest={x.get('id'):(x.get('href'),x.get('media-type')) for x in hpf.findall(f'.//{{{OPF}}}item')}
        root=ET.fromstring(z.read('Contents/section0.xml'))
        for img in root.findall('.//hc:img',NS):
            rid=img.get('binaryItemIDRef')
            if rid and rid.startswith('image'):
                if rid not in manifest: raise ValueError(f'manifest 누락: {rid}')
                href,_=manifest[rid]
                if href not in names: raise ValueError(f'BinData 누락: {href}')
    return True