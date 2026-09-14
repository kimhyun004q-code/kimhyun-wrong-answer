from __future__ import annotations
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES

from excel_reader import read_workbook
from hwpx_direct import HwpxExam, generate_student_files

APP_TITLE = "김현수학 개인별오답 생성기 - HWPX 초고속+수기"


def safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip().rstrip(".") or "결과"


def parse_manual_questions(text: str) -> list[int]:
    """1,3,5 / 1 3 5 / 3-6 / 3~6 형식을 모두 허용한다."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("수기로 만들 문항 번호를 입력해 주세요.")
    raw = raw.replace("，", ",").replace("；", ",").replace(";", ",")
    raw = re.sub(r"\s*[-~]\s*", "-", raw)
    tokens = [x for x in re.split(r"[\s,/]+", raw) if x]
    nums: list[int] = []
    for token in tokens:
        m = re.fullmatch(r"(\d+)-(\d+)", token)
        if m:
            a, b = map(int, m.groups())
            if a <= 0 or b <= 0:
                raise ValueError("문항 번호는 1 이상의 숫자여야 합니다.")
            step = 1 if a <= b else -1
            nums.extend(range(a, b + step, step))
            continue
        if not token.isdigit():
            raise ValueError(f"문항 번호 형식을 확인해 주세요: {token}")
        q = int(token)
        if q <= 0:
            raise ValueError("문항 번호는 1 이상의 숫자여야 합니다.")
        nums.append(q)
    return sorted(set(nums))


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1030x835")
        self.minsize(920, 740)
        self.data = None
        self.last_result_dir = None
        self.mode = tk.StringVar(value="excel")
        self.excel_path = tk.StringVar()
        self.hwpx_path = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "개인별오답"))
        self.test_name = tk.StringVar()
        self.test_date = tk.StringVar()
        self.manual_student = tk.StringVar()
        self.manual_questions = tk.StringVar()
        self.status = tk.StringVar(value="엑셀 자동 또는 수기 입력 방식을 선택하세요.")
        self._build()
        self._mode_changed()

    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_TITLE, font=("맑은 고딕", 18, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="기존 엑셀 자동 방식은 그대로 유지하고, 필요할 때 학생이름과 문항번호를 직접 입력할 수 있습니다.",
        ).pack(anchor="w", pady=(2, 8))

        mode_box = ttk.LabelFrame(outer, text="생성 방식", padding=(10, 7))
        mode_box.pack(fill="x", pady=(0, 9))
        ttk.Radiobutton(mode_box, text="엑셀 자동", variable=self.mode, value="excel", command=self._mode_changed).grid(row=0, column=0, sticky="w", padx=(0, 18))
        ttk.Radiobutton(mode_box, text="수기 입력", variable=self.mode, value="manual", command=self._mode_changed).grid(row=0, column=1, sticky="w", padx=(0, 18))
        ttk.Label(mode_box, text="학생이름").grid(row=0, column=2, sticky="e")
        self.manual_name_entry = ttk.Entry(mode_box, textvariable=self.manual_student, width=16)
        self.manual_name_entry.grid(row=0, column=3, padx=(5, 14), sticky="w")
        ttk.Label(mode_box, text="오답번호").grid(row=0, column=4, sticky="e")
        self.manual_questions_entry = ttk.Entry(mode_box, textvariable=self.manual_questions, width=28)
        self.manual_questions_entry.grid(row=0, column=5, padx=(5, 8), sticky="ew")
        self.manual_preview_btn = ttk.Button(mode_box, text="수기 미리보기", command=self._preview_manual)
        self.manual_preview_btn.grid(row=0, column=6, padx=(4, 0))
        ttk.Label(mode_box, text="예: 3, 8, 10 또는 3-6").grid(row=1, column=4, columnspan=3, sticky="w", pady=(4,0))
        mode_box.columnconfigure(5, weight=1)

        drop = tk.Label(
            outer,
            text="시험지 HWPX를 드래그하세요  ·  엑셀 자동 모드는 XLSX도 함께 드래그",
            relief="groove",
            bd=2,
            height=3,
            font=("맑은 고딕", 11, "bold"),
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

        ttk.Label(outer, text="오답 미리보기", font=("맑은 고딕", 10, "bold")).pack(anchor="w", pady=(12, 4))
        self.tree = ttk.Treeview(outer, columns=("name", "count", "wrong"), show="headings", height=11)
        self.tree.heading("name", text="학생명")
        self.tree.heading("count", text="오답수")
        self.tree.heading("wrong", text="오답문항")
        self.tree.column("name", width=150, anchor="center")
        self.tree.column("count", width=80, anchor="center")
        self.tree.column("wrong", width=680)
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

    def _mode_changed(self):
        manual = self.mode.get() == "manual"
        state = "normal" if manual else "disabled"
        self.manual_name_entry.configure(state=state)
        self.manual_questions_entry.configure(state=state)
        self.manual_preview_btn.configure(state=state)
        self.btn.configure(text="수기 지정 HWPX 생성" if manual else "학생별 HWPX 즉시 생성")
        if manual:
            self.status.set("수기 모드: 학생이름과 오답번호를 직접 입력하면 엑셀 없이도 만들 수 있습니다.")
            if not self.test_date.get():
                self.test_date.set(datetime.now().strftime("%Y-%m-%d"))
            if self.hwpx_path.get() and not self.test_name.get():
                self.test_name.set(Path(self.hwpx_path.get()).stem)
        else:
            self.status.set("엑셀 자동 모드: 기존처럼 XLSX의 학생별 오답을 그대로 사용합니다.")
            if self.data:
                self._show_excel_preview()

    def _log(self, msg):
        def apply():
            self.status.set(msg)
            self.log.insert("end", time.strftime("%H:%M:%S ") + msg + "\n")
            self.log.see("end")
        self.after(0, apply)

    def _clear_tree(self):
        for x in self.tree.get_children():
            self.tree.delete(x)

    def _show_excel_preview(self):
        if not self.data:
            return
        self._clear_tree()
        for s in self.data["students"]:
            wrong_text = ", ".join(map(str, s["wrongs"])) if s["wrongs"] else "-"
            self.tree.insert("", "end", values=(s["name"], len(s["wrongs"]), wrong_text))

    def _preview_manual(self):
        try:
            name = self.manual_student.get().strip()
            if not name:
                raise ValueError("학생이름을 입력해 주세요.")
            nums = parse_manual_questions(self.manual_questions.get())
            self._clear_tree()
            self.tree.insert("", "end", values=(name, len(nums), ", ".join(map(str, nums))))
            self._log(f"수기 미리보기: {name} / {len(nums)}문항")
        except Exception as e:
            messagebox.showerror("수기 입력 오류", str(e))

    def _on_drop(self, ev):
        for p in list(self.tk.splitlist(ev.data)):
            ext = Path(p).suffix.lower()
            if ext == ".xlsx":
                self.excel_path.set(p)
            elif ext == ".hwpx":
                self.hwpx_path.set(p)
                if not self.test_name.get() or self.mode.get() == "manual":
                    self.test_name.set(Path(p).stem)
                if not self.test_date.get() and self.mode.get() == "manual":
                    self.test_date.set(datetime.now().strftime("%Y-%m-%d"))
            elif ext == ".hwp":
                self._log("HWP는 사용하지 않습니다. 시험지를 HWPX로 저장해서 넣어주세요.")
        if self.excel_path.get():
            self._analyze()
        if self.hwpx_path.get():
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
            if self.mode.get() == "manual" or not self.test_name.get():
                self.test_name.set(Path(p).stem)
            if self.mode.get() == "manual" and not self.test_date.get():
                self.test_date.set(datetime.now().strftime("%Y-%m-%d"))
            self._check_hwpx()

    def _pick_out(self):
        p = filedialog.askdirectory()
        if p:
            self.output_dir.set(p)

    def _analyze(self):
        try:
            self.data = read_workbook(self.excel_path.get())
            if self.mode.get() == "excel":
                self.test_name.set(self.data["test_name"])
                self.test_date.set(self.data["test_date"])
                self._show_excel_preview()
            self._log(f"엑셀 분석 완료: 학생 {len(self.data['students'])}명 / {self.data['question_count']}문항")
        except Exception as e:
            messagebox.showerror("엑셀 오류", str(e))

    def _check_hwpx(self):
        try:
            if not self.hwpx_path.get():
                return
            if self.mode.get() == "excel" and self.data:
                exam = HwpxExam(self.hwpx_path.get(), int(self.data["question_count"]))
            else:
                exam = HwpxExam(self.hwpx_path.get(), None)
            self._log(f"HWPX 문항 확인 완료: {exam.question_count}문항. 한글 실행 없이 바로 생성할 수 있습니다.")
        except Exception as e:
            messagebox.showerror("HWPX 오류", str(e))

    def _start(self):
        if self.btn["state"] == "disabled":
            return
        self.btn.configure(state="disabled")
        self.pb["value"] = 0
        threading.Thread(target=self._run, daemon=True).start()

    def _result_dir(self, test_name: str, test_date: str) -> Path:
        root = Path(self.output_dir.get())
        root.mkdir(parents=True, exist_ok=True)
        result_dir = root / safe_name(f"{test_name}_{test_date}_개인별오답")
        result_dir.mkdir(parents=True, exist_ok=True)
        self.last_result_dir = result_dir
        return result_dir

    def _run_manual(self):
        exam_path = self.hwpx_path.get()
        if not Path(exam_path).exists():
            raise RuntimeError("시험지 HWPX를 넣어주세요.")
        student = self.manual_student.get().strip()
        if not student:
            raise RuntimeError("수기 입력의 학생이름을 입력해 주세요.")
        wrongs = parse_manual_questions(self.manual_questions.get())
        test_name = self.test_name.get().strip() or Path(exam_path).stem
        test_date = self.test_date.get().strip() or datetime.now().strftime("%Y-%m-%d")
        exam = HwpxExam(exam_path, None)
        invalid = [q for q in wrongs if q > exam.question_count]
        if invalid:
            raise RuntimeError(
                f"시험지는 {exam.question_count}문항까지 인식했습니다. 범위를 벗어난 번호: {', '.join(map(str, invalid))}"
            )
        result_dir = self._result_dir(test_name, test_date)
        out = result_dir / f"{safe_name(student)}_{safe_name(test_date)}_오답.hwpx"
        self._log(f"수기 생성 시작: {student} / {', '.join(map(str, wrongs))}번")
        exam.generate(str(out), student, test_date, wrongs)
        self.after(0, lambda: self.pb.configure(value=100))
        self._log(f"완료: {out.name}")
        self.after(0, lambda: messagebox.showinfo("완료", f"수기 지정 오답노트를 만들었습니다.\n\n{out}"))

    def _run_excel(self):
        if not self.data:
            if not self.excel_path.get():
                raise RuntimeError("성적 엑셀을 넣어주세요.")
            self.data = read_workbook(self.excel_path.get())
        exam_path = self.hwpx_path.get()
        if not Path(exam_path).exists():
            raise RuntimeError("시험지 HWPX를 넣어주세요.")

        test_name = self.test_name.get().strip() or self.data["test_name"]
        test_date = self.test_date.get().strip() or self.data["test_date"]
        result_dir = self._result_dir(test_name, test_date)
        targets = [s for s in self.data["students"] if s["wrongs"]]
        if not targets:
            raise RuntimeError("오답이 있는 학생이 없습니다.")

        self._log("엑셀 자동 생성 시작: 한컴 한글은 실행하지 않습니다.")

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

    def _run(self):
        try:
            if self.mode.get() == "manual":
                self._run_manual()
            else:
                self._run_excel()
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
