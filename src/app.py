from __future__ import annotations
import json, os, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import psutil

from tkinterdnd2 import TkinterDnD, DND_FILES

from excel_reader import read_workbook
from pdf_questions import detect_question_clips, render_question_images

APP_TITLE = "김현수학 개인별오답 생성기"
WORKER_TIMEOUT_SECONDS = 180
WORKER_RETRIES = 2

def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip()

def _child_command(*args):
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, str(Path(__file__).resolve()), *args]

def _hwp_pids() -> set[int]:
    out = set()
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if (p.info.get("name") or "").lower() == "hwp.exe":
                out.add(int(p.info["pid"]))
        except Exception:
            pass
    return out

def _kill_new_hwp(before: set[int]):
    for pid in _hwp_pids() - before:
        try:
            psutil.Process(pid).kill()
        except Exception:
            pass

def run_worker(args: list[str], success_file: str | None, on_progress, label: str):
    last_error = None
    for attempt in range(1, WORKER_RETRIES + 1):
        before = _hwp_pids()
        with tempfile.TemporaryDirectory(prefix="kimhyun_worker_") as td:
            progress = Path(td) / "progress.json"
            cmd = _child_command(*args, str(progress))
            proc = subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            started = time.time()
            last_state = None
            while True:
                if progress.exists():
                    try:
                        data = json.loads(progress.read_text(encoding="utf-8"))
                        state = data.get("state")
                        if state != last_state:
                            last_state = state
                            on_progress(f"[{label} {attempt}/{WORKER_RETRIES}] {data.get('message','')}")
                        if state == "error":
                            last_error = data.get("message", f"{label} 오류")
                    except Exception:
                        pass
                rc = proc.poll()
                if rc is not None:
                    ok_file = True if success_file is None else Path(success_file).exists()
                    if rc == 0 and ok_file:
                        return
                    break
                if time.time() - started > WORKER_TIMEOUT_SECONDS:
                    last_error = f"{label} 작업이 오래 응답하지 않아 자동으로 다시 시도합니다."
                    on_progress(last_error)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    _kill_new_hwp(before)
                    break
                time.sleep(0.35)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        _kill_new_hwp(before)
        if attempt < WORKER_RETRIES:
            time.sleep(1.0)
    raise RuntimeError(last_error or f"{label} 작업에 실패했습니다.")

