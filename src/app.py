from __future__ import annotations
import os
import re
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES

from excel_reader import read_workbook
from hwpx_direct import HwpxExam, generate_student_files

APP_TITLE = "김현수학 개인별오답 생성기 - HWPX 초고속"


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip().rstrip(".") or "결과"


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x760")
        self.minsize(900, 680)
        self.data = None
        self.last_result_dir = None
        self.excel_path = tk.StringVar()
        self.hwpx_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "개인별오답"))
        self.test_name = tk.StringVar()
        self.test_date = tk.StringVar()
        self.status = tk.StringVar(value="엑셀과 HWPX 시험지를 창에 끌어다 놓으세요.")
        self._build()

    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_TITLE, font=("맑은 고딕", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="한컴 한글을 실행하지 않습니다. 엑셀(.xlsx) + 시험지(.hwpx)를 같이 드래그하면 빠르게 학생별 HWPX를 만듭니다.",
        ).pack(anchor="w", pady=(2, 10))

        drop = tk.Label(
            outer,
            text="여기에 엑셀과 HWPX 파일을 함께 드래그해서 놓으세요",
            relief="groove",
            bd=2,
            height=4,
            font=("맑은 고딕", 12, "bold"),
        )
        drop.pack(fill="x", pady=(0, 10))
        drop.drop_target_register(DND_FILES)
        drop.dnd_bind("<<Drop>>", self._on_drop)

        form = ttk.Frame(outer)
        form.pack(fill="x")
        self._row(form, 0, "성적 엑셀", self.excel_path, self._pick_excel)
        self._row(form, 1, "시험지 HWPX", self.hwpx_path, self._pick_hwpx)
        self._row(form, 2, "저장 위치", self.output_dir, self._pick_out)
        ttk.Label(form, text="시험명").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.test_name).grid(row=3, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(form, text="시험일").grid(row=3, column=2, sticky="w", padx=(10, 0), pady=4)
        ttk.Entry(form, textvariable=self.test_date, width=16).grid(row=3, column=3, sticky="w", padx=6, pady=4)
        form.columnconfigure(1, weight=1)

        ttk.Label(outer, text="학생별 오답 미리보기", font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(12, 4))
        self.tree = ttk.Treeview(outer, columns=("name", "count", "wrong"), show="headings", height=12)
        self.tree.heading("name", text="학생명")
        self.tree.heading("count", text="오답수")
        self.tree.heading("wrong", text="오답문항")
        self.tree.column("name", width=150, anchor="center")
        self.tree.column("count", width=80, anchor="center")
        self.tree.column("wrong", width=650)
        self.tree.pack(fill="both", expand=True)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=10)
        self.btn = ttk.Button(actions, text="학생별 HWPX 즉시 생성", command=self._start)
        self.btn.pack(side="left")
        ttk.Button(actions, text="결과 폴더 열기", command=self._open_out).pack(side="left", padx=8)
        self.pb = ttk.Progressbar(actions, mode="determinate", maximum=100)
        self.pb.pack(side="right", fill="x", expand=True, padx=(20, 0))

        ttk.Label(outer, textvariable=self.status).pack(anchor="w")
        self.log = tk.Text(outer, height=7, wrap="word")
        self.log.pack(fill="x", pady=(4, 0))

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
            elif ext == ".hwpx":
                self.hwpx_path.set(p)
            elif ext == ".hwp":
                self._log("HWP는 사용하지 않습니다. 시험지를 HWPX로 저장해서 넣어주세요.")
        if self.excel_path.get():
            self._analyze()
        if self.hwpx_path.get() and self.data:
            self._check_hwpx()

    def _pick_excel(self):
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if p:
            self.excel_path.set(p)
            self._analyze()

    def _pick_hwpx(self):
        p = filedialog.askopenfilename(filetypes=[("한글 HWPX", "*.hwpx")])
        if p:
            self.hwpx_path.set(p)
            if self.data:
                self._check_hwpx()

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
            self._log(f"엑셀 분석 완료: 학생 {len(self.data['students'])}명 / {self.data['question_count']}문항")
        except Exception as e:
            messagebox.showerror("엑셀 오류", str(e))

    def _check_hwpx(self):
        try:
            exam = HwpxExam(self.hwpx_path.get(), int(self.data["question_count"]))
            self._log(f"HWPX 문항 확인 완료: {exam.question_count}문항. 한글 실행 없이 바로 생성할 수 있습니다.")
        except Exception as e:
            messagebox.showerror("HWPX 오류", str(e))

    def _start(self):
        if self.btn["state"] == "disabled":
            return
        self.btn.configure(state="disabled")
        self.pb["value"] = 0
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            if not self.data:
                self.data = read_workbook(self.excel_path.get())
            exam_path = self.hwpx_path.get()
            if not Path(exam_path).exists():
                raise RuntimeError("시험지 HWPX를 넣어주세요.")

            root = Path(self.output_dir.get())
            root.mkdir(parents=True, exist_ok=True)
            test_name = self.test_name.get().strip() or self.data["test_name"]
            test_date = self.test_date.get().strip() or self.data["test_date"]
            result_dir = root / safe_name(f"{test_name}_{test_date}_개인별오답")
            result_dir.mkdir(parents=True, exist_ok=True)
            self.last_result_dir = result_dir

            targets = [s for s in self.data["students"] if s["wrongs"]]
            if not targets:
                raise RuntimeError("오답이 있는 학생이 없습니다.")

            self._log("생성 시작: 한컴 한글은 실행하지 않습니다.")

            def progress(i, total, student):
                pct = int(i * 100 / max(total, 1))
                self.after(0, lambda p=pct: self.pb.configure(value=p))
                self._log(f"[{i}/{total}] {student} 완료")

            files = generate_student_files(
                exam_path=exam_path,
                result_dir=str(result_dir),
                students=self.data["students"],
                question_count=int(self.data["question_count"]),
                test_date=test_date,
                progress=progress,
            )
            self._log(f"완료: 학생별 HWPX {len(files)}개 생성")
            self.after(0, lambda: messagebox.showinfo("완료", f"학생별 HWPX {len(files)}개를 만들었습니다.\n\n{result_dir}"))
        except Exception as e:
            self._log("오류: " + str(e))
            self.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.after(0, self._finish)

    def _finish(self):
        self.btn.configure(state="normal")

    def _open_out(self):
        p = Path(self.last_result_dir or self.output_dir.get())
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
