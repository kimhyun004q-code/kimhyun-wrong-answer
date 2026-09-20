from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
HS = 'http://www.hancom.co.kr/hwpml/2011/section'
NS = {'hp': HP, 'hs': HS}
ET.register_namespace('hp', HP)
ET.register_namespace('hs', HS)


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / name


def app_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def qname(ns: str, tag: str) -> str:
    return f'{{{ns}}}{tag}'


def extract_group(s: str, start: int, opening='{', closing='}'):
    if start >= len(s) or s[start] != opening:
        return None, start
    depth = 0
    i = start
    while i < len(s):
        if s[i] == opening:
            depth += 1
        elif s[i] == closing:
            depth -= 1
            if depth == 0:
                return s[start+1:i], i+1
        i += 1
    return None, start


def strip_outer_math_delimiters(s: str) -> str:
    s = s.strip()
    pairs = [('$$','$$'), ('\\[','\\]'), ('\\(','\\)')]
    for a,b in pairs:
        if s.startswith(a) and s.endswith(b):
            return s[len(a):-len(b)].strip()
    if len(s) >= 2 and s[0] == '$' and s[-1] == '$':
        return s[1:-1].strip()
    return s


def contains_korean(s: str) -> bool:
    return bool(re.search(r'[가-힣]', s))


def text_in_equation(s: str) -> str:
    s = s.strip()
    if not s:
        return ''
    # Quoted equation text is safer for Korean/long strings.
    s = s.replace('"', "'")
    if contains_korean(s) or len(s) > 8:
        return f'"{s}"'
    return f'rm {s} it'


def replace_command_groups(s: str, commands, arity, builder):
    """Balanced-brace replacement for LaTeX commands."""
    changed = False
    pos = 0
    out = []
    while pos < len(s):
        found = None
        found_cmd = None
        for cmd in commands:
            idx = s.find(cmd, pos)
            if idx >= 0 and (found is None or idx < found):
                found = idx; found_cmd = cmd
        if found is None:
            out.append(s[pos:]); break
        out.append(s[pos:found])
        j = found + len(found_cmd)
        while j < len(s) and s[j].isspace(): j += 1
        args = []
        ok = True
        for _ in range(arity):
            g, nxt = extract_group(s, j)
            if g is None:
                ok = False; break
            args.append(g); j = nxt
            while j < len(s) and s[j].isspace(): j += 1
        if not ok:
            out.append(found_cmd)
            pos = found + len(found_cmd)
            continue
        out.append(builder(found_cmd, args))
        pos = j
        changed = True
    return ''.join(out), changed


def split_array_rows(body: str):
    # LaTeX rows are separated by \\; keep braces untouched.
    rows = re.split(r'\\\\(?:\s*\[[^\]]*\])?', body)
    cleaned = []
    for row in rows:
        row = row.strip()
        row = re.sub(r'^\\hline\s*', '', row)
        row = re.sub(r'\\hline\s*$', '', row)
        if row:
            cleaned.append(row)
    return cleaned


def split_unbraced_ampersands(row: str):
    parts, buf = [], []
    depth = 0
    i = 0
    while i < len(row):
        c = row[i]
        if c == '{': depth += 1
        elif c == '}': depth = max(0, depth-1)
        if c == '&' and depth == 0:
            parts.append(''.join(buf).strip()); buf=[]
        else:
            buf.append(c)
        i += 1
    parts.append(''.join(buf).strip())
    return parts


def convert_array(expr: str):
    m = re.fullmatch(r'\s*\\begin\{array\}\{([^}]*)\}(.*?)\\end\{array\}\s*', expr, re.S)
    if not m:
        return None
    spec, body = m.group(1), m.group(2)
    rows = split_array_rows(body)
    if not rows:
        return ''
    converted_rows = []
    maxcols = 1
    for row in rows:
        cells = split_unbraced_ampersands(row)
        maxcols = max(maxcols, len(cells))
        converted_rows.append(' & '.join(latex_to_hwp(c) for c in cells))
    # HWP MATRIX uses # for row breaks and & for columns. Plain matrix has no delimiters.
    return 'matrix{' + ' # '.join(converted_rows) + '}'


def convert_environment(expr: str):
    # array
    a = convert_array(expr)
    if a is not None:
        return a
    # aligned / align / gathered -> line-aligned equations
    m = re.fullmatch(r'\s*\\begin\{(?:aligned|align\*?|gathered|gather\*?)\}(.*?)\\end\{(?:aligned|align\*?|gathered|gather\*?)\}\s*', expr, re.S)
    if m:
        rows = split_array_rows(m.group(1))
        rows = [r.replace('&=', '=').replace('&', '') for r in rows]
        return 'eqalign{' + ' # '.join(latex_to_hwp(r) for r in rows) + '}'
    # cases
    m = re.fullmatch(r'\s*\\begin\{cases\}(.*?)\\end\{cases\}\s*', expr, re.S)
    if m:
        rows = split_array_rows(m.group(1))
        return 'cases{' + ' # '.join(latex_to_hwp(r.replace('&','~')) for r in rows) + '}'
    # matrix variants
    for env, hwp in [('matrix','matrix'),('pmatrix','pmatrix'),('bmatrix','bmatrix'),('vmatrix','dmatrix'),('Vmatrix','dmatrix')]:
        m = re.fullmatch(rf'\s*\\begin\{{{env}\}}(.*?)\\end\{{{env}\}}\s*', expr, re.S)
        if m:
            rows = split_array_rows(m.group(1))
            return hwp + '{' + ' # '.join(' & '.join(latex_to_hwp(c) for c in split_unbraced_ampersands(r)) for r in rows) + '}'
    return None




