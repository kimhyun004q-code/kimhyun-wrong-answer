from __future__ import annotations
import json, os, time, traceback
from pathlib import Path
import pythoncom
import win32com.client
from security import install_security_module

def write_progress(path: str, state: str, message: str, error: str = ""):
    data = {"state": state, "message": message, "error": error, "ts": time.time()}
    tmp = Path(path).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

def worker(source: str, target_pdf: str, progress: str) -> int:
    pythoncom.CoInitialize()
    hwp = None
    try:
        write_progress(progress, "security", "한글 파일 접근 자동 허용 설정 중")
        install_security_module()
        write_progress(progress, "launch", "한컴 한글 시작 중")
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
            raise RuntimeError("한컴 파일 접근 자동 허용 모듈 등록에 실패했습니다.")
        try:
            hwp.XHwpWindows.Item(0).Visible = False
        except Exception:
            pass
        try:
            hwp.SetMessageBoxMode(0x1000)
        except Exception:
            pass
        write_progress(progress, "open", "시험지 여는 중")
        ok = False
        try:
            ok = bool(hwp.Open(str(Path(source).resolve()), "", "forceopen:true"))
        except Exception:
            ok = bool(hwp.Open(str(Path(source).resolve()), "", ""))
        if not ok:
            raise RuntimeError("시험지 한글 파일을 열지 못했습니다.")
        write_progress(progress, "save", "원본 시험지를 PDF로 변환 중")
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
        if not ok or not Path(out).exists():
            raise RuntimeError("한글의 PDF 변환에 실패했습니다.")
        write_progress(progress, "done", "시험지 PDF 변환 완료")
        return 0
    except Exception as e:
        write_progress(progress, "error", str(e), traceback.format_exc())
        return 2
    finally:
        if hwp is not None:
            try:
                hwp.XHwpDocuments.Item(0).Close(False)
            except Exception:
                pass
            try:
                hwp.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()
