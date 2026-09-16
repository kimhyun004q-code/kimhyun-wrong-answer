from __future__ import annotations

import ctypes
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import app

CF_UNICODETEXT = 13
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_user32.OpenClipboard.argtypes = [ctypes.c_void_p]
_user32.OpenClipboard.restype = ctypes.c_bool
_user32.CloseClipboard.argtypes = []
_user32.CloseClipboard.restype = ctypes.c_bool
_user32.GetClipboardData.argtypes = [ctypes.c_uint]
_user32.GetClipboardData.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalUnlock.restype = ctypes.c_bool


def message(text: str, error: bool = False):
    flags = 0x10 if error else 0x40
    _user32.MessageBoxW(None, text, 'GPT → HWPX', flags)


def clipboard_text() -> str:
    for _ in range(12):
        if _user32.OpenClipboard(None):
            try:
                h = _user32.GetClipboardData(CF_UNICODETEXT)
                if not h:
                    return ''
                p = _kernel32.GlobalLock(h)
                if not p:
                    return ''
                try:
                    return ctypes.wstring_at(p)
                finally:
                    _kernel32.GlobalUnlock(h)
            finally:
                _user32.CloseClipboard()
        import time
        time.sleep(0.05)
    return ''


def _candidate_answer(s: str) -> bool:
    s = s.strip()
    if not s or len(s) > 60:
        return False
    if re.fullmatch(r'\[[^\]]+\]', s):
        return False
    if s.startswith('[[TIKZ]]') or s.startswith('[[DISPLAY_EQ]]') or s.startswith('[[INLINE_EQ]]'):
        return False
    return True


def normalize_answer_first(raw: str) -> tuple[str, str]:
    """Return (normalized_text, answer).

    Contract: output always starts with exactly one '[정답] 실제정답' line,
    followed by exactly one '[해설]' line.  Existing math/TikZ tags remain intact.
    """
    text = raw.replace('\r\n', '\n').replace('\r', '\n').strip()
    answer = ''

    # 1) Dedicated ANSWER tag has the highest priority.
    tagged = re.findall(r'\[\[ANSWER\]\](.*?)\[\[/ANSWER\]\]', text, flags=re.S | re.I)
    for item in tagged:
        val = ' '.join(x.strip() for x in item.splitlines() if x.strip())
        if val:
            answer = val
    text = re.sub(r'\[\[ANSWER\]\].*?\[\[/ANSWER\]\]', '\n', text, flags=re.S | re.I)

    lines = text.split('\n')
    kept: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        st = line.strip()

        # Same-line form: [정답] 47
        m = re.match(r'^\s*\[정답\]\s*(.*?)\s*$', line)
        if m:
            val = m.group(1).strip()
            if val:
                answer = answer or val
                i += 1
                continue

            # Empty [정답] line.  Capture the following short value only when
            # it occurs before a real explanation header.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if not answer and j < len(lines) and lines[j].strip() != '[해설]' and _candidate_answer(lines[j]):
                answer = lines[j].strip()
                i = j + 1
                continue
            i += 1
            continue

        kept.append(line)
        i += 1

    text = '\n'.join(kept)

    # 2) Repair the malformed pattern seen in the current output/input:
    #    [해설] / 30번 / [해설]  -> answer=30번, body starts after second [해설].
    if not answer:
        m = re.search(r'(?ms)^\s*\[해설\]\s*\n\s*([^\n]+?)\s*\n\s*\[해설\]\s*$', text)
        if m and _candidate_answer(m.group(1)):
            answer = m.group(1).strip()
            text = text[:m.start()] + '\n[해설]\n' + text[m.end():]

    # 3) Last-resort answer patterns used by ordinary ChatGPT prose.
    if not answer:
        m = re.search(r'(?im)^\s*정답\s*(?:은|:|：)?\s*`?([^`\n]{1,50})`?\s*$', text)
        if m and _candidate_answer(m.group(1)):
            answer = m.group(1).strip().rstrip('.')
            text = text[:m.start()] + text[m.end():]
    if not answer:
        boxes = re.findall(r'\\boxed\s*\{([^{}]{1,50})\}', text)
        if boxes:
            answer = boxes[-1].strip()

    if not answer:
        answer = '정답 확인 필요'

    # Remove all standalone explanation headers.  We add exactly one ourselves.
    text = re.sub(r'(?im)^\s*\[해설\]\s*$', '', text)
    # Remove accidental empty standalone answer headers that survived unusual spacing.
    text = re.sub(r'(?im)^\s*\[정답\]\s*$', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    normalized = f'[정답] {answer}\n[해설]'
    if text:
        normalized += '\n' + text
    return normalized, answer


def output_path(folder: Path | None = None) -> Path:
    d = folder or (app.desktop_dir() / 'GPT_HWPX')
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    p = d / f'GPT해설_{stamp}.hwpx'
    n = 2
    while p.exists():
        p = d / f'GPT해설_{stamp}_{n}.hwpx'
        n += 1
    return p


def run_conversion(raw: str, folder: Path | None = None, open_after: bool = True) -> Path:
    normalized, _ = normalize_answer_first(raw)
    out = output_path(folder)
    app.convert_all(normalized, out, prefer_vector=True)
    if open_after:
        try:
            os.startfile(str(out))
        except Exception:
            pass
    return out


def main(argv: list[str]) -> int:
    test_input = None
    output_dir = None
    no_open = False
    i = 0
    while i < len(argv):
        if argv[i] == '--test-input' and i + 1 < len(argv):
            test_input = Path(argv[i + 1]); i += 2; continue
        if argv[i] == '--output-dir' and i + 1 < len(argv):
            output_dir = Path(argv[i + 1]); i += 2; continue
        if argv[i] == '--no-open':
            no_open = True; i += 1; continue
        i += 1

    try:
        raw = test_input.read_text(encoding='utf-8-sig') if test_input else clipboard_text()
        if not raw.strip():
            message('ChatGPT 응답을 먼저 복사(Ctrl+C)한 뒤 다시 실행해주세요.', True)
            return 2
        out = run_conversion(raw, output_dir, open_after=not no_open)
        # Normal one-click mode stays silent on success: double-click -> document opens.
        if test_input:
            print(out)
        return 0
    except Exception as e:
        message(str(e), True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
