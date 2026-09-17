import os, sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from core import APP_TITLE, EVAL_AREAS, analyze, fill_workbook, default_output_path, run_cli

def gui_main():
    try:
        from tkinterdnd2 import TkinterDnD, DND_FILES
        root = TkinterDnD.Tk()
        dnd_available = True
    except Exception:
        root = tk.Tk()
        DND_FILES = None
        dnd_available = False
    root.title(APP_TITLE); root.geometry('980x720'); root.minsize(860,620)
    root.option_add('*Font', ('Malgun Gothic', 10))
    hwpx_var=tk.StringVar(); xlsx_var=tk.StringVar(); status=tk.StringVar(value="HWPX와 성적 엑셀을 선택하세요.")
    rows_state=[]

    for arg in sys.argv[1:]:
        lo=arg.lower()
        if lo.endswith('.hwpx'): hwpx_var.set(arg)
        elif lo.endswith('.xlsx'): xlsx_var.set(arg)

    top=ttk.Frame(root,padding=12); top.pack(fill='x')
    ttk.Label(top,text="HWPX 시험지").grid(row=0,column=0,sticky='w',pady=4)
    ttk.Entry(top,textvariable=hwpx_var,width=82).grid(row=0,column=1,sticky='ew',padx=8)
    ttk.Button(top,text="찾기",command=lambda: hwpx_var.set(filedialog.askopenfilename(filetypes=[('HWPX','*.hwpx')]) or hwpx_var.get())).grid(row=0,column=2)
    ttk.Label(top,text="성적 엑셀").grid(row=1,column=0,sticky='w',pady=4)
    ttk.Entry(top,textvariable=xlsx_var,width=82).grid(row=1,column=1,sticky='ew',padx=8)
    ttk.Button(top,text="찾기",command=lambda: xlsx_var.set(filedialog.askopenfilename(filetypes=[('Excel','*.xlsx')]) or xlsx_var.get())).grid(row=1,column=2)
    top.columnconfigure(1,weight=1)

    note=ttk.Label(root,text="테스트 시트의 학생별 이름·정오 입력은 직접 입력합니다. 프로그램은 테스트정보와 계산파트를 자동 구성합니다.\n평가영역은 계산 / 이해 / 추론 / 문제해결 / 자료해석 5영역이며 아래에서 수정할 수 있습니다.",padding=(12,4))
    note.pack(fill='x')

    if dnd_available:
        drop = tk.Label(root, text="HWPX + XLSX 두 파일을 여기로 드래그하세요", relief='groove', bd=2, height=2, font=('Malgun Gothic',10,'bold'))
        drop.pack(fill='x', padx=12, pady=(4,2))
        drop.drop_target_register(DND_FILES)
        def on_drop(ev):
            for fp in root.tk.splitlist(ev.data):
                lo=fp.lower()
                if lo.endswith('.hwpx'): hwpx_var.set(fp)
                elif lo.endswith('.xlsx'): xlsx_var.set(fp)
        drop.dnd_bind('<<Drop>>', on_drop)

    btnbar=ttk.Frame(root,padding=(12,6)); btnbar.pack(fill='x')
    frame=ttk.Frame(root,padding=(12,0)); frame.pack(fill='both',expand=True)
    canvas=tk.Canvas(frame,highlightthickness=0); scrollbar=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
    inner=ttk.Frame(canvas); inner.bind('<Configure>',lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0,0),window=inner,anchor='nw'); canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side='left',fill='both',expand=True); scrollbar.pack(side='right',fill='y')

    def render_rows(rows, source):
        nonlocal rows_state
        rows_state=[]
        for w in inner.winfo_children(): w.destroy()
        hdr=["번호","형식","문제유형(자동·수정가능)","평가영역","배점"]
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
        status.set(f"{len(rows)}문항 분석 완료 · {source}")

    def do_analyze():
        hp=hwpx_var.get().strip(); xp=xlsx_var.get().strip()
        if not os.path.isfile(hp) or not hp.lower().endswith('.hwpx'):
            messagebox.showerror(APP_TITLE,"HWPX 시험지를 선택해 주세요."); return
        if not os.path.isfile(xp) or not xp.lower().endswith('.xlsx'):
            messagebox.showerror(APP_TITLE,"성적 XLSX를 선택해 주세요."); return
        try:
            rows,source=analyze(hp)
            render_rows(rows,source)
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e))

    def do_save():
        if not rows_state:
            do_analyze()
            if not rows_state: return
        hp=hwpx_var.get().strip(); xp=xlsx_var.get().strip()
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
            if n != 30 and abs(sum(float(r['score']) for r in reviewed)-100) > 1e-6:
                raise ValueError(f"배점 합계가 {sum(float(r['score']) for r in reviewed):g}점입니다. 100점으로 맞춰 주세요.")
            default=default_output_path(xp)
            out=filedialog.asksaveasfilename(defaultextension='.xlsx',initialfile=Path(default).name,initialdir=str(Path(default).parent),filetypes=[('Excel','*.xlsx')])
            if not out: return
            fill_workbook(xp,hp,reviewed,out)
            status.set(f"완료: {out}")
            messagebox.showinfo(APP_TITLE,f"자동완성 파일을 저장했습니다.\n\n{out}\n\n테스트 시트에 학생별 이름과 정오(오답=1)를 입력하면 점수·등수·정답률이 계산됩니다.")
        except Exception as e:
            messagebox.showerror(APP_TITLE,str(e))

    ttk.Button(btnbar,text="1. HWPX 분석",command=do_analyze).pack(side='left')
    ttk.Button(btnbar,text="2. 엑셀 자동완성 저장",command=do_save).pack(side='left',padx=8)
    ttk.Label(btnbar,textvariable=status).pack(side='left',padx=12)

    foot=ttk.Label(root,text="규칙: 30문항이면 기존 배점을 유지합니다. 그 외 문항은 총점 100점으로 자동 배점하며 저장 전에 수정할 수 있습니다.",padding=12)
    foot.pack(fill='x')
    root.mainloop()

if __name__ == '__main__':
    if '--cli' in sys.argv:
        idx=sys.argv.index('--cli'); args=sys.argv[idx+1:]
        if len(args)<2: raise SystemExit('usage: app.py --cli exam.hwpx grade.xlsx [output.xlsx]')
        run_cli(args[0],args[1],args[2] if len(args)>2 else None)
    else:
        gui_main()
