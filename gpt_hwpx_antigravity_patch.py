from pathlib import Path
import re


def patch_app(path: str):
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    needle = "u=ctypes.windll.user32; k=ctypes.windll.kernel32\n"
    patch_text = '''u=ctypes.windll.user32; k=ctypes.windll.kernel32
    u.OpenClipboard.argtypes=[ctypes.c_void_p]; u.OpenClipboard.restype=ctypes.c_bool
    u.CloseClipboard.argtypes=[]; u.CloseClipboard.restype=ctypes.c_bool
    u.GetClipboardData.argtypes=[ctypes.c_uint]; u.GetClipboardData.restype=ctypes.c_void_p
    k.GlobalLock.argtypes=[ctypes.c_void_p]; k.GlobalLock.restype=ctypes.c_void_p
    k.GlobalUnlock.argtypes=[ctypes.c_void_p]; k.GlobalUnlock.restype=ctypes.c_bool
'''
    if 'GetClipboardData.restype=ctypes.c_void_p' not in s and needle in s:
        s = s.replace(needle, patch_text, 1)
    p.write_text(s, encoding='utf-8')


def patch_core(path: str):
    p = Path(path)
    s = p.read_text(encoding='utf-8')

    a = s.index('def normalize_geometry_text(text: str) -> str:')
    b = s.index('\ndef romanize_math_labels', a)
    new = r'''def normalize_geometry_text(text: str) -> str:
    """Normalize geometry labels while preserving ordinary variables/functions."""
    text=text.replace('⊥', r'\\perp').replace('∥', r'\\parallel')
    text=re.sub(r'∠\s*([A-Z]{1,6})', lambda m:r'\\angle '+m.group(1), text)
    text=re.sub(r'\^\s*\{\s*\\(?:circ|degree)\s*\}', r'^{circ}', text)
    text=re.sub(r'\^\s*\\(?:circ|degree)\b', r'^{circ}', text)
    nouns=r'(점|삼각형|사각형|오각형|육각형|선분|직선|반직선|평면|원)'
    text=re.sub(nouns+r'\s+\$\s*([A-Z]{1,6})\s*\$', lambda m:m.group(1)+' $\\mathrm{'+m.group(2)+'}$', text)
    text=re.sub(nouns+r'\s+\\\(\s*([A-Z]{1,6})\s*\\\)', lambda m:m.group(1)+r' \(' + r'\\mathrm{'+m.group(2)+'}' + r'\)', text)
    text=re.sub(nouns+r'\s+`\s*([A-Z]{1,6})\s*`', lambda m:m.group(1)+' `\\mathrm{'+m.group(2)+'}`', text)
    text=re.sub(nouns+r'\s+\[\[INLINE_EQ\]\]\s*([A-Z]{1,6})\s*\[\[/INLINE_EQ\]\]', lambda m:m.group(1)+' [[INLINE_EQ]]\\mathrm{'+m.group(2)+'}[[/INLINE_EQ]]', text)
    text=re.sub(nouns+r'\s+([A-Z]{1,6})(?![A-Za-z0-9])', lambda m:m.group(1)+' `\\mathrm{'+m.group(2)+'}`', text)
    return text
'''
    s = s[:a] + new + s[b:]

    anchor = "    s = s.replace('&nbsp;', ' ')\n"
    relation = r'''    # Normalize equality/inequality as HWP relation tokens with even math spacing.
    s = s.replace('&lt;', '<').replace('&gt;', '>').replace('＜', '<').replace('＞', '>')
    s = s.replace('≤', '@@LEQ@@').replace('≥', '@@GEQ@@').replace('≠', '@@NEQ@@')
    s = re.sub(r'\\(?:leqslant|leq|le)\b', '@@LEQ@@', s)
    s = re.sub(r'\\(?:geqslant|geq|ge)\b', '@@GEQ@@', s)
    s = re.sub(r'\\(?:neq|ne)\b', '@@NEQ@@', s)
    s = re.sub(r'\\(?:lt|less)\b', '@@LT@@', s)
    s = re.sub(r'\\(?:gt|greater)\b', '@@GT@@', s)
    s = re.sub(r'(?<![<>=!])<=', '@@LEQ@@', s)
    s = re.sub(r'(?<![<>=!])>=', '@@GEQ@@', s)
    s = re.sub(r'!=', '@@NEQ@@', s)
    s = re.sub(r'\s*<\s*', '@@LT@@', s)
    s = re.sub(r'\s*>\s*', '@@GT@@', s)
    s = re.sub(r'\s*=\s*', '@@EQ@@', s)
    for key,val in (
        ('@@LEQ@@',' ~LEQ~ '), ('@@GEQ@@',' ~GEQ~ '), ('@@NEQ@@',' ~neq~ '),
        ('@@LT@@',' ~<~ '), ('@@GT@@',' ~>~ '), ('@@EQ@@',' ~=~ ')):
        s=s.replace(key,val)

    s = re.sub(r'\\sqrt(\[[^\]]+\])\s*([0-9A-Za-z])', r'\\sqrt\1{\2}', s)
    s = re.sub(r'\\sqrt\s*([0-9A-Za-z])', r'\\sqrt{\1}', s)
'''
    if anchor in s:
        s = s.replace(anchor, anchor + relation, 1)

    s = s.replace("if index is None: out.append('sqrt {'+latex_to_hwp(g)+'}')",
                  "if index is None: out.append(' sqrt {'+latex_to_hwp(g)+'} ')")
    s = s.replace("else: out.append('root {'+latex_to_hwp(index)+'} of {'+latex_to_hwp(g)+'}')",
                  "else: out.append(' root {'+latex_to_hwp(index)+'} of {'+latex_to_hwp(g)+'} ')")

    s = s.replace("lambda cmd,a: '{'+latex_to_hwp(a[0])+'} CHOOSE {'+latex_to_hwp(a[1])+'}')",
                  "lambda cmd,a: '{}_{'+latex_to_hwp(a[0])+'} rm C _{'+latex_to_hwp(a[1])+'}')")

    needle = "        r'\\underline': lambda a: 'under {'+latex_to_hwp(a)+'}',\n"
    extras = """        r'\\overrightarrow': lambda a: 'vec {'+latex_to_hwp(a)+'}',
        r'\\overleftrightarrow': lambda a: 'dyad {'+latex_to_hwp(a)+'}',
        r'\\wideparen': lambda a: 'arch {'+latex_to_hwp(a)+'}',
        r'\\overparen': lambda a: 'arch {'+latex_to_hwp(a)+'}',
"""
    if needle in s and r"r'\overleftrightarrow'" not in s:
        s = s.replace(needle, needle + extras, 1)

    s = s.replace(
        "        r'\\angle':'angle', r'\\perp':'bot', r'\\parallel':'parallel', r'\\therefore':'therefore', r'\\because':'because',",
        "        r'\\angle':'angle', r'\\triangle':'TRIANGLE', r'\\square':'□', r'\\perp':'bot', r'\\parallel':'parallel', r'\\therefore':'therefore', r'\\because':'because',"
    )

    needle2 = "    # \\begin{...} leftovers should never print literally.\n"
    decor = r'''    # Decorated objects must be grouped before a following exponent.
    s = re.sub(r'(?<![A-Za-z])((?:bar|vec|hat|tilde|under|dyad|arch)\s*\{[^{}]*\})\s*\^\s*(\{[^{}]+\}|[0-9A-Za-z])',
               lambda m: '{'+m.group(1)+'}^'+(m.group(2) if m.group(2).startswith('{') else '{'+m.group(2)+'}'), s)

'''
    if needle2 in s:
        s = s.replace(needle2, decor + needle2, 1)

    s = s.replace("        r'\\geq':'>=', r'\\ge':'>=', r'\\leq':'<=', r'\\le':'<=', r'\\neq':'!=', r'\\ne':'!=', r'\\approx':'APPROX',",
                  "        r'\\geq':'~GEQ~', r'\\ge':'~GEQ~', r'\\leq':'~LEQ~', r'\\le':'~LEQ~', r'\\neq':'~neq~', r'\\ne':'~neq~', r'\\approx':'APPROX',")
    s = s.replace("        '≤':'<=','≥':'>=','≠':'!=','→':'rarrow','⇒':'RARROW','⇔':'LRARROW','↔':'LRARROW',",
                  "        '≤':'~LEQ~','≥':'~GEQ~','≠':'~neq~','→':'rarrow','⇒':'RARROW','⇔':'LRARROW','↔':'LRARROW',")

    p.write_text(s, encoding='utf-8')


if __name__ == '__main__':
    patch_app('app/ultrafast_app.py')
    patch_core('app/ultrafast_core.py')
