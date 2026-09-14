from __future__ import annotations

import json
import os
import re
import time
import traceback
from pathlib import Path

import pythoncom
import win32com.client

from security import install_security_module


HWP_TYPELIB = "{7D2B6F3C-1D95-4E0C-BF5A-5EE564186FBC}"


def write_progress(path: str, state: str, message: str, error: str = "", **extra):
    data = {"state": state, "message": message, "error": error, "ts": time.time(), **extra}
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _register_security(hwp) -> None:
    registered = False
    for module_name in ("FilePathCheckerModule", "FilePathCheckerModuleExample"):
        try:
            if bool(hwp.RegisterModule("FilePathCheckDLL", module_name)):
                registered = True
                break
        except Exception:
            pass
    if not registered:
        raise RuntimeError("한컴 파일 접근 자동 허용 모듈 등록에 실패했습니다.")


def _new_hwp(visible: bool = False):
    """Force a new HWP instance and wrap it with makepy metadata when possible."""
    try:
        win32com.client.gencache.EnsureModule(HWP_TYPELIB, 0, 1, 0)
    except Exception:
        pass

    raw = win32com.client.DispatchEx("HWPFrame.HwpObject")
    try:
        hwp = win32com.client.gencache.EnsureDispatch(raw)
    except Exception:
        hwp = raw

    _register_security(hwp)
    try:
        hwp.XHwpWindows.Item(0).Visible = visible
    except Exception:
        try:
            hwp.XHwpWindows.Active_XHwpWindow.Visible = visible
        except Exception:
            pass
    try:
        hwp.SetMessageBoxMode(0x1000)
    except Exception:
        pass
    return hwp


def _quit(hwp) -> None:
    if hwp is None:
        return
    try:
        while int(hwp.XHwpDocuments.Count) > 0:
            try:
                hwp.XHwpDocuments.Item(0).Close(False)
            except Exception:
                break
    except Exception:
        pass
    try:
        hwp.Quit()
    except Exception:
        pass


def _open_source(hwp, source: str) -> None:
    path = str(Path(source).resolve())
    ok = False
    for arg in (
        "forceopen:true;versionwarning:false;suspendpassword:true",
        "forceopen:true;versionwarning:false",
        "forceopen:true",
        "",
    ):
        try:
            ok = bool(hwp.Open(path, "", arg))
        except Exception:
            ok = False
        if ok:
            break
    if not ok:
        raise RuntimeError("시험지 한글 파일을 열지 못했습니다.")


def _insert_text(hwp, text: str) -> None:
    p = hwp.HParameterSet.HInsertText
    hwp.HAction.GetDefault("InsertText", p.HSet)
    p.Text = text
    hwp.HAction.Execute("InsertText", p.HSet)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _looks_like_question(text: str) -> bool:
    t = _norm(text)
    if len(t) < 7:
        return False
    if t.startswith(("정답", "해설", "[출제의도]", "출제의도")):
        return False
    banned = (
        "시험이 시작", "답안지", "계산은 문제지", "시간이 남", "연습은 실전",
        "성명", "이름을", "유의사항", "주의사항",
    )
    if any(x in t for x in banned):
        return False
    if "?" in t or "？" in t:
        return True
    return bool(re.search(r"(?:구하시오|고르시오|구하여라|구해라|쓰시오|나타내시오)[.。\s]*$", t))


def _get_pos(hwp) -> tuple[int, int, int]:
    try:
        p = hwp.GetPos()
        if isinstance(p, (tuple, list)) and len(p) >= 3:
            return int(p[0]), int(p[1]), int(p[2])
    except Exception:
        pass
    pset = hwp.GetPosBySet()
    return int(pset.Item("List")), int(pset.Item("Para")), int(pset.Item("Pos"))


def _move_to_scan_pos(hwp) -> None:
    try:
        hwp.MovePos(201, 0, 0)
    except Exception:
        hwp.MovePos(201)