def normalize_frac_shorthand(src: str) -> str:
    """Normalize common GPT/LaTeX fraction shorthand without damaging braced input.

    Handles: \\frac83, \\frac ab, \\frac{A}2, \\frac8{B}, dfrac/tfrac variants.
    """
    # Common adjacent single-token form first: \\frac83 -> \\frac{8}{3}
    src = re.sub(r'\\(frac|dfrac|tfrac)\s*([A-Za-z0-9])([A-Za-z0-9])',
                 lambda m: '\\' + m.group(1) + '{' + m.group(2) + '}{' + m.group(3) + '}', src)

    def read_arg(text: str, i: int):
        n=len(text)
        while i<n and text[i].isspace(): i+=1
        if i>=n: return None,i
        if text[i]=='{':
            g,nxt=extract_group(text,i)
            if g is not None: return g,nxt
            return None,i
        if text[i]=='\\':
            j=i+1
            while j<n and text[j].isalpha(): j+=1
            if j>i+1: return text[i:j],j
            if j<n: return text[i:j+1],j+1
        # An unbraced TeX argument is one token. GPT often emits a single digit/letter.
        return text[i], i+1

    out=[]; i=0; cmds=(r'\frac',r'\dfrac',r'\tfrac')
    while i<len(src):
        hit=None
        for cmd in cmds:
            if src.startswith(cmd,i): hit=cmd; break
        if not hit:
            out.append(src[i]); i+=1; continue
        j=i+len(hit)
        a,j2=read_arg(src,j)
        b,j3=read_arg(src,j2)
        if a is None or b is None:
            out.append(hit); i=j; continue
        out.append(hit+'{'+a+'}{'+b+'}')
        i=j3
    return ''.join(out)


def normalize_geometry_text(text: str) -> str:
    """Pre-normalize geometry notation while leaving ordinary function symbols alone.

    Geometry labels are upright Roman in Korean textbooks.  Handle both bare
    labels (점 A) and labels already wrapped as inline math (점 $A$, 점 \(A\),
    점 `A`, 점 [[INLINE_EQ]]A[[/INLINE_EQ]]).
    """
    text=text.replace('⊥', r'\\perp').replace('∥', r'\\parallel')
    text=re.sub(r'∠\s*([A-Z]{1,6})', lambda m:r'\\angle '+m.group(1), text)
    text=re.sub(r'\^\s*\{\s*\\(?:circ|degree)\s*\}', r'^{circ}', text)
    text=re.sub(r'\^\s*\\(?:circ|degree)\b', r'^{circ}', text)

    nouns=r'(점|삼각형|사각형|오각형|육각형|선분|직선|반직선|평면|원)'

    # noun + $A$ / $AB$
    text=re.sub(nouns+r'\s+\$\s*([A-Z]{1,6})\s*\$',
                lambda m:m.group(1)+' $\\mathrm{'+m.group(2)+'}$', text)
    # noun + \(A\) / \(AB\)
    text=re.sub(nouns+r'\s+\\\(\s*([A-Z]{1,6})\s*\\\)',
                lambda m:m.group(1)+r' \(' + r'\mathrm{'+m.group(2)+'}' + r'\)', text)
    # noun + `A` / `AB`
    text=re.sub(nouns+r'\s+`\s*([A-Z]{1,6})\s*`',
                lambda m:m.group(1)+' `\\mathrm{'+m.group(2)+'}`', text)
    # noun + explicit tagged inline equation
    text=re.sub(nouns+r'\s+\[\[INLINE_EQ\]\]\s*([A-Z]{1,6})\s*\[\[/INLINE_EQ\]\]',
                lambda m:m.group(1)+' [[INLINE_EQ]]\\mathrm{'+m.group(2)+'}[[/INLINE_EQ]]', text)
    # noun + bare A / AB
    text=re.sub(nouns+r'\s+([A-Z]{1,6})(?![A-Za-z0-9])',
                lambda m:m.group(1)+' `\\mathrm{'+m.group(2)+'}`', text)
    return text

