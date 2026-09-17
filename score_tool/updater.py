import hashlib, json, os, subprocess, sys, tempfile, threading, urllib.request
from pathlib import Path
from tkinter import messagebox

MANIFEST_URL='https://raw.githubusercontent.com/kimhyun004q-code/kimhyun-wrong-answer/main/releases/update.json'


def _ver(v):
    out=[]
    for p in str(v).strip().split('.'):
        try: out.append(int(p))
        except: out.append(0)
    return tuple(out)


def _download(url, path):
    req=urllib.request.Request(url,headers={'User-Agent':'KimHyunMath-Updater'})
    with urllib.request.urlopen(req,timeout=10) as r, open(path,'wb') as f:
        while True:
            b=r.read(1024*1024)
            if not b: break
            f.write(b)


def _sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest().lower()


def _apply_update(downloaded, current):
    script=Path(tempfile.gettempdir())/'kimhyun_math_apply_update.cmd'
    qcur=str(current).replace('%','%%'); qnew=str(downloaded).replace('%','%%')
    script.write_text(
        '@echo off\r\n'
        'chcp 65001 >nul\r\n'
        ':wait\r\n'
        f'move /Y "{qnew}" "{qcur}" >nul 2>nul\r\n'
        'if errorlevel 1 (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'start "" "{qcur}"\r\n'
        'del "%~f0"\r\n', encoding='utf-8')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    subprocess.Popen(['cmd','/c',str(script)],creationflags=flags,close_fds=True)
    os._exit(0)


def check_and_update_async(root, current_version, status_var=None):
    if not getattr(sys,'frozen',False): return
    def worker():
        try:
            req=urllib.request.Request(MANIFEST_URL,headers={'User-Agent':'KimHyunMath-Updater'})
            with urllib.request.urlopen(req,timeout=5) as r:
                manifest=json.loads(r.read().decode('utf-8-sig'))
            remote=str(manifest.get('version','0'))
            if _ver(remote) <= _ver(current_version):
                if status_var: root.after(0,lambda:status_var.set(f'최신 버전 v{current_version} · HWPX를 넣어주세요.'))
                return
            url=manifest['url']; expected=manifest['sha256'].lower()
            tmp=Path(tempfile.gettempdir())/f'kimhyun_math_{remote}.exe'
            if status_var: root.after(0,lambda:status_var.set(f'새 버전 v{remote} 다운로드 중...'))
            _download(url,tmp)
            if _sha256(tmp) != expected:
                try: tmp.unlink()
                except: pass
                raise RuntimeError('업데이트 파일 검증에 실패했습니다.')
            def ask_apply():
                messagebox.showinfo('자동 업데이트',f'새 버전 v{remote}을 받았습니다.\n프로그램을 자동으로 업데이트한 뒤 다시 실행합니다.')
                _apply_update(tmp,Path(sys.executable))
            root.after(0,ask_apply)
        except Exception:
            if status_var:
                root.after(0,lambda:status_var.set(f'오프라인/업데이트 확인 실패 · 현재 버전 v{current_version} 사용'))
    threading.Thread(target=worker,daemon=True).start()