def _scan_question_ranges(hwp, expected_count: int, progress: str) -> dict[int, tuple[tuple[int, int, int], tuple[int, int, int]]]:
    """Find question paragraph starts directly inside HWP; no PDF/image conversion."""
    try:
        hwp.HAction.Run("MoveDocBegin")
    except Exception:
        try:
            hwp.MovePos(2, 0, 0)
        except Exception:
            pass

    heading_seen = False
    after_heading: list[tuple[int, int, int, str]] = []
    all_candidates: list[tuple[int, int, int, str]] = []
    seen_para: set[tuple[int, int]] = set()
    solution_pos: tuple[int, int, int] | None = None

    scan_started = False
    try:
        try:
            hwp.InitScan(0x07, 0x0077, 0, 0, -1, -1)
        except Exception:
            hwp.InitScan(0x07, 0x0077)
        scan_started = True

        while True:
            result = hwp.GetText()
            if not isinstance(result, (tuple, list)) or len(result) < 2:
                raise RuntimeError("한글 문서 텍스트 스캔 결과를 읽지 못했습니다.")
            state, text = int(result[0]), str(result[1] or "")
            if state == 1:
                break
            if state == 0 or not text.strip():
                continue

            _move_to_scan_pos(hwp)
            list_id, para, _ = _get_pos(hwp)
            t = _norm(text)
            compact = re.sub(r"\s+", "", t)

            if "정답및해설" in compact or "정답및풀이" in compact:
                if list_id == 0:
                    solution_pos = (list_id, para, 0)
                if all_candidates:
                    break
                continue

            if "5지선다형" in compact or "객관식" in compact:
                heading_seen = True
                continue

            if list_id != 0 or not _looks_like_question(t):
                continue

            key = (list_id, para)
            if key in seen_para:
                continue
            seen_para.add(key)
            item = (list_id, para, 0, t)
            all_candidates.append(item)
            if heading_seen:
                after_heading.append(item)

            n = len(after_heading if heading_seen else all_candidates)
            if n <= expected_count:
                write_progress(progress, "scan", f"원본 한글에서 문항 위치 확인 중: {n}/{expected_count}", current=n, total=expected_count)
    finally:
        if scan_started:
            try:
                hwp.ReleaseScan()
            except Exception:
                pass

    candidates = after_heading if len(after_heading) >= expected_count else all_candidates
    if len(candidates) < expected_count:
        preview = "\n".join(f"- {i+1}: {x[3][:90]}" for i, x in enumerate(candidates))
        raise RuntimeError(
            f"원본 한글에서 문항 시작을 {len(candidates)}개만 찾았습니다. "
            f"엑셀상 문항 수는 {expected_count}개입니다.\n{preview}"
        )

    if len(candidates) > expected_count:
        if heading_seen and len(after_heading) >= expected_count:
            candidates = candidates[:expected_count]
        else:
            candidates = candidates[-expected_count:]

    # Last question ends immediately before the answer/solution section.
    if solution_pos is None or solution_pos[0] != candidates[-1][0]:
        try:
            hwp.HAction.Run("MoveDocEnd")
        except Exception:
            hwp.MovePos(3, 0, 0)
        solution_pos = _get_pos(hwp)

    starts = [(x[0], x[1], x[2]) for x in candidates]
    ranges = {}
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else solution_pos
        if start[0] != end[0]:
            raise RuntimeError(
                f"{i+1}번 문항 범위가 서로 다른 한글 영역(List)에 걸쳐 있어 자동 복사가 어렵습니다. "
                "이 시험지 구조에 맞게 범위 인식을 조정해야 합니다."
            )
        if end[1] < start[1] or (end[1] == start[1] and end[2] <= start[2]):
            raise RuntimeError(f"{i+1}번 문항의 시작/끝 위치가 올바르지 않습니다.")
        ranges[i + 1] = (start, end)

    return ranges


def _select_and_copy(src, start: tuple[int, int, int], end: tuple[int, int, int]) -> None:
    slist, spara, spos = start
    elist, epara, epos = end
    if slist != elist:
        raise RuntimeError("문항 복사 범위의 한글 영역이 서로 다릅니다.")

    if not bool(src.SetPos(slist, spara, spos)):
        raise RuntimeError("원본 문항 시작 위치로 이동하지 못했습니다.")
    if not bool(src.SelectText(spara, spos, epara, epos)):
        raise RuntimeError("원본 문항 범위를 선택하지 못했습니다.")
    if not bool(src.HAction.Run("Copy")):
        raise RuntimeError("원본 문항을 클립보드로 복사하지 못했습니다.")


def _paste(dst) -> None:
    # Clipboard is normally synchronous, but a short retry handles large equations/pictures.
    for delay in (0.0, 0.02, 0.05):
        if delay:
            time.sleep(delay)
        try:
            if bool(dst.HAction.Run("Paste")):
                return
        except Exception:
            pass
    raise RuntimeError("복사한 문항을 학생 한글 파일에 붙여넣지 못했습니다.")