def romanize_math_labels(expr: str) -> str:
    """Romanize multi-letter uppercase geometry labels in original math source only."""
    # Avoid re-wrapping labels already inside \mathrm{...}.
    out=[]; pos=0
    for m in re.finditer(r'\b[A-Z]{2,6}\b', expr):
        prefix=expr[max(0,m.start()-8):m.start()]
        out.append(expr[pos:m.start()])
        if prefix.endswith(r'\mathrm{'):
            out.append(m.group(0))
        else:
            out.append(r'\mathrm{'+m.group(0)+'}')
        pos=m.end()
    out.append(expr[pos:])
    return ''.join(out)


def _latex_to_hwp_base(expr: str) -> str:
    """Convert ChatGPT/LaTeX math to Hancom equation script."""
    s = strip_outer_math_delimiters(expr)
    s = s.replace('\r',' ').replace('\n',' ')
    s = s.replace('&nbsp;', ' ')
    # Normalize equality/inequality as HWP relation tokens with even spacing.
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

    env = convert_environment(s)
    if env is not None:
        return re.sub(r'\s+', ' ', env).strip()

    # Protect VISIBLE set braces before stripping LaTeX sizing commands.
    # In Hancom equation script, raw { } are grouping braces and are not displayed.
    # Visible set braces must be emitted as: left lbrace ... right rbrace.
    s = re.sub(r'\\left\s*\\\{', ' ZZSETLZZ ', s)
    s = re.sub(r'\\right\s*\\\}', ' ZZSETRZZ ', s)
    s = s.replace(r'\{', ' ZZSETLZZ ').replace(r'\}', ' ZZSETRZZ ')

    # Protect escaped literal characters before generic command processing.
    placeholders = {
        r'\%': '__PERCENT__', r'\&': '__AMP__', r'\#': '__HASH__', r'\_': '__UNDERSCORE__',
        r'\$': '__DOLLAR__', r'\Q': '__LBRACE__', r'\q': '__RBRACE__',
    }
    for k,v in placeholders.items(): s=s.replace(k,v)

    # Spacing and size commands.
    s = s.replace(r'\left', '').replace(r'\right', '')
    s = s.replace(r'\ ', ' ~ ').replace(r'\,', ' ~ ').replace(r'\;', ' ~~ ').replace(r'\:', ' ~ ')
    s = s.replace(r'\!', '').replace(r'\quad', ' ~~ ').replace(r'\qquad', ' ~~~~ ')
    s = s.replace(r'\displaystyle', '').replace(r'\textstyle','')
    s = s.replace(r'\Bigl','').replace(r'\Bigr','').replace(r'\bigl','').replace(r'\bigr','').replace(r'\Big','').replace(r'\big','')

    # Arrays that occur nested in another command.
    for _ in range(4):
        m = re.search(r'\\begin\{array\}\{([^}]*)\}', s)
        if not m: break
        end = s.find(r'\end{array}', m.end())
        if end < 0: break
        block = s[m.start():end+len(r'\end{array}')]
        conv = convert_array(block)
        if conv is None: break
        s = s[:m.start()] + conv + s[end+len(r'\end{array}'):]

    # Normalize shorthand fractions before generic group handling.
    s = normalize_frac_shorthand(s)

    # Two-argument constructs.
    for _ in range(20):
        old = s
        s,_ = replace_command_groups(s, [r'\frac', r'\dfrac', r'\tfrac'], 2,
            lambda cmd,a: '{' + latex_to_hwp(a[0]) + '} over {' + latex_to_hwp(a[1]) + '}')
        if s == old: break

    # Binomial / combinations. Keep HWP native choose command.
    for _ in range(8):
        old=s
        s,_=replace_command_groups(s,[r'\binom',r'\dbinom'],2,
            lambda cmd,a: '{'+latex_to_hwp(a[0])+'} CHOOSE {'+latex_to_hwp(a[1])+'}')
        if s==old: break

    # Boxed answer: HWP's documented public command list does not expose a stable box command.
    # Use a visible square-bracket box-like fallback rather than leaving raw LaTeX.
    for _ in range(8):
        old=s
        s,_=replace_command_groups(s,[r'\boxed'],1,
            lambda cmd,a: latex_to_hwp(a[0]))
        if s==old: break

    # sqrt[n]{x} and sqrt{x}, balanced groups.
    pos=0; out=[]
    while pos < len(s):
        idx=s.find(r'\sqrt',pos)
        if idx<0: out.append(s[pos:]); break
        out.append(s[pos:idx]); j=idx+5
        while j<len(s) and s[j].isspace(): j+=1
        index=None
        if j<len(s) and s[j]=='[':
            depth=1; k=j+1
            while k<len(s) and depth:
                if s[k]=='[': depth+=1
                elif s[k]==']': depth-=1
                k+=1
            if depth==0:
                index=s[j+1:k-1]; j=k
                while j<len(s) and s[j].isspace(): j+=1
        g,nxt=extract_group(s,j)
        if g is None:
            out.append('sqrt '); pos=j; continue
        if index is None: out.append('sqrt {'+latex_to_hwp(g)+'}')
        else: out.append('root {'+latex_to_hwp(index)+'} of {'+latex_to_hwp(g)+'}')
        pos=nxt
    s=''.join(out)

    # One-argument decorations and text/style commands.
    one_arg = {
        r'\overline': lambda a: 'bar {'+latex_to_hwp(a)+'}',
        r'\bar': lambda a: 'bar {'+latex_to_hwp(a)+'}',
        r'\vec': lambda a: 'vec {'+latex_to_hwp(a)+'}',
        r'\hat': lambda a: 'hat {'+latex_to_hwp(a)+'}',
        r'\tilde': lambda a: 'tilde {'+latex_to_hwp(a)+'}',
        r'\underline': lambda a: 'under {'+latex_to_hwp(a)+'}',
        r'\mathrm': lambda a: text_in_equation(a),
        r'\operatorname': lambda a: text_in_equation(a),
        r'\text': lambda a: text_in_equation(a),
        r'\mathbf': lambda a: 'bold {'+latex_to_hwp(a)+'}',
        r'\mathit': lambda a: 'it {'+latex_to_hwp(a)+'}',
        # Blackboard-bold is not a stable Hancom command here; keep only its symbol.
        # Examples: \\mathbb{R} -> R, \\mathbb{Z} -> Z.
        r'\mathbb': lambda a: latex_to_hwp(a),
    }
    for cmd,fn in one_arg.items():
        for _ in range(10):
            old=s
            s,changed=replace_command_groups(s,[cmd],1,lambda c,a,fn=fn: fn(a[0]))
            if not changed or s==old: break

    # \begin{...} leftovers should never print literally.
    s = re.sub(r'\\(?:begin|end)\{[^}]+\}', '', s)
    s = s.replace(r'\hline','')

    # Core symbols. Order longest first.
    simple = {
        r'\Longleftrightarrow':'LRARROW', r'\Leftrightarrow':'LRARROW', r'\leftrightarrow':'LRARROW',
        r'\Longrightarrow':'RARROW', r'\Rightarrow':'RARROW', r'\rightarrow':'rarrow', r'\to':'rarrow',
        r'\Longleftarrow':'LARROW', r'\Leftarrow':'LARROW', r'\leftarrow':'larrow',
        r'\subseteq':'SUBSET=', r'\supseteq':'SUPSET=', r'\subset':'SUBSET', r'\supset':'SUPSET',
        r'\notin':'not IN', r'\in':'IN', r'\ni':'OWNS',
        r'\emptyset':'EMPTYSET', r'\varnothing':'EMPTYSET', r'\cup':'cup', r'\cap':'cap',
        r'\geq':'~GEQ~', r'\ge':'~GEQ~', r'\leq':'~LEQ~', r'\le':'~LEQ~', r'\neq':'~neq~', r'\ne':'~neq~', r'\approx':'APPROX',
        r'\pm':'+-', r'\mp':'-+', r'\times':'TIMES', r'\cdot':'cdot', r'\div':'divide',
        r'\infty':'INF', r'\sum':'sum', r'\prod':'prod', r'\int':'int', r'\oint':'oint', r'\lim':'lim',
        r'\sin':'sin', r'\cos':'cos', r'\tan':'tan', r'\log':'log', r'\ln':'ln',
        r'\angle':'angle', r'\perp':'bot', r'\parallel':'parallel', r'\therefore':'therefore', r'\because':'because',
        r'\alpha':'alpha', r'\beta':'beta', r'\gamma':'gamma', r'\delta':'delta', r'\epsilon':'epsilon',
        r'\varepsilon':'varepsilon', r'\theta':'theta', r'\lambda':'lambda', r'\mu':'mu', r'\rho':'rho',
        r'\sigma':'sigma', r'\omega':'omega', r'\pi':'pi', r'\phi':'phi', r'\varphi':'varphi',
        r'\Delta':'Delta', r'\Sigma':'Sigma', r'\Omega':'Omega',
        r'\ldots':'...', r'\cdots':'cdots', r'\vdots':'vdots', r'\ddots':'ddots',
        r'\circ':'circ', r'\degree':'circ', r'\colon':':',
    }
    for k in sorted(simple, key=len, reverse=True):
        s=s.replace(k,' '+simple[k]+' ')

    # LaTeX delimiters and scalable bars.
    s=s.replace(r'\lvert',' | ').replace(r'\rvert',' | ')
    s=s.replace(r'\lVert',' || ').replace(r'\rVert',' || ')
    s=s.replace(r'\(','(').replace(r'\)',')').replace(r'\[','[').replace(r'\]',']')

    # Superscripts/subscripts with balanced groups.
    def convert_scripts(s):
        out=[]; i=0
        while i<len(s):
            if s[i] in '^_':
                op=s[i]; j=i+1
                while j<len(s) and s[j].isspace(): j+=1
                if j<len(s) and s[j]=='{':
                    g,nxt=extract_group(s,j)
                    if g is not None:
                        out.append(op+'{'+latex_to_hwp(g)+'}'); i=nxt; continue
                if j<len(s):
                    # single token / command name already converted
                    k=j
                    if s[k] in '+-': k+=1
                    while k<len(s) and (s[k].isalnum() or s[k] in '.'): k+=1
                    if k>j:
                        out.append(op+'{'+s[j:k]+'}'); i=k; continue
            out.append(s[i]); i+=1
        return ''.join(out)
    s=convert_scripts(s)

    unicode_map = {
        '≤':'~LEQ~','≥':'~GEQ~','≠':'~neq~','→':'rarrow','⇒':'RARROW','⇔':'LRARROW','↔':'LRARROW',
        '∈':'IN','∉':'not IN','⊂':'SUBSET','⊆':'SUBSET=','⊃':'SUPSET','⊇':'SUPSET=',
        '∪':'cup','∩':'cap','∅':'EMPTYSET','∞':'INF','π':'pi','θ':'theta','α':'alpha','β':'beta','γ':'gamma',
        '√':'sqrt','×':'TIMES','÷':'divide','·':'cdot','±':'+-','∑':'sum','∫':'int','∥':'parallel','⊥':'bot',
    }
    for k,v in unicode_map.items(): s=s.replace(k,' '+v+' ')

    # Restore escaped literals.
    restore = {'__PERCENT__':'%', '__AMP__':'&', '__HASH__':'#', '__UNDERSCORE__':'_', '__DOLLAR__':'$', '__LBRACE__':'{', '__RBRACE__':'}'}
    for k,v in restore.items(): s=s.replace(k,v)
    s=s.replace('ZZSETLZZ', ' left lbrace ').replace('ZZSETRZZ', ' right rbrace ')

    # Normalize unbraced/malformed blackboard-bold forms before unknown-command cleanup.
    # \\mathbb R / \\mathbbR -> R (same for other single letters).
    s=re.sub(r'\\mathbb\s+([A-Za-z])\b', r'\1', s)
    s=re.sub(r'\\mathbb([A-Za-z])\b', r'\1', s)

    # If an upstream stage already emitted stray W brace markers, normalize them.
    s=s.replace('W{', ' left lbrace ').replace('W}', ' right rbrace ')
    # Unknown LaTeX commands: remove leading slash but do not expose raw source.
    s=re.sub(r'\\([A-Za-z]+)', r'\1', s)
    s=s.replace('\\\\',' # ')
    s=re.sub(r'(?!)','',s)
    s=re.sub(r'\s+',' ',s).strip()
    return s



