from pathlib import Path
import re

p = Path('app/ultrafast_core.py')
s = p.read_text(encoding='utf-8')

helper = r'''
def _protect_set_delimiters(expr: str) -> str:
    """Protect visible set braces from Hancom equation grouping braces."""
    s = expr.replace(r'\{', 'ZZSETLBRACEXX').replace(r'\}', 'ZZSETRBRACEXX')
    pat = re.compile(r'\{([^{}]*)\}')
    for _ in range(8):
        changed = False
        out = []
        pos = 0
        for m in pat.finditer(s):
            inner = m.group(1)
            prefix = s[:m.start()].rstrip()
            whole = (not s[:m.start()].strip() and not s[m.end():].strip())
            after_relation = bool(re.search(r'(?:=|!=|<=|>=|<|>|\\in|\\notin|\\ni|\\subset(?:eq)?|\\supset(?:eq)?|\\cup|\\cap|\\setminus|[-+])\s*$', prefix))
            set_like_content = bool(re.search(r'[,|]', inner)) or bool(re.fullmatch(r'\s*[A-Za-z0-9]+\s*', inner))
            command_arg = bool(re.search(r'\\[A-Za-z]+\s*$', prefix))
            script_arg = prefix.endswith('^') or prefix.endswith('_')
            if (whole or after_relation) and set_like_content and not command_arg and not script_arg:
                out.append(s[pos:m.start()])
                out.append('ZZSETLBRACEXX' + inner + 'ZZSETRBRACEXX')
                pos = m.end()
                changed = True
        if not changed:
            break
        out.append(s[pos:])
        s = ''.join(out)
    return s
'''

anchor = '\ndef _latex_to_hwp_base(expr: str) -> str:\n'
if 'def _protect_set_delimiters' not in s:
    if anchor not in s:
        raise SystemExit('set helper anchor missing')
    s = s.replace(anchor, '\n' + helper + anchor, 1)

anchor = "    s = s.replace('&nbsp;', ' ')\n"
if 's = _protect_set_delimiters(s)' not in s:
    if anchor not in s:
        raise SystemExit('set protect call anchor missing')
    s = s.replace(anchor, anchor + '    s = _protect_set_delimiters(s)\n', 1)

old = "        r'\\$': '__DOLLAR__', r'\\{': '__LBRACE__', r'\\}': '__RBRACE__',\n"
new = "        r'\\$': '__DOLLAR__',\n"
if old not in s:
    raise SystemExit('placeholder brace anchor missing')
s = s.replace(old, new, 1)

old = "        r'\\emptyset':'EMPTYSET', r'\\varnothing':'EMPTYSET', r'\\cup':'cup', r'\\cap':'cap',\n"
new = "        r'\\emptyset':'EMPTYSET', r'\\varnothing':'EMPTYSET', r'\\cup':'SMALLUNION', r'\\cap':'SMALLINTER', r'\\setminus':'-',\n"
if old not in s:
    raise SystemExit('cup/cap map anchor missing')
s = s.replace(old, new, 1)

old = "    s=s.replace(r'\\{',' { ').replace(r'\\}',' } ')\n"
if old not in s:
    raise SystemExit('brace delimiter anchor missing')
s = s.replace(old, '', 1)

old = "        '∪':'cup','∩':'cap','∅':'EMPTYSET','∞':'INF','π':'pi','θ':'theta','α':'alpha','β':'beta','γ':'gamma',\n"
new = "        '∪':'SMALLUNION','∩':'SMALLINTER','∅':'EMPTYSET','∞':'INF','π':'pi','θ':'theta','α':'alpha','β':'beta','γ':'gamma',\n"
if old not in s:
    raise SystemExit('unicode cup/cap anchor missing')
s = s.replace(old, new, 1)

anchor = "    # Restore escaped literals.\n"
restore_visible = "    # Restore visible set delimiters using Hancom delimiter syntax.\n    s=s.replace('ZZSETLBRACEXX', ' LEFT { ').replace('ZZSETRBRACEXX', ' RIGHT } ')\n\n"
if restore_visible not in s:
    if anchor not in s:
        raise SystemExit('restore anchor missing')
    s = s.replace(anchor, restore_visible + anchor, 1)

old = "    restore = {'__PERCENT__':'%', '__AMP__':'&', '__HASH__':'#', '__UNDERSCORE__':'_', '__DOLLAR__':'$', '__LBRACE__':'{', '__RBRACE__':'}'}\n"
new = "    restore = {'__PERCENT__':'%', '__AMP__':'&', '__HASH__':'#', '__UNDERSCORE__':'_', '__DOLLAR__':'$'}\n"
if old not in s:
    raise SystemExit('restore map anchor missing')
s = s.replace(old, new, 1)

anchor = "    # Unknown LaTeX commands: remove leading slash but do not expose raw source.\n"
bare_fix = "    # Bare cup/cap from older paths must become Hancom set operators.\n    s=re.sub(r'(?i)\\bcup\\b', ' SMALLUNION ', s)\n    s=re.sub(r'(?i)\\bcap\\b', ' SMALLINTER ', s)\n\n"
if bare_fix not in s:
    if anchor not in s:
        raise SystemExit('bare cup/cap anchor missing')
    s = s.replace(anchor, bare_fix + anchor, 1)

old = "    s=re.sub(r'(?i)LEFT|RIGHT','',s)\n"
if old not in s:
    raise SystemExit('LEFT/RIGHT cleanup anchor missing')
s = s.replace(old, '', 1)

p.write_text(s, encoding='utf-8')
print('SET PATCH APPLIED')
