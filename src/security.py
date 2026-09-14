from __future__ import annotations
import os, sys, shutil, hashlib, winreg
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "KimHyunWrongAnswer"
SECURITY_DIR = APP_DIR / "security"
DLL_NAME = "FilePathCheckerModule.dll"

def resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    return base / name

def _same_file(a: Path, b: Path) -> bool:
    if not a.exists() or not b.exists():
        return False
    def h(p):
        x = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                x.update(chunk)
        return x.hexdigest()
    return h(a) == h(b)

def install_security_module() -> Path:
    source = resource_path(DLL_NAME)
    if not source.exists():
        raise RuntimeError(f"보안 모듈이 실행파일에 포함되지 않았습니다: {source}")

    SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    dest = SECURITY_DIR / DLL_NAME
    if not _same_file(source, dest):
        shutil.copy2(source, dest)

    key_paths = [
        r"Software\HNC\HwpAutomation\Modules",
        r"Software\HNC\HwpUserAction\Modules",
    ]
    views = [0]
    if hasattr(winreg, "KEY_WOW64_32KEY"):
        views += [winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY]

    errors = []
    for kp in key_paths:
        for view in views:
            try:
                access = winreg.KEY_SET_VALUE | view
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, kp, 0, access) as k:
                    winreg.SetValueEx(k, "FilePathCheckerModule", 0, winreg.REG_SZ, str(dest))
            except OSError as e:
                errors.append(f"{kp} view={view}: {e}")

    if len(errors) >= len(key_paths) * len(views):
        raise RuntimeError("한컴 파일 접근 허용 모듈을 자동 등록하지 못했습니다.\n" + "\n".join(errors))
    return dest