def _antigravity_preprocess(expr: str) -> str:
    """Compatibility layer distilled from the supplied Antigravity HWP math fixes."""
    e=expr
    # prime notation
    e=re.sub(r"(?<=[A-Za-z0-9)\}])'''(?!')", ' prime prime prime ', e)
    e=re.sub(r"(?<=[A-Za-z0-9)\}])''(?!')", ' prime prime ', e)
    e=re.sub(r"(?<=[A-Za-z0-9)\}])'(?!')", ' prime ', e)
    e=re.sub(r'\\prime\s*\\prime\s*\\prime', ' prime prime prime ', e)
    e=re.sub(r'\\prime\s*\\prime', ' prime prime ', e)
    e=re.sub(r'\\prime', ' prime ', e)
    # Korean textbook combination notation.
    # Accept \binom, {}_n\mathrm{C}_r and {}_nC_r; make C 125% for readability.
    e=re.sub(
        r'(?:\\(?:d?binom)\{([^{}]+)\}\{([^{}]+)\}|\{\}_\{?\s*([^{}\s]+)\s*\}?\s*(?:\\mathrm\{C\}|C)\s*_\{?\s*([^{}\s]+)\s*\}?)',
        r'{}_{\1\3}{ scale 125 rm C }_{\2\4}',
        e,
    )
    # fractions inside script groups: 2^{1/2}, a_{n/2}
    def _script_frac(m):
        op=m.group(1); inner=m.group(2).strip()
        fm=re.fullmatch(r'([A-Za-z0-9]+)\s*/\s*([A-Za-z0-9]+)',inner)
        return op+'{\\frac{'+fm.group(1)+'}{'+fm.group(2)+'}}' if fm else m.group(0)
    e=re.sub(r'([_^])\{([^{}]+)\}', _script_frac, e)
    # unbraced roots from LLM output
    e=re.sub(r'\\sqrt\s*([A-Za-z0-9])', r'\\sqrt{\1}', e)
    # common operators which should not leak a backslash into HWP
    for cmd in ('max','min','gcd','det','deg','exp'):
        e=re.sub(r'\\'+cmd+r'\b', cmd, e)
    e=re.sub(r'\\(?:bmod|pmod)\b',' mod ',e)
    e=re.sub(r'\\mid\b',' | ',e)
    return e