class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x760")
        self.minsize(900, 680)
        self.data = None
        self.last_result_dir = None
        self.excel_path = tk.StringVar()
        self.hwp_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "개인별오답"))
        self.test_name = tk.StringVar()
        self.test_date = tk.StringVar()
        self.status = tk.StringVar(value="엑셀과 한글 시험지를 창에 끌어다 놓으세요.")
        self._build()

    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_TITLE, font=("맑은 고딕", 18, "bold")).pack(anchor="w")
        ttk.Label(outer, text="엑셀(.xlsx) + 시험지(.hwp/.hwpx)를 같이 드래그하세요. 결과는 학생별 HWP만 생성합니다.").pack(anchor="w", pady=(2,10))

        drop = tk.Label(outer, text="여기에 엑셀과 한글 파일을 드래그해서 놓으세요", relief="groove", bd=2, height=4, font=("맑은 고딕", 12, "bold"))
        drop.pack(fill="x", pady=(0,10))
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", self._on_drop)

        form = ttk.Frame(outer)
        form.pack(fill="x")
        self._row(form, 0, "성적 엑셀", self.excel_path, self._pick_excel)
        self._row(form, 1, "시험지", self.hwp_path, self._pick_hwp)
        self._row(form, 2, "저장 위치", self.output_dir, self._pick_out)
        ttk.Label(form, text="시험명").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.test_name).grid(row=3, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(form, text="시험일").grid(row=3, column=2, sticky="w", padx=(10,0), pady=4)
        ttk.Entry(form, textvariable=self.test_date, width=16).grid(row=3, column=3, sticky="w", padx=6, pady=4)
        form.columnconfigure(1, weight=1)

        ttk.Label(outer, text="학생별 오답 미리보기", font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(12,4))
        self.tree = ttk.Treeview(outer, columns=("name","count","wrong"), show="headings", height=12)
        self.tree.heading("name", text="학생명")
        self.tree.heading("count", text="오답수")
        self.tree.heading("wrong", text="오답문항")
        self.tree.column("name", width=150, anchor="center")
        self.tree.column("count", width=80, anchor="center")
        self.tree.column("wrong", width=650)
        self.tree.pack(fill="both", expand=True)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=10)
        self.btn = ttk.Button(actions, text="학생별 HWP 생성", command=self._start)
        self.btn.pack(side="left")
        ttk.Button(actions, text="결과 폴더 열기", command=self._open_out).pack(side="left", padx=8)
        self.pb = ttk.Progressbar(actions, mode="indeterminate")
        self.pb.pack(side="right", fill="x", expand=True, padx=(20,0))

        ttk.Label(outer, textvariable=self.status).pack(anchor="w")
        self.log = tk.Text(outer, height=7, wrap="word")
        self.log.pack(fill="x", pady=(4,0))

    def _row(self, parent, row, label, var, command):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=1, columnspan=3, sticky="ew", padx=6, pady=4)
        ttk.Button(parent, text="선택", command=command).grid(row=row, column=4, padx=4, pady=4)

    def _log(self, msg):
        def apply():
            self.status.set(msg)
            self.log.insert("end", time.strftime("%H:%M:%S ") + msg + "\n")
            self.log.see("end")
        self.after(0, apply)

    def _on_drop(self, ev):
        paths = list(self.tk.splitlist(ev.data))
        for p in paths:
            ext = Path(p).suffix.lower()
            if ext == ".xlsx":
                self.excel_path.set(p)
            elif ext in {".hwp", ".hwpx"}:
                self.hwp_path.set(p)
        if self.excel_path.get():
            self._analyze()

    def _pick_excel(self):
        p = filedialog.askopenfilename(filetypes=[("Excel","*.xlsx")])
        if p:
            self.excel_path.set(p)
            self._analyze()

    def _pick_hwp(self):
        p = filedialog.askopenfilename(filetypes=[("한글 시험지","*.hwp *.hwpx")])
        if p:
            self.hwp_path.set(p)

    def _pick_out(self):
        p = filedialog.askdirectory()
        if p:
            self.output_dir.set(p)

    def _analyze(self):
        try:
            self.data = read_workbook(self.excel_path.get())
            self.test_name.set(self.data["test_name"])
            self.test_date.set(self.data["test_date"])
            for x in self.tree.get_children():
                self.tree.delete(x)
            for s in self.data["students"]:
                wrong_text = ", ".join(map(str, s["wrongs"])) if s["wrongs"] else "-"
                self.tree.insert("", "end", values=(s["name"], len(s["wrongs"]), wrong_text))
            self._log(f"엑셀 분석 완료: {len(self.data['students'])}명 / {self.data['question_count']}문항")
        except Exception as e:
            messagebox.showerror("엑셀 오류", str(e))

    def _start(self):
        if self.btn["state"] == "disabled":
            return
        self.btn.configure(state="disabled")
        self.pb.start(12)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            if not self.data:
                self.data = read_workbook(self.excel_path.get())
            source = self.hwp_path.get()
            if not Path(source).exists():
                raise RuntimeError("시험지 HWP/HWPX를 넣어주세요.")

            root = Path(self.output_dir.get())
            root.mkdir(parents=True, exist_ok=True)
            folder_name = safe_name(f"{self.test_name.get()}_{self.test_date.get()}_개인별오답")
            result_dir = root / folder_name
            result_dir.mkdir(parents=True, exist_ok=True)
            self.last_result_dir = result_dir

            with tempfile.TemporaryDirectory(prefix="kimhyun_wrong_") as td:
                work = Path(td)
                base_pdf = str(work / "source.pdf")
                self._log("한글 파일 접근은 프로그램이 자동 허용합니다. 이제 기다리기만 하면 됩니다.")
                run_worker(["--hwp-worker", source, base_pdf], base_pdf, self._log, "시험지 준비")

                self._log("문항 위치를 자동 분석 중입니다.")
                clips = detect_question_clips(base_pdf, self.data["question_count"])
                images = render_question_images(base_pdf, clips, str(work / "question_images"))
                self._log(f"문항 {len(images)}개 준비 완료.")

                targets = [s for s in self.data["students"] if s["wrongs"]]
                for i, s in enumerate(targets, 1):
                    student = str(s["name"])
                    date_text = self.test_date.get().strip()
                    filename = safe_name(f"{student}_{date_text}_오답.hwp")
                    out_hwp = str(result_dir / filename)
                    manifest = {
                        "student": student,
                        "test_name": self.test_name.get().strip(),
                        "test_date": date_text,
                        "wrongs": [int(q) for q in s["wrongs"]],
                        "images": {str(q): images.get(int(q), []) for q in s["wrongs"]},
                    }
                    manifest_path = work / f"manifest_{i}.json"
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                    self._log(f"[{i}/{len(targets)}] {student} HWP 생성 중")
                    run_worker(["--student-hwp-worker", str(manifest_path), out_hwp], out_hwp, self._log, student)

            self._log(f"모든 학생 HWP 생성 완료: {result_dir}")
            self.after(0, lambda: messagebox.showinfo("완료", f"완료했습니다.\n\n결과 폴더:\n{result_dir}"))
        except Exception as e:
            self._log("오류: " + str(e))
            self.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.after(0, self._finish)

    def _finish(self):
        self.pb.stop()
        self.btn.configure(state="normal")

    def _open_out(self):
        p = self.last_result_dir or Path(self.output_dir.get())
        Path(p).mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))

def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--hwp-worker":
        from hwp_worker import worker
        if len(sys.argv) != 5:
            raise SystemExit(3)
        raise SystemExit(worker(sys.argv[2], sys.argv[3], sys.argv[4]))
    if len(sys.argv) >= 2 and sys.argv[1] == "--student-hwp-worker":
        from hwp_worker import student_hwp_worker
        if len(sys.argv) != 5:
            raise SystemExit(3)
        raise SystemExit(student_hwp_worker(sys.argv[2], sys.argv[3], sys.argv[4]))
    App().mainloop()

if __name__ == "__main__":
    main()