def _new_output_doc(dst) -> None:
    try:
        dst.HAction.Run("FileNew")
    except Exception:
        try:
            dst.XHwpDocuments.Add(1)
        except Exception as e:
            raise RuntimeError(f"새 한글 문서를 만들지 못했습니다: {e}")


def _close_active_doc(dst) -> None:
    try:
        dst.XHwpDocuments.Active_XHwpDocument.Close(False)
        return
    except Exception:
        pass
    try:
        dst.XHwpDocuments.Item(0).Close(False)
    except Exception:
        pass


def _save_student(dst, student_job: dict, output_hwp: str) -> None:
    out = str(Path(output_hwp).resolve())
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    ok = False
    try:
        ok = bool(dst.SaveAs(out, "HWP", ""))
    except Exception:
        ok = False
    if not ok or not Path(out).exists() or Path(out).stat().st_size < 1024:
        raise RuntimeError(f"{student_job['student']} HWP 저장에 실패했습니다.")


def _create_student_from_source(src, dst, student_job: dict, ranges: dict[int, tuple], progress: str, index: int, total: int) -> None:
    _new_output_doc(dst)
    header = (
        f"{student_job['test_name']}\r\n"
        f"학생명 : {student_job['student']}\r\n"
        f"시험일 : {student_job['test_date']}\r\n"
        f"오답문항 : {', '.join(str(x) for x in student_job['wrongs'])}번\r\n"
        "----------------------------------------\r\n\r\n"
    )
    _insert_text(dst, header)

    first = True
    for q in student_job["wrongs"]:
        q = int(q)
        if q not in ranges:
            continue
        if not first:
            try:
                dst.HAction.Run("BreakPage")
            except Exception:
                _insert_text(dst, "\r\n\r\n")
        first = False

        _select_and_copy(src, *ranges[q])
        _paste(dst)
        try:
            dst.HAction.Run("Cancel")
        except Exception:
            pass

    write_progress(
        progress,
        "save_student",
        f"[{index}/{total}] {student_job['student']} 저장 중",
        current=index,
        total=total,
    )
    _save_student(dst, student_job, student_job["output_hwp"])
    _close_active_doc(dst)


def batch_hwp_worker(manifest_path: str, progress: str) -> int:
    """Direct HWP mode: no PDF, no PNG/JPEG. Rich question blocks are copied inside Hangul."""
    pythoncom.CoInitialize()
    src = None
    dst = None
    try:
        job = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        students = job["students"]
        if not students:
            raise RuntimeError("오답이 있는 학생이 없습니다.")

        write_progress(progress, "security", "한글 파일 접근 자동 허용 설정 중")
        install_security_module()

        write_progress(progress, "launch", "직접복사 모드: 한컴 한글 준비 중")
        src = _new_hwp(visible=False)
        dst = _new_hwp(visible=False)

        write_progress(progress, "open", "원본 시험지를 여는 중")
        _open_source(src, job["source"])

        write_progress(progress, "scan", "PDF 변환 없이 원본 한글에서 문항을 바로 찾는 중")
        ranges = _scan_question_ranges(src, int(job["question_count"]), progress)
        write_progress(progress, "scan_done", f"문항 {len(ranges)}개 인식 완료 — 바로 학생별 HWP 생성 시작")

        total = len(students)
        for i, st in enumerate(students, 1):
            write_progress(progress, "student", f"[{i}/{total}] {st['student']} 원본 문제 직접 복사 중", current=i, total=total)
            _create_student_from_source(src, dst, st, ranges, progress, i, total)

        write_progress(progress, "done", f"학생 {total}명 HWP 생성 완료", current=total, total=total)
        return 0
    except Exception as e:
        write_progress(progress, "error", str(e), traceback.format_exc())
        return 2
    finally:
        _quit(dst)
        _quit(src)
        pythoncom.CoUninitialize()


# Backward-compatible entry points kept for older command-line switches.
def worker(source: str, target_hwp: str, progress: str) -> int:
    write_progress(progress, "error", "이 버전은 학생별 직접복사 모드만 사용합니다.")
    return 2


def student_hwp_worker(manifest_path: str, output_hwp: str, progress: str) -> int:
    write_progress(progress, "error", "이 버전은 일괄 직접복사 모드만 사용합니다.")
    return 2