def _antigravity_postprocess(s: str) -> str:
    # Critical HWP parser boundary: 10sqrt -> 10 sqrt, nsqrt -> n sqrt.
    s=re.sub(r'(?<=[0-9A-Za-z}\)])(?=(?:sqrt|root)\b)', ' ', s)
    # A radical/decorated object followed by a power must be the whole power base.
    s=re.sub(r'\bsqrt\s*\{([^{}]+)\}\s*\^\{([^{}]+)\}', r'{sqrt {\1}}^{\2}', s)
    s=re.sub(r'\b(bar|vec|hat|tilde)\s*\{([^{}]+)\}\s*\^\{([^{}]+)\}', r'{\1 {\2}}^{\3}', s)
    # normalize Korean C notation produced through rm/it style switching
    s=re.sub(r'\{\}_\{([^{}]+)\}\s*rm\s+C\s+it\s*_\{([^{}]+)\}', r'{}_{\1} C _{\2}', s)
    # operator spacing after scripts, matching Hancom parser expectations
    s=re.sub(r'(\^\{[^{}]+\}|_\{[^{}]+\})\s*([+\-=])\s*', r'\1 \2 ', s)
    s=re.sub(r'\s+',' ',s).strip()
    return s

def latex_to_hwp(expr: str) -> str:
    return _antigravity_postprocess(_latex_to_hwp_base(_antigravity_preprocess(expr)))

