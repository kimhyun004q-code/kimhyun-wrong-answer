from __future__ import annotations
import json, os, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import psutil

from tkinterdnd2 import TkinterDnD, DND_FILES
from excel_reader import read_workbook

APP_TITLE = "김현수학 개인별오답 생성기"
STALL_TIMEOUT_SECONDS = 120
HARD_TIMEOUT_SECONDS = 1800
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

def run_batch_worker(manifest_path: str, on_progress):
    last_error = None
    for attempt in range(1, WORKER_RETRIES + 1):
        before = _hwp_pids()
        with tempfile.TemporaryDirectory(prefix="kimhyun_runner_") as td:
            progress = Path(td) / "progress.json"
            cmd = _child_command("--batch-hwp-worker", manifest_path, str(progress))
            proc = subprocess.Popen(cmd, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            started = time.time()
            last_activity = started
            last_marker = None

            while True:
                if progress.exists():
                    try:
                        data = json.loads(progress.read_text(encoding="utf-8"))
                        marker = (data.get("state"), data.get("message"), data.get("current"))
                        if marker != last_marker:
                            last_marker = marker
                            last_activity = time.time()
                            on_progress(data.get("message", "작업 중"))
                        if data.get("state") == "error":
                            last_error = data.get("message", "한글 생성 오류")
                    except Exception:
                        pass

                rc = proc.poll()
                if rc is not None:
                    if rc == 0:
                        return
                    break

                now = time.time()
                if now - last_activity > STALL_TIMEOUT_SECONDS:
                    last_error = "한컴 한글이 2분 동안 진행되지 않아 자동 재시도합니다."
                    on_progress(last_error)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    _kill_new_hwp(before)
                    break
                if now - started > HARD_TIMEOUT_SECONDS:
                    last_error = "전체 작업 시간이 너무 길어 자동 재시도합니다."
                    on_progress(last_error)
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    _kill_new_hwp(before)
                    break
                time.sleep(0.3)

            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        _kill_new_hwp(before)
        if attempt < WORKER_RETRIES:
            on_progress("작업을 한 번 더 자동 시도합니다.")
            time.sleep(1.0)
    raise RuntimeError(last_error or "학생별 HWP 생성에 실패했습니다.")

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
        self.btn = ttk.Button(actions, text="학생별 HWP 빠른 생성", command=self._start)
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
        for p in list(self.tk.splitlist(ev.data)):
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
            test_name = self.test_name.get().strip()
            test_date = self.test_date.get().strip()
            folder_name = safe_name(f"{test_name}_{test_date}_개인별오답")
            result_dir = root / folder_name
            result_dir.mkdir(parents=True, exist_ok=True)
            self.last_result_dir = result_dir

            targets = [s for s in self.data["students"] if s["wrongs"]]
            if not targets:
                raise RuntimeError("오답이 있는 학생이 없습니다.")

            students = []
            for s in targets:
                student = str(s["name"])
                filename = safe_name(f"{student}_{test_date}_오답.hwp")
                students.append({
                    "student": student,
                    "test_name": test_name,
                    "test_date": test_date,
                    "wrongs": [int(q) for q in s["wrongs"]],
                    "output_hwp": str(result_dir / filename),
                })

            with tempfile.TemporaryDirectory(prefix="kimhyun_job_") as td:
                manifest_path = Path(td) / "batch_job.json"
                manifest = {
                    "source": str(Path(source).resolve()),
                    "question_count": int(self.data["question_count"]),
                    "students": students,
                }
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                self._log("고속 모드 시작: 한글을 한 번만 실행해 전체 학생을 연속 처리합니다.")
                run_batch_worker(str(manifest_path), self._log)

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
    if len(sys.argv) >= 2 and sys.argv[1] == "--batch-hwp-worker":
        from hwp_worker import batch_hwp_worker
        if len(sys.argv) != 4:
            raise SystemExit(3)
        raise SystemExit(batch_hwp_worker(sys.argv[2], sys.argv[3]))
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
