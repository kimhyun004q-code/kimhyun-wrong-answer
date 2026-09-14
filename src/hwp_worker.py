from __future__ import annotations
import json, os, tempfile, time, traceback
from pathlib import Path
import pythoncom
import win32com.client
from security import install_security_module


def write_progress(path: str, state: str, message: str, error: str = "", **extra):
    data = {"state": state, "message": message, "error": error, "ts": time.time(), **extra}
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _prepare_hwp(progress: str):
    write_progress(progress, "security", "한글 파일 접근 자동 허용 설정 중")
    install_security_module()
    write_progress(progress, "launch", "한컴 한글을 한 번만 시작합니다")
    hwp = win32com.client.DispatchEx("HWPFrame.HwpObject")
    registered = False
    for module_name in ("FilePathCheckerModule", "FilePathCheckerModuleExample"):
        try:
            if bool(hwp.RegisterModule("FilePathCheckDLL", module_name)):
                registered = True
                break
        except Exception:
            pass
    if not registered:
        try:
            hwp.Quit()
        except Exception:
            pass
        raise RuntimeError("한컴 파일 접근 자동 허용 모듈 등록에 실패했습니다.")
    try:
        hwp.XHwpWindows.Item(0).Visible = False
    except Exception:
        pass
    try:
        hwp.SetMessageBoxMode(0x1000)
    except Exception:
        pass
    return hwp


def _close_current_document(hwp):
    try:
        hwp.XHwpDocuments.Item(0).Close(False)
    except Exception:
        pass


def _quit(hwp):
    if hwp is None:
        return
    _close_current_document(hwp)
    try:
        hwp.Quit()
    except Exception:
        pass


def _insert_text(hwp, text: str):
    p = hwp.HParameterSet.HInsertText
    hwp.HAction.GetDefault("InsertText", p.HSet)
    p.Text = text
    hwp.HAction.Execute("InsertText", p.HSet)


def _insert_picture(hwp, item: dict):
    path = str(Path(item["path"]).resolve())
    width = float(item.get("width_mm", 160.0))
    height = float(item.get("height_mm", 200.0))
    if height > 235.0:
        ratio = 235.0 / height
        height = 235.0
        width *= ratio
    try:
        hwp.InsertPicture(path, True, 3, False, False, 0, width, height)
        return
    except Exception:
        pass
    try:
        hwp.InsertPicture(path, True, 0, False, False, 0)
        return
    except Exception as e:
        raise RuntimeError(f"문항 이미지를 한글에 넣지 못했습니다: {Path(path).name} / {e}")


def _open_source(hwp, source: str):
    ok = False
    try:
        ok = bool(hwp.Open(str(Path(source).resolve()), "", "forceopen:true"))
    except Exception:
        ok = bool(hwp.Open(str(Path(source).resolve()), "", ""))
    if not ok:
        raise RuntimeError("시험지 한글 파일을 열지 못했습니다.")


def _save_source_pdf(hwp, target_pdf: str):
    out = str(Path(target_pdf).resolve())
    ok = False
    try:
        pset = hwp.HParameterSet.HFileOpenSave
        hwp.HAction.GetDefault("FileSaveAs_S", pset.HSet)
        pset.filename = out
        pset.Format = "PDF"
        pset.Attributes = 0
        ok = bool(hwp.HAction.Execute("FileSaveAs_S", pset.HSet))
    except Exception:
        pass
    if not ok:
        try:
            ok = bool(hwp.SaveAs(out, "PDF", ""))
        except Exception:
            pass
    if not ok or not Path(out).exists() or Path(out).stat().st_size < 1024:
        raise RuntimeError("시험지 분석용 PDF 변환에 실패했습니다.")