INLINE_TOKEN_RE = re.compile(
    r'(\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\\)\$(?!\$).*?(?<!\\)\$|`[^`\n]+`)',
    re.S,
)


def looks_like_math(code: str) -> bool:
    c=code.strip()
    if not c: return False
    if re.search(r'\\[A-Za-z]+|[=<>+\-*/^_]|[0-9]|[(),]|[A-Za-z](?:,[A-Za-z])+', c): return True
    if len(c)<=12 and re.fullmatch(r'[A-Za-z]+', c): return True
    return False



_SET_SUB_TRANS = str.maketrans('0123456789+-', '₀₁₂₃₄₅₆₇₈₉₊₋')
_SET_SUP_TRANS = str.maketrans('0123456789+-cn', '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ᶜⁿ')


def _to_subscript_text(x: str) -> str:
    return x.translate(_SET_SUB_TRANS)


def _to_superscript_text(x: str) -> str:
    return x.translate(_SET_SUP_TRANS)


def is_simple_set_literal_math(expr: str) -> bool:
    """Set literals are safer as normal HWP text than equation-script braces."""
    e=expr or ''
    has_braces = (r'\{' in e and r'\}' in e) or (r'\left\{' in e and r'\right\}' in e)
    # HWP equation input can expose escaped braces as stray W{ ... W}.
    has_w_braces = ('W{' in e and 'W}' in e) or ('\\W{' in e and 'W}' in e)
    if not (has_braces or has_w_braces):
        return False
    # Complex math should stay in the equation engine; this path is for literal sets only.
    return not re.search(r'\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|oint|binom|dbinom|overline|vec|begin|cases)\b', e)


def set_literal_to_text(expr: str) -> str:
    """Render simple set notation with literal Unicode braces so HWP cannot swallow the closing brace."""
    s=(expr or '').strip()
    # Delimiters and spacing commands first.
    s=re.sub(r'\\left\s*\\\{', '{', s)
    s=re.sub(r'\\right\s*\\\}', '}', s)
    s=s.replace(r'\{','{').replace(r'\}','}')
    # Remove only brace-adjacent stray W artifacts; keep a genuine variable W elsewhere.
    s=s.replace('\\W{','{').replace('W{','{').replace('W}','}')
    s=s.replace(r'\,',' ').replace(r'\;',' ').replace(r'\:',' ').replace(r'\!','')
    s=s.replace(r'\quad','  ').replace(r'\qquad','    ')
    # Blackboard-bold single-letter sets.
    s=re.sub(r'\\mathbb\s*\{\s*([A-Za-z])\s*\}', r'\1', s)
    s=re.sub(r'\\mathbb\s+([A-Za-z])\b', r'\1', s)
    s=re.sub(r'\\mathbb([A-Za-z])\b', r'\1', s)
    # Standard set operators/symbols.
    replacements={
        r'\cup':'∪', r'\cap':'∩', r'\in':'∈', r'\notin':'∉',
        r'\subseteq':'⊆', r'\subset':'⊂', r'\supseteq':'⊇', r'\supset':'⊃',
        r'\emptyset':'∅', r'\varnothing':'∅', r'\leq':'≤', r'\le':'≤',
        r'\geq':'≥', r'\ge':'≥', r'\neq':'≠', r'\ne':'≠', r'\mid':'|',
    }
    for a,b in sorted(replacements.items(), key=lambda kv: len(kv[0]), reverse=True):
        s=s.replace(a,b)
    # Common roman/text wrappers.
    s=re.sub(r'\\(?:mathrm|mathit|mathbf)\{([^{}]*)\}', r'\1', s)
    s=re.sub(r'\\text\{([^{}]*)\}', r'\1', s)
    # Subscripts/superscripts used in set names and complements.
    s=re.sub(r'_\{([0-9]+)\}', lambda m:_to_subscript_text(m.group(1)), s)
    s=re.sub(r'_([0-9]+)', lambda m:_to_subscript_text(m.group(1)), s)
    s=re.sub(r'\^\{([0-9]+|[cn])\}', lambda m:_to_superscript_text(m.group(1)), s)
    s=re.sub(r'\^([0-9]+|[cn])\b', lambda m:_to_superscript_text(m.group(1)), s)
    # Remove any remaining harmless sizing delimiters; never remove literal braces.
    s=s.replace(r'\left','').replace(r'\right','')
    s=s.replace(r'\(','(').replace(r'\)',')').replace(r'\[','[').replace(r'\]',']')
    # Unknown command fallback: keep its visible command name, without the slash.
    s=re.sub(r'\\([A-Za-z]+)', r'\1', s)
    s=re.sub(r'\s*,\s*', ', ', s)
    s=re.sub(r'\s*=\s*', ' = ', s)
    s=re.sub(r'\s+', ' ', s).strip()
    return s


