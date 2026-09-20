from pathlib import Path
import re

p = Path("app/ultrafast_core.py")
s = p.read_text(encoding="utf-8")

old = """def latex_to_hwp(expr: str) -> str:
    return _antigravity_postprocess(_latex_to_hwp_base(_antigravity_preprocess(expr)))
"""
if old not in s:
    raise SystemExit("latex_to_hwp anchor missing")

new = """def _latex_to_hwp_before_setfix(expr: str) -> str:
    return _antigravity_postprocess(_latex_to_hwp_base(_antigravity_preprocess(expr)))

def latex_to_hwp(expr: str) -> str:
    out = _latex_to_hwp_before_setfix(expr)
    out = out.replace('__{LBRACE}__', ' LEFT { ')
    out = out.replace('__{RBRACE}__', ' RIGHT } ')
    out = re.sub(r'(?i)\\bcup\\b', ' SMALLUNION ', out)
    out = re.sub(r'(?i)\\bcap\\b', ' SMALLINTER ', out)
    out = re.sub(r'(?i)\\bsetminus\\b', ' - ', out)
    return re.sub(r'\\s+', ' ', out).strip()
"""

s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("SETFIX POSTPROCESS APPLIED")