def _create_student_doc(hwp, manifest: dict, images: dict, output_hwp: str):
    try:
        hwp.HAction.Run("FileNew")
    except Exception:
        pass

    header = (
        f"{manifest['test_name']}\r\n"
        f"학생명 : {manifest['student']}\r\n"
        f"시험일 : {manifest['test_date']}\r\n"
        f"오답문항 : {', '.join(str(x) for x in manifest['wrongs'])}번\r\n"
        "----------------------------------------\r\n\r\n"
    )
    _insert_text(hwp, header)

    first = True
    for q in manifest["wrongs"]:
        items = images.get(int(q), [])
        if not items:
            continue
        if not first:
            try:
                hwp.HAction.Run("BreakPage")
            except Exception:
                _insert_text(hwp, "\r\n\r\n")
        first = False
        _insert_text(hwp, f"[오답 {q}번]\r\n")
        for item in items:
            _insert_picture(hwp, item)
            _insert_text(hwp, "\r\n")

    out = str(Path(output_hwp).resolve())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ok = False
    try:
        ok = bool(hwp.SaveAs(out, "HWP", ""))
    except Exception:
        pass
    if not ok or not Path(out).exists() or Path(out).stat().st_size < 1024:
        raise RuntimeError(f"{manifest['student']} HWP 저장에 실패했습니다.")
    _close_current_document(hwp)


def batch_hwp_worker(manifest_path: str, progress: str) -> int:
    """Ultra-fast path: one Hangul process, render only actually-wrong questions as compact JPEGs."""
    pythoncom.CoInitialize()
    hwp = None
    try:
        job = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        students = job["students"]
        needed_questions = sorted({int(q) for st in students for q in st.get("wrongs", [])})
        hwp = _prepare_hwp(progress)

        with tempfile.TemporaryDirectory(prefix="kimhyun_batch_") as td:
            td = Path(td)
            source_pdf = td / "source.pdf"
            image_dir = td / "question_images"

            write_progress(progress, "open", "원본 시험지를 여는 중")
            _open_source(hwp, job["source"])
            write_progress(progress, "convert", "문항 분석용 PDF를 한 번만 만드는 중")
            _save_source_pdf(hwp, str(source_pdf))
            _close_current_document(hwp)

            write_progress(progress, "analyze", "문항 위치를 한 번만 분석 중")
            from pdf_questions import detect_question_clips, render_question_images
            clips = detect_question_clips(str(source_pdf), int(job["question_count"]))
            write_progress(progress, "render", f"실제 오답 문항 {len(needed_questions)}개만 고속 준비 중")
            images = render_question_images(
                str(source_pdf), clips, str(image_dir), dpi=140,
                only_questions=set(needed_questions)
            )
            write_progress(progress, "render_done", f"오답 문항 {len(images)}개 준비 완료")

            total = len(students)
            for i, st in enumerate(students, 1):
                write_progress(progress, "student", f"[{i}/{total}] {st['student']} HWP 생성 중", current=i, total=total)
                _create_student_doc(hwp, st, images, st["output_hwp"])

            write_progress(progress, "done", f"학생 {total}명 HWP 생성 완료", current=total, total=total)
        return 0
    except Exception as e:
        write_progress(progress, "error", str(e), traceback.format_exc())
        return 2
    finally:
        _quit(hwp)
        pythoncom.CoUninitialize()


def worker(source: str, target_pdf: str, progress: str) -> int:
    pythoncom.CoInitialize()
    hwp = None
    try:
        hwp = _prepare_hwp(progress)
        write_progress(progress, "open", "시험지 여는 중")
        _open_source(hwp, source)
        write_progress(progress, "save", "문항 분석용 임시 PDF를 만드는 중")
        _save_source_pdf(hwp, target_pdf)
        write_progress(progress, "done", "시험지 분석 준비 완료")
        return 0
    except Exception as e:
        write_progress(progress, "error", str(e), traceback.format_exc())
        return 2
    finally:
        _quit(hwp)
        pythoncom.CoUninitialize()


def student_hwp_worker(manifest_path: str, output_hwp: str, progress: str) -> int:
    pythoncom.CoInitialize()
    hwp = None
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        hwp = _prepare_hwp(progress)
        images = {int(k): v for k, v in manifest["images"].items()}
        write_progress(progress, "student", f"{manifest['student']} HWP 생성 중")
        _create_student_doc(hwp, manifest, images, output_hwp)
        write_progress(progress, "done", f"{manifest['student']} HWP 완료")
        return 0
    except Exception as e:
        write_progress(progress, "error", str(e), traceback.format_exc())
        return 2
    finally:
        _quit(hwp)
        pythoncom.CoUninitialize()