def strip_inline_markdown_text(s: str) -> str:
    # Remove emphasis markers and markdown links while retaining visible text.
    s=re.sub(r'\*\*(.*?)\*\*', r'\1', s)
    s=re.sub(r'__(.*?)__', r'\1', s)
    s=re.sub(r'(?<!\*)\*(.*?)\*(?!\*)', r'\1', s)
    s=re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', s)
    return s


def split_inline(line: str):
    parts=[]; pos=0
    for m in INLINE_TOKEN_RE.finditer(line):
        if m.start()>pos:
            parts.append(('text', strip_inline_markdown_text(line[pos:m.start()])))
        raw=m.group(0)
        if raw.startswith('`'):
            code=raw[1:-1]
            if looks_like_math(code): parts.append(('math', code))
            else: parts.append(('text', code))
        else:
            parts.append(('math', strip_outer_math_delimiters(raw)))
        pos=m.end()
    if pos<len(line): parts.append(('text', strip_inline_markdown_text(line[pos:])))
    return parts or [('text','')]


def parse_blocks(text: str):
    """Return [('paragraph', inline_parts), ('display_math', raw), ('blank',None), ...]."""
    text=text.replace('\r\n','\n').replace('\r','\n')
    lines=text.split('\n')
    blocks=[]; i=0
    while i<len(lines):
        line=lines[i]
        stripped=line.strip()

        # ChatGPT/Windows clipboard often serializes display math as a
        # delimiter on its own line: $$ ... $$ or \[ ... \].
        # Treat the whole multi-line region as ONE equation object.
        if stripped in ('$$', r'\['):
            closer = '$$' if stripped == '$$' else r'\]'
            content=[]; i+=1
            while i<len(lines) and lines[i].strip()!=closer:
                content.append(lines[i]); i+=1
            if i<len(lines) and lines[i].strip()==closer:
                i+=1
            raw='\n'.join(content).strip()
            if raw:
                blocks.append(('display_math',raw))
            continue

        fm=re.match(r'^\s*```\s*([A-Za-z0-9_+-]*)\s*$', line)
        if fm:
            lang=fm.group(1).lower(); content=[]; i+=1
            while i<len(lines) and not re.match(r'^\s*```\s*$', lines[i]):
                content.append(lines[i]); i+=1
            if i<len(lines): i+=1
            raw='\n'.join(content).strip()
            if lang in ('math','latex','tex','') and raw:
                blocks.append(('display_math', raw))
            elif raw:
                for cl in content:
                    blocks.append(('paragraph', [('text',cl)]))
            continue
        if not line.strip():
            i+=1; continue
        # headings
        hm=re.match(r'^\s*#{1,6}\s+(.*)$', line)
        if hm:
            blocks.append(('heading', split_inline(hm.group(1).strip()))); i+=1; continue
        # bullets
        bm=re.match(r'^\s*[-*+]\s+(.*)$', line)
        if bm:
            parts=[('text','• ')] + split_inline(bm.group(1))
            blocks.append(('paragraph',parts)); i+=1; continue
        blocks.append(('paragraph',split_inline(line)))
        i+=1
    # trim leading/trailing blanks
    while blocks and blocks[0][0]=='blank': blocks.pop(0)
    while blocks and blocks[-1][0]=='blank': blocks.pop()
    return blocks


def add_text_run(p, text: str, char_pr='0'):
    if text == '': return
    run=ET.SubElement(p,qname(HP,'run'),{'charPrIDRef':char_pr})
    t=ET.SubElement(run,qname(HP,'t'))
    if text.startswith(' ') or text.endswith(' ') or '  ' in text:
        t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
    t.text=text


