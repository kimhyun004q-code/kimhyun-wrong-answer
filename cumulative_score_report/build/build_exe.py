# -*- coding: utf-8 -*-
"""Windows EXE 빌드 설정. 같은 폴더에 source 파일을 배치한 뒤 실행."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "성적표만들기"
SEP = ";" if os.name == "nt" else ":"
SCRIPTS = ["build_xlsx.py", "run3.py", "report3.py", "parse.py", "discover.py", "_pw_install.py"]
BUNDLE_BROWSER = True
if BUNDLE_BROWSER:
    import playwright
    pkg = os.path.join(os.path.dirname(playwright.__file__), "driver", "package", ".local-browsers")
    if not os.path.isdir(pkg):
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH="0")
        rc = subprocess.call([sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"], env=env)
        if rc != 0 or not os.path.isdir(pkg):
            sys.exit("[중단] Chromium 설치 실패. 인터넷 연결을 확인하세요.")
missing = [f for f in SCRIPTS if not os.path.exists(os.path.join(HERE, f))]
if missing:
    sys.exit(f"[중단] 같은 폴더에 없는 파일: {', '.join(missing)}")
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
       "--name", NAME, "--collect-all", "playwright", "--hidden-import", "PIL._tkinter_finder",
       "--hidden-import", "olefile"]
for mod in ["pandas", "numpy", "scipy", "matplotlib", "torch", "tensorflow", "sklearn", "cv2",
            "transformers", "sympy", "opentelemetry", "narwhals", "fsspec", "pydantic", "regex",
            "jinja2", "IPython", "notebook", "pytest", "setuptools", "wheel"]:
    cmd += ["--exclude-module", mod]
for f in SCRIPTS:
    cmd += ["--add-data", f"{os.path.join(HERE, f)}{SEP}."]
icon = os.path.join(HERE, "icon.ico")
if os.path.exists(icon):
    cmd += ["--icon", icon]
cmd.append(os.path.join(HERE, "성적표_GUI.py"))
print("실행:", " ".join(cmd), "\n")
rc = subprocess.call(cmd, cwd=HERE)
if rc != 0:
    sys.exit(rc)
out = os.path.join(HERE, "dist", NAME)
print(f"완성: {out}")
