import os, sys, shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core import APP_TITLE, EVAL_AREAS, analyze, fill_workbook
try:
    from build_version import APP_VERSION
except Exception:
    APP_VERSION = '0.0.0'
try:
    from updater import check_and_update_async
except Exception:
    check_and_update_async = None

TEMPLATE_NAMES = ['등수 성적 처리기본틀 수정 2026.xlsx', 'template.xlsx']


def program_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_template() -> str:
    dirs = [program_dir(), Path.cwd()]
    for d in dirs:
        for name in TEMPLATE_NAMES:
            p = d / name
            if p.is_file():
                return str(p)
    raise FileNotFoundError(
        '성적처리 기본틀을 찾지 못했습니다.\n\n'
        '프로그램과 같은 폴더에\n'
        '「등수 성적 처리기본틀 수정 2026.xlsx」를 두어 주세요.\n'
        '한 번만 같이 두면 이후에는 HWPX만 넣으면 됩니다.'
    )


def default_output_paths(hwpx_path: str):
    p = Path(hwpx_path)
    return (
        str(p.with_name(p.stem + '_성적처리.xlsx')),
        str(p.with_name(p.stem + '_시험분석.hwpx')),
    )


def gui_main():
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        root = TkinterDnD.Tk(); dnd = True
    except Exception:
        root = tk.Tk(); DND_FILES = None; dnd = False

    root.title(f'{APP_TITLE}  v{APP_VERSION}')
    root.geometry('980x740'); root.minsize(860,620)
    root.option_add('*Font', ('Malgun Gothic', 10))

    hwpx_var = tk.StringVar()
    status = tk.StringVar(value='HWPX 시험지 하나만 넣으면 됩니다.')
    rows_state = []

    for arg in sys.argv[1:]:
        if arg.lower().endswith('.hwpx'):
            hwpx_var.set(arg)

    top = ttk.Frame(root, padding=12); top.pack(fill='x')
    ttk.Label(top, text='시험지 HWPX').grid(row=0,column=0,sticky='w',pady=4)
    ttk.Entry(top,textvariable=hwpx_var,width=82).grid(row=0,column=1,sticky='ew',padx=8)
    ttk.Button(top,text='찾기',command=lambda: hwpx_var.set(filedialog.askopenfilename(filetypes=[('HWPX','*.hwpx')]) or hwpx_var.get())).grid(row=0,column=2)
    top.columnconfigure(1,weight=1)

    ttk.Label(root, text='성적처리 기본틀은 프로그램 폴더에 고정해 둡니다. 이후 HWPX만 넣으면 XLSX와 HWPX 결과본을 같은 폴더에 만듭니다.', padding=(12,4)).pack(fill='x')

    if dnd:
        drop = tk.Label(root,text='HWPX 파일을 여기로 드래그하세요',relief='groove',bd=2,height=3,font=('Malgun Gothic',11,'bold'))
        drop.pack(fill='x',padx=12,pady=(4,6)); drop.drop_target_register(DND_FILES)
        def on_drop(ev):
            for fp in root.tk.splitlist(ev.data):
                if fp.lower().endswith('.hwpx'):
                    hwpx_var.set(fp); do_analyze(); break
        drop.dnd_bind('<<Drop>>', on_drop)

    btnbar = ttk.Frame(root,padding=(12,6)); btnbar.pack(fill='x')
    frame = ttk.Frame(root,padding=(12,0)); frame.pack(fill='both',expand=True)
    canvas=tk.Canvas(frame,highlightthickness=0); scrollbar=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
    inner=ttk.Frame(canvas); inner.bind('<Configure>',lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0,0),window=inner,anchor='nw'); canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side='left',fill='both',expand=True); scrollbar.pack(side='right',fill='y')

    def render_rows(rows, source):
        nonlocal rows_state
        rows_state=[]
        for w in inner.winfo_children(): w.destroy()
        hdr=['번호','형식','문제유형(자동·수정가능)','평가영역','배점']
        for j,h in enumerate(hdr): ttk.Label(inner,text=h,font=('Malgun Gothic',10,'bold')).grid(row=0,column=j,padx=5,pady=5,sticky='w')
        for i,r in enumerate(rows,1):
            topic=tk.StringVar(value=r['topic']); ev=tk.StringVar(value=r['eval']); score=tk.StringVar(value='' if r['score'] is None else str(r['score']))
            ttk.Label(inner,text=str(r['num']),width=5).grid(row=i,column=0,padx=5,pady=3)
            ttk.Label(inner,text=r['format'],width=8).grid(row=i,column=1,padx=5,pady=3)
            ttk.Entry(inner,textvariable=topic,width=30).grid(row=i,column=2,padx=5,pady=3,sticky='ew')
            ttk.Combobox(inner,textvariable=ev,values=EVAL_AREAS,state='readonly',width=12).grid(row=i,column=3,padx=5,pady=3)
            ttk.Entry(inner,textvariable=score,width=8,state=('disabled' if len(rows)==30 else 'normal')).grid(row=i,column=4,padx=5,pady=3)
            rows_state.append((r,topic,ev,score))
        inner.columnconfigure(2,weight=1)
        status.set(f'{len(rows)}문항 분석 완료 · {source}')

    def do_analyze():
        hp=hwpx_var.get().strip()
        if not os.path.isfile(hp) or not hp.lower().endswith('.hwpx'):
            messagebox.showerror(APP_TITLE,'HWPX 시험지를 선택해 주세요.'); return
        try:
            rows,source=analyze(hp); render_rows(rows,source)
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e))

    def do_save():
        hp=hwpx_var.get().strip()
        if not rows_state:
            do_analyze()
            if not rows_state: return
        reviewed=[]
        try:
            n=len(rows_state)
            for base,tv,ev,sv in rows_state:
                score=None
                if n != 30:
                    score=float(sv.get())
                    if score<=0: raise ValueError(f"{base['num']}번 배점이 올바르지 않습니다.")
                    if abs(score-round(score))<1e-9: score=int(round(score))
                reviewed.append({'num':base['num'],'text':base['text'],'format':base['format'],'topic':tv.get().strip() or '복합유형','eval':ev.get(),'score':score})
            if n != 30:
                total=sum(float(r['score']) for r in reviewed)
                if abs(total-100)>1e-6: raise ValueError(f'배점 합계가 {total:g}점입니다. 100점으로 맞춰 주세요.')

            out_xlsx,out_hwpx=default_output_paths(hp)
            template=find_template()
            fill_workbook(template,hp,reviewed,out_xlsx)
            shutil.copy2(hp,out_hwpx)
            status.set(f'완료: {Path(out_xlsx).name} / {Path(out_hwpx).name}')
            messagebox.showinfo(APP_TITLE,
                '완료했습니다.\n\n'
                f'성적처리 엑셀: {out_xlsx}\n'
                f'HWPX 결과본: {out_hwpx}\n\n'
                '현재 자동업데이트 버전의 HWPX 결과본은 원본 보존 복사본입니다. 시험분석 자동삽입은 다음 단계에서 연결할 수 있습니다.')
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e))

    ttk.Button(btnbar,text='1. HWPX 분석',command=do_analyze).pack(side='left')
    ttk.Button(btnbar,text='2. XLSX + HWPX 생성',command=do_save).pack(side='left',padx=8)
    ttk.Label(btnbar,textvariable=status).pack(side='left',padx=12)

    foot=ttk.Label(root,text='평가영역: 계산 / 이해 / 추론 / 문제해결 / 자료해석   ·   30문항은 기존 배점 유지, 그 외는 총점 100점',padding=12)
    foot.pack(fill='x')

    if check_and_update_async:
        try:
            check_and_update_async(root, APP_VERSION, status)
        except Exception:
            pass
    root.mainloop()

if __name__=='__main__':
    gui_main()