def add_equation_run(p, script: str, eq_id: int, z_order: int, base_unit='1100'):
    run=ET.SubElement(p,qname(HP,'run'),{'charPrIDRef':'0'})
    eq=ET.SubElement(run,qname(HP,'equation'),{
        'id':str(eq_id),'zOrder':str(z_order),'numberingType':'EQUATION','textWrap':'TOP_AND_BOTTOM',
        'textFlow':'BOTH_SIDES','lock':'0','dropcapstyle':'None','version':'Equation Version 60','baseLine':'0',
        'textColor':'#000000','baseUnit':base_unit,'lineMode':'CHAR','font':'HYhwpEQ'
    })
    ET.SubElement(eq,qname(HP,'sz'),{'width':'0','widthRelTo':'ABSOLUTE','height':'0','heightRelTo':'ABSOLUTE','protect':'0'})
    ET.SubElement(eq,qname(HP,'pos'),{
        'treatAsChar':'1','affectLSpacing':'0','flowWithText':'1','allowOverlap':'0','holdAnchorAndSO':'0',
        'vertRelTo':'PARA','horzRelTo':'PARA','vertAlign':'TOP','horzAlign':'LEFT','vertOffset':'0','horzOffset':'0'
    })
    ET.SubElement(eq,qname(HP,'outMargin'),{'left':'56','right':'56','top':'0','bottom':'0'})
    sc=ET.SubElement(eq,qname(HP,'shapeComment')); sc.text='수식입니다.'
    scr=ET.SubElement(eq,qname(HP,'script')); scr.text=script
    ET.SubElement(run,qname(HP,'t'))


def new_para(pid: int):
    return ET.Element(qname(HP,'p'),{
        'id':str(pid),'paraPrIDRef':'0','styleIDRef':'0','pageBreak':'0','columnBreak':'0','merged':'0'
    })


def clean_first_paragraph(first_p):
    for child in list(first_p):
        if child.tag==qname(HP,'run'):
            if child.find('.//hp:secPr',NS) is None and child.find('.//hp:colPr',NS) is None:
                first_p.remove(child)
        elif child.tag==qname(HP,'linesegarray'):
            first_p.remove(child)


def build_section(template_xml: bytes, text: str) -> bytes:
    root=ET.fromstring(template_xml)
    paras=root.findall('hp:p',NS)
    if not paras: raise ValueError('템플릿 section0.xml에 문단이 없습니다.')
    first=paras[0]; clean_first_paragraph(first)
    for p in paras[1:]: root.remove(p)

    blocks=parse_blocks(text)
    eq_id=1200000001; z=1; pid=2200000001
    used_first=False

    def get_para():
        nonlocal used_first,pid
        if not used_first:
            used_first=True; return first
        p=new_para(pid); pid+=1; root.append(p); return p

    for kind,data in blocks:
        p=get_para()
        if kind=='blank':
            add_text_run(p,' ')
            continue
        if kind=='display_math':
            script=latex_to_hwp(romanize_math_labels(data))
            add_equation_run(p,script,eq_id,z,'1150'); eq_id+=1; z+=1
            continue
        if kind in ('paragraph','heading'):
            if kind=='heading': add_text_run(p,'')
            for typ,val in data:
                if typ=='text': add_text_run(p,val)
                else:
                    script=latex_to_hwp(romanize_math_labels(val))
                    add_equation_run(p,script,eq_id,z); eq_id+=1; z+=1
    if not blocks:
        add_text_run(first,' ')
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def preview_text(text: str) -> str:
    # Human-readable preview with fenced markers removed, not raw Markdown fences.
    out=[]
    for kind,data in parse_blocks(text):
        if kind=='blank': out.append('')
        elif kind=='display_math':
            # Keep original math content but remove begin/end wrappers where feasible.
            arr=convert_array(data)
            out.append(data if arr is None else re.sub(r'\\begin\{array\}\{[^}]*\}|\\end\{array\}|\\hline','',data).replace('\\\\','\n').replace('&','\t'))
        else:
            line=''
            for typ,val in data:
                line += val if typ=='text' else val
            out.append(line)
    return '\n'.join(out)


def make_hwpx(text: str, output_path: Path, template_path: Path|None=None):
    template_path=template_path or resource_path('direct_hwpx_template.hwpx')
    if not template_path.exists(): raise FileNotFoundError(f'템플릿을 찾을 수 없습니다: {template_path}')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(template_path,'r') as zin:
        section=build_section(zin.read('Contents/section0.xml'),text)
        with zipfile.ZipFile(output_path,'w') as zout:
            for info in zin.infolist():
                data=zin.read(info.filename)
                if info.filename=='Contents/section0.xml': data=section
                elif info.filename=='Preview/PrvText.txt': data=preview_text(text).encode('utf-8')
                zi=zipfile.ZipInfo(info.filename,date_time=info.date_time)
                zi.external_attr=info.external_attr; zi.create_system=info.create_system
                zi.compress_type=zipfile.ZIP_STORED if info.filename=='mimetype' else zipfile.ZIP_DEFLATED
                zout.writestr(zi,data)


def default_name(): return 'gpt_v32_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.hwpx'