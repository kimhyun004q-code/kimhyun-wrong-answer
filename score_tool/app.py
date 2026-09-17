import ctypes
import os
import sys
import shutil
import threading
import zipfile
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

ANALYSIS_MARKERS = (
    '시험 분석',
    '시험지 전체 개요',
    '어려움·매우 어려움 문항 분석',
    '연구실 한마디',
    '수학 김현입니다.',
)

_analysis_cache = {}


def program_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def find_template() -> str:
    candidates = [
        resource_dir() / 'template.xlsx',
        program_dir() / '등수 성적 처리기본틀 수정 2026.xlsx',
        program_dir() / 'template.xlsx',
        Path.cwd() / '등수 성적 처리기본틀 수정 2026.xlsx',
        Path.cwd() / 'template.xlsx',
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    raise FileNotFoundError('내장 성적처리 기본틀을 찾지 못했습니다. 프로그램을 최신 버전으로 업데이트해 주세요.')


def default_output_paths(hwpx_path: str):
    p = Path(hwpx_path)
    return (
        str(p.with_name(p.stem + '_성적처리.xlsx')),
        str(p.with_name(p.stem + '_시험분석.hwpx')),
    )


def _file_key(path: str):
    p = Path(path)
    st = p.stat()
    return (str(p.resolve()), st.st_size, st.st_mtime_ns)


def analyze_cached(path: str):
    key = _file_key(path)
    cached = _analysis_cache.get(key)
    if cached is not None:
        return cached
    result = analyze(path)
    _analysis_cache.clear()
    _analysis_cache[key] = result
    return result


def is_already_analyzed(hwpx_path: str) -> bool:
    try:
        hits = 0
        with zipfile.ZipFile(hwpx_path, 'r') as z:
            names = [n for n in z.namelist() if n.startswith('Contents/section') and n.endswith('.xml')]
            for name in names:
                text = z.read(name).decode('utf-8', errors='ignore')
                for marker in ANALYSIS_MARKERS:
                    if marker in text:
                        hits += 1
                if hits >= 2:
                    return True
        return False
    except Exception:
        return False


def _decode_drop_path(value):
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        for enc in ('utf-8', 'mbcs', 'cp949'):
            try:
                return value.decode(enc)
            except Exception:
                pass
        return value.decode(errors='ignore')
    return str(value)


def _allow_windows_drop_messages(root):
    """Allow Explorer drag/drop even when Windows integrity levels differ."""
    if os.name != 'nt':
        return
    try:
        root.update_idletasks()
        hwnd = root.winfo_id()
        user32 = ctypes.windll.user32
        MSGFLT_ALLOW = 1
        # WM_DROPFILES, WM_COPYGLOBALDATA, WM_COPYDATA
        for msg in (0x0233, 0x0049, 0x004A):
            try:
                user32.ChangeWindowMessageFilterEx(hwnd, msg, MSGFLT_ALLOW, None)
            except Exception:
                try:
                    user32.ChangeWindowMessageFilter(msg, MSGFLT_ALLOW)
                except Exception:
                    pass
    except Exception:
        pass


def gui_main():
    # Native Tk is used intentionally. Windows file dropping is handled by windnd,
    # which is more reliable in a one-file PyInstaller build than Tcl/Tk DnD alone.
    root = tk.Tk()
    root.title(f'{APP_TITLE}  v{APP_VERSION}')
    root.geometry('1020x760')
    root.minsize(900, 640)
    root.option_add('*Font', ('Malgun Gothic', 10))

    hwpx_var = tk.StringVar()
    status = tk.StringVar(value='HWPX 시험지 하나만 넣으면 됩니다. 엑셀 기본틀은 프로그램에 내장되어 있습니다.')
    rows_state = []
    busy = {'value': False}
    action_buttons = []

    def clear_rows():
        nonlocal rows_state
        rows_state = []
        for w in inner.winfo_children():
            w.destroy()

    def accept_hwpx(path):
        path = os.path.abspath(os.path.normpath(_decode_drop_path(path).strip().strip('"')))
        if not path.lower().endswith('.hwpx') or not os.path.isfile(path):
            status.set('HWPX 파일만 넣어 주세요.')
            return False
        hwpx_var.set(path)
        clear_rows()
        update_file_status(path)
        drop_label.configure(text=f'선택됨: {Path(path).name}')
        return True

    def choose_hwpx():
        p = filedialog.askopenfilename(filetypes=[('HWPX 시험지', '*.hwpx')])
        if p:
            accept_hwpx(p)

    def update_file_status(path):
        if not path or not os.path.isfile(path):
            return
        if is_already_analyzed(path):
            status.set('이미 시험분석이 들어간 HWPX입니다. 「엑셀만 생성 (빠름)」을 누르면 됩니다.')
        else:
            status.set('HWPX가 준비되었습니다. 문항 확인 또는 바로 엑셀 생성을 누르세요.')

    def set_busy(v):
        busy['value'] = bool(v)
        state = 'disabled' if v else 'normal'
        for b in action_buttons:
            b.configure(state=state)
        root.update_idletasks()

    def render_rows(rows, source):
        nonlocal rows_state
        rows_state = []
        for w in inner.winfo_children():
            w.destroy()
        hdr = ['번호', '형식', '문제유형(자동·수정가능)', '평가영역', '배점']
        for j, h in enumerate(hdr):
            ttk.Label(inner, text=h, font=('Malgun Gothic', 10, 'bold')).grid(row=0, column=j, padx=5, pady=5, sticky='w')
        for i, r in enumerate(rows, 1):
            topic = tk.StringVar(value=r['topic'])
            ev = tk.StringVar(value=r['eval'])
            score = tk.StringVar(value='' if r['score'] is None else str(r['score']))
            ttk.Label(inner, text=str(r['num']), width=5).grid(row=i, column=0, padx=5, pady=3)
            ttk.Label(inner, text=r['format'], width=8).grid(row=i, column=1, padx=5, pady=3)
            ttk.Entry(inner, textvariable=topic, width=30).grid(row=i, column=2, padx=5, pady=3, sticky='ew')
            ttk.Combobox(inner, textvariable=ev, values=EVAL_AREAS, state='readonly', width=12).grid(row=i, column=3, padx=5, pady=3)
            ttk.Entry(inner, textvariable=score, width=8, state=('disabled' if len(rows) == 30 else 'normal')).grid(row=i, column=4, padx=5, pady=3)
            rows_state.append((r, topic, ev, score))
        inner.columnconfigure(2, weight=1)
        status.set(f'{len(rows)}문항 확인 완료 · {source}')

    def validate_hwpx():
        hp = hwpx_var.get().strip()
        if not os.path.isfile(hp) or not hp.lower().endswith('.hwpx'):
            raise ValueError('HWPX 시험지를 선택해 주세요.')
        return hp

    def auto_rows(hp):
        return analyze_cached(hp)

    def reviewed_rows_from_ui_or_auto(hp):
        if rows_state:
            reviewed = []
            n = len(rows_state)
            for base, tv, ev, sv in rows_state:
                score = None
                if n != 30:
                    score = float(sv.get())
                    if score <= 0:
                        raise ValueError(f"{base['num']}번 배점이 올바르지 않습니다.")
                    if abs(score - round(score)) < 1e-9:
                        score = int(round(score))
                reviewed.append({
                    'num': base['num'],
                    'text': base['text'],
                    'format': base['format'],
                    'topic': tv.get().strip() or '복합유형',
                    'eval': ev.get(),
                    'score': score,
                })
            if n != 30:
                total = sum(float(r['score']) for r in reviewed)
                if abs(total - 100) > 1e-6:
                    raise ValueError(f'배점 합계가 {total:g}점입니다. 100점으로 맞춰 주세요.')
            return reviewed
        rows, _source = auto_rows(hp)
        return rows

    def do_analyze():
        try:
            hp = validate_hwpx()
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        if busy['value']:
            return
        set_busy(True)
        status.set('문항을 확인하는 중...')

        def work():
            try:
                rows, source = auto_rows(hp)
                root.after(0, lambda: render_rows(rows, source))
            except Exception as e:
                root.after(0, lambda: messagebox.showerror(APP_TITLE, str(e)))
            finally:
                root.after(0, lambda: set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def generate_excel_only():
        try:
            hp = validate_hwpx()
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        if busy['value']:
            return
        set_busy(True)
        status.set('엑셀을 빠르게 생성하는 중...')

        def work():
            try:
                reviewed = reviewed_rows_from_ui_or_auto(hp)
                out_xlsx, _ = default_output_paths(hp)
                fill_workbook(find_template(), hp, reviewed, out_xlsx)
                analyzed = is_already_analyzed(hp)
                msg = '엑셀 생성 완료'
                if analyzed:
                    msg += ' · 기존 분석 HWPX는 그대로 사용'
                root.after(0, lambda: status.set(f'{msg}: {Path(out_xlsx).name}'))
                root.after(0, lambda: messagebox.showinfo(
                    APP_TITLE,
                    f'성적처리 엑셀을 만들었습니다.\n\n{out_xlsx}\n\nHWPX 파일은 변경하지 않았습니다.'
                ))
            except Exception as e:
                root.after(0, lambda: messagebox.showerror(APP_TITLE, str(e)))
            finally:
                root.after(0, lambda: set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    def generate_both():
        try:
            hp = validate_hwpx()
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        if busy['value']:
            return
        if is_already_analyzed(hp):
            generate_excel_only()
            return
        set_busy(True)
        status.set('엑셀과 HWPX 결과본을 생성하는 중...')

        def work():
            try:
                reviewed = reviewed_rows_from_ui_or_auto(hp)
                out_xlsx, out_hwpx = default_output_paths(hp)
                fill_workbook(find_template(), hp, reviewed, out_xlsx)
                shutil.copyfile(hp, out_hwpx)
                root.after(0, lambda: status.set(f'완료: {Path(out_xlsx).name} / {Path(out_hwpx).name}'))
                root.after(0, lambda: messagebox.showinfo(
                    APP_TITLE,
                    f'완료했습니다.\n\n성적처리 엑셀: {out_xlsx}\nHWPX 결과본: {out_hwpx}'
                ))
            except Exception as e:
                root.after(0, lambda: messagebox.showerror(APP_TITLE, str(e)))
            finally:
                root.after(0, lambda: set_busy(False))

        threading.Thread(target=work, daemon=True).start()

    # UI
    top = ttk.Frame(root, padding=12)
    top.pack(fill='x')
    ttk.Label(top, text='시험지 HWPX').grid(row=0, column=0, sticky='w', pady=4)
    ttk.Entry(top, textvariable=hwpx_var, width=82).grid(row=0, column=1, sticky='ew', padx=8)
    ttk.Button(top, text='찾기', command=choose_hwpx).grid(row=0, column=2)
    top.columnconfigure(1, weight=1)

    ttk.Label(
        root,
        text='엑셀 기본틀 내장 · HWPX만 넣으면 됩니다. 이미 시험분석이 들어간 HWPX는 다시 만들지 않고 엑셀만 생성합니다.',
        padding=(12, 4),
    ).pack(fill='x')

    drop_label = tk.Label(
        root,
        text='HWPX 파일을 이 창 어디에나 드래그해서 놓으세요',
        relief='groove',
        bd=2,
        height=4,
        font=('Malgun Gothic', 12, 'bold'),
        cursor='hand2',
    )
    drop_label.pack(fill='x', padx=12, pady=(4, 6))
    drop_label.bind('<Button-1>', lambda _e: choose_hwpx())

    btnbar = ttk.Frame(root, padding=(12, 6))
    btnbar.pack(fill='x')

    frame = ttk.Frame(root, padding=(12, 0))
    frame.pack(fill='both', expand=True)
    canvas = tk.Canvas(frame, highlightthickness=0)
    scrollbar = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
    inner = ttk.Frame(canvas)
    inner.bind('<Configure>', lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.create_window((0, 0), window=inner, anchor='nw')
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')

    b1 = ttk.Button(btnbar, text='문항 확인/수정', command=do_analyze)
    b1.pack(side='left')
    action_buttons.append(b1)
    b2 = ttk.Button(btnbar, text='엑셀만 생성 (빠름)', command=generate_excel_only)
    b2.pack(side='left', padx=8)
    action_buttons.append(b2)
    b3 = ttk.Button(btnbar, text='엑셀 + HWPX 생성', command=generate_both)
    b3.pack(side='left')
    action_buttons.append(b3)
    ttk.Label(btnbar, textvariable=status).pack(side='left', padx=12)

    ttk.Label(
        root,
        text='평가영역: 계산 / 이해 / 추론 / 문제해결 / 자료해석   ·   같은 파일은 분석 결과를 재사용하여 더 빠르게 처리합니다.',
        padding=12,
    ).pack(fill='x')

    # Native Windows Explorer drag/drop. This is independent of tkinterdnd2 Tcl packages.
    drag_ready = False
    if os.name == 'nt':
        try:
            import windnd

            _allow_windows_drop_messages(root)

            def native_drop(files):
                def apply_drop():
                    for item in files:
                        if accept_hwpx(item):
                            return
                    status.set('드래그한 항목에서 HWPX 파일을 찾지 못했습니다.')
                root.after(0, apply_drop)

            try:
                windnd.hook_dropfiles(root, func=native_drop, force_unicode=True)
            except TypeError:
                windnd.hook_dropfiles(root, func=native_drop)
            drag_ready = True
        except Exception:
            drag_ready = False

    # Secondary TkDND fallback when available.
    if not drag_ready:
        try:
            from tkinterdnd2 import TkinterDnD, DND_FILES
            TkinterDnD.require(root)
            drop_label.drop_target_register(DND_FILES)

            def tk_drop(ev):
                for item in root.tk.splitlist(ev.data):
                    if accept_hwpx(item):
                        break

            drop_label.dnd_bind('<<Drop>>', tk_drop)
            drag_ready = True
        except Exception:
            pass

    if drag_ready:
        drop_label.configure(text='HWPX 파일을 이 창 어디에나 드래그해서 놓으세요  ✓ 드래그 준비됨')
    else:
        drop_label.configure(text='드래그 기능을 준비하지 못했습니다. 여기를 클릭하거나 위의 「찾기」를 눌러 주세요.')

    for arg in sys.argv[1:]:
        if str(arg).lower().endswith('.hwpx') and os.path.isfile(arg):
            accept_hwpx(arg)
            break

    if check_and_update_async:
        try:
            check_and_update_async(root, APP_VERSION, status)
        except Exception:
            pass

    root.mainloop()


if __name__ == '__main__':
    gui_main()
