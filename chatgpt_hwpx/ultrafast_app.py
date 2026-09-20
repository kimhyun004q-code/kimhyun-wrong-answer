from __future__ import annotations
import ctypes, os, re, sys, tempfile, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import ultrafast_core as core
import ultrafast_tikz as tikz

CF_UNICODETEXT=13

def message(text:str,error:bool=False):
    if os.name=='nt':
        ctypes.windll.user32.MessageBoxW(None,text,'GPT → HWPX 초고속',0x10 if error else 0x40)
    else:
        print(text,file=sys.stderr if error else sys.stdout)

def clipboard_text()->str:
    if os.name!='nt': return ''
    u=ctypes.windll.user32; k=ctypes.windll.kernel32
    u.OpenClipboard.argtypes=[ctypes.c_void_p]; u.OpenClipboard.restype=ctypes.c_bool
    u.CloseClipboard.argtypes=[]; u.CloseClipboard.restype=ctypes.c_bool
    u.GetClipboardData.argtypes=[ctypes.c_uint]; u.GetClipboardData.restype=ctypes.c_void_p
    k.GlobalLock.argtypes=[ctypes.c_void_p]; k.GlobalLock.restype=ctypes.c_void_p
    k.GlobalUnlock.argtypes=[ctypes.c_void_p]; k.GlobalUnlock.restype=ctypes.c_bool
    for _ in range(10):
        if u.OpenClipboard(None):
            try:
                h=u.GetClipboardData(CF_UNICODETEXT)
                if not h:return ''
                p=k.GlobalLock(h)
                if not p:return ''
                try:return ctypes.wstring_at(p)
                finally:k.GlobalUnlock(h)
            finally:u.CloseClipboard()
        time.sleep(.03)
    return ''

def desktop_dir()->Path:
    if os.name=='nt':
        try:
            import winreg
            q=winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders')
            v,_=winreg.QueryValueEx(q,'Desktop');winreg.CloseKey(q)
            return Path(os.path.expandvars(v))
        except Exception: pass
    return Path.home()/'Desktop'

def _candidate_answer(s:str)->bool:
    s=s.strip()
    return bool(s) and len(s)<=80 and not re.fullmatch(r'\[[^\]]+\]',s)

def normalize_answer_first(raw:str)->tuple[str,str]:
    text=raw.replace('\r\n','\n').replace('\r','\n').strip(); answer=''
    tagged=re.findall(r'\[\[ANSWER\]\](.*?)\[\[/ANSWER\]\]',text,flags=re.S|re.I)
    for item in tagged:
        val=' '.join(x.strip() for x in item.splitlines() if x.strip())
        if val:answer=val
    text=re.sub(r'\[\[ANSWER\]\].*?\[\[/ANSWER\]\]','\n',text,flags=re.S|re.I)
    lines=text.split('\n'); kept=[]; i=0
    while i<len(lines):
        m=re.match(r'^\s*\[정답\]\s*(.*?)\s*$',lines[i])
        if m:
            val=m.group(1).strip()
            if val: answer=answer or val; i+=1; continue
            j=i+1
            while j<len(lines) and not lines[j].strip():j+=1
            if not answer and j<len(lines) and lines[j].strip()!='[해설]' and _candidate_answer(lines[j]):
                answer=lines[j].strip(); i=j+1; continue
            i+=1; continue
        kept.append(lines[i]); i+=1
    text='\n'.join(kept)
    if not answer:
        m=re.search(r'(?ms)^\s*\[해설\]\s*\n\s*([^\n]+?)\s*\n\s*\[해설\]\s*$',text)
        if m and _candidate_answer(m.group(1)):
            answer=m.group(1).strip(); text=text[:m.start()]+'\n[해설]\n'+text[m.end():]
    if not answer:
        boxes=re.findall(r'\\boxed\s*\{([^{}]{1,80})\}',text)
        if boxes:answer=boxes[-1].strip()
    if not answer:
        m=re.search(r'(?im)^\s*정답\s*(?:은|:|：)?\s*`?([^`\n]{1,60})`?',text)
        if m and _candidate_answer(m.group(1)):
            answer=m.group(1).strip().rstrip('.')
    # 객관식은 실제 값/해설을 제거하고 선택 번호만 남긴다.
    circled=re.search(r'[①②③④⑤]', answer)
    if circled:
        answer=circled.group(0)
    if not answer:answer='정답 확인 필요'
    text=re.sub(r'(?im)^\s*\[해설\]\s*$','',text)
    text=re.sub(r'(?im)^\s*\[정답\]\s*$','',text)
    text=re.sub(r'\n{3,}','\n\n',text).strip()
    normalized=f'[정답] {answer}\n[해설]'
    if text:normalized+='\n'+text
    return normalized,answer

def output_path(folder:Path|None=None)->Path:
    d=folder or desktop_dir()/'GPT_HWPX';d.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S'); p=d/f'GPT해설_{stamp}.hwpx';n=2
    while p.exists():p=d/f'GPT해설_{stamp}_{n}.hwpx';n+=1
    return p

def convert(raw:str,target:Path,validate:bool=False)->Path:
    # All normalizations happen once, in-process. No nested EXEs.
    text,_=normalize_answer_first(raw)
    text=core.normalize_geometry_text(text)
    normalized,blocks=tikz.preprocess_tags(text)
    # Direct HWPX creation is the hot fast path.
    core.make_hwpx(normalized,target)
    if blocks:
        with tempfile.TemporaryDirectory(prefix='gpt_hwpx_tikz_') as td:
            wd=Path(td)
            # TeX compilation is independent; use up to 2 workers for multiple figures.
            if len(blocks)>1:
                with ThreadPoolExecutor(max_workers=min(2,len(blocks))) as ex:
                    blocks=list(ex.map(lambda b:tikz.render_tikz(b,wd,prefer_vector=True,dpi=360),blocks))
            else:
                tikz.render_tikz(blocks[0],wd,prefer_vector=True,dpi=360)
            logs=[]; tikz.inject_tikz_images(target,blocks,logs)
            errors=[x for x in blocks if x.error]
            if errors:
                target.with_name(target.stem+'_TikZ오류.txt').write_text('\n'.join(f'[{b.index}] {b.error}' for b in errors),encoding='utf-8')
    if validate:
        with zipfile.ZipFile(target) as z:
            bad=z.testzip()
            if bad:raise RuntimeError('HWPX ZIP 오류: '+bad)
    return target

def main(argv:list[str])->int:
    test_input=None; outdir=None; no_open=False; validate=False; i=0
    while i<len(argv):
        if argv[i]=='--test-input' and i+1<len(argv):test_input=Path(argv[i+1]);i+=2;continue
        if argv[i]=='--output-dir' and i+1<len(argv):outdir=Path(argv[i+1]);i+=2;continue
        if argv[i]=='--no-open':no_open=True;i+=1;continue
        if argv[i]=='--validate':validate=True;i+=1;continue
        i+=1
    try:
        raw=test_input.read_text(encoding='utf-8-sig') if test_input else clipboard_text()
        if not raw.strip():message('ChatGPT 응답을 먼저 복사(Ctrl+C)한 뒤 다시 실행해주세요.',True);return 2
        out=output_path(outdir); t0=time.perf_counter();convert(raw,out,validate=validate);elapsed=time.perf_counter()-t0
        if not no_open and os.name=='nt':
            try:os.startfile(str(out))
            except Exception:pass
        if test_input:print(f'{out}\t{elapsed:.4f}s')
        return 0
    except Exception as e:
        message(str(e),True);return 1

if __name__=='__main__':raise SystemExit(main(sys.argv[1:]))