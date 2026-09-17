import os, sys, re, zipfile, shutil, math
import xml.etree.ElementTree as ET
from pathlib import Path

APP_TITLE = "김현수학 HWPX·성적표 자동입력기"
EVAL_AREAS = ["계산", "이해", "추론", "문제해결", "자료해석"]

HP_NS = "http://www.hancom.co.kr/hwpml/2011/paragraph"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace('', MAIN_NS)


def local(tag):
    return tag.split('}')[-1]


def clean_text(s):
    return re.sub(r"\s+", " ", s or "").strip()


def extract_hwpx_questions(hwpx_path):
    """HWPX의 미주(endNote) 위치를 문제 경계로 사용한다.
    각 문제는 미주가 달린 문단부터 다음 미주 문단 직전까지의 본문을 묶는다.
    """
    paragraphs = []
    anchor_indices = []
    with zipfile.ZipFile(hwpx_path, 'r') as z:
        sec_names = sorted([n for n in z.namelist() if n.startswith('Contents/section') and n.endswith('.xml')])
        if not sec_names:
            raise ValueError("HWPX에서 본문 section XML을 찾지 못했습니다.")
        for sec in sec_names:
            root = ET.fromstring(z.read(sec))
            for child in list(root):
                if local(child.tag) != 'p':
                    continue
                out = []
                def rec(e):
                    if local(e.tag) == 'endNote':
                        return
                    if local(e.tag) in ('t', 'script') and e.text:
                        out.append(e.text)
                    for c in list(e):
                        rec(c)
                rec(child)
                txt = clean_text(''.join(out))
                has_endnote = any(local(e.tag) == 'endNote' for e in child.iter())
                if has_endnote:
                    anchor_indices.append(len(paragraphs))
                paragraphs.append(txt)

    questions = []
    if anchor_indices:
        for qi, start in enumerate(anchor_indices):
            end = anchor_indices[qi+1] if qi+1 < len(anchor_indices) else len(paragraphs)
            text = clean_text(' '.join(x for x in paragraphs[start:end] if x))
            for marker in ("정답 및 해설", "정답과 해설", "해설 및 정답"):
                if marker in text:
                    text = text.split(marker, 1)[0].strip()
            questions.append(text)
    else:
        joined = '\n'.join(paragraphs)
        matches = list(re.finditer(r"(?m)^\s*(\d{1,2})\s*[.)]\s+", joined))
        for i, m in enumerate(matches):
            e = matches[i+1].start() if i+1 < len(matches) else len(joined)
            questions.append(clean_text(joined[m.end():e]))

    questions = [q for q in questions if q][:30]
    if not questions:
        raise ValueError("문항을 찾지 못했습니다. 미주가 연결된 HWPX 시험지를 사용해 주세요.")
    return questions


def detect_question_format(text):
    circled = sum(text.count(c) for c in "①②③④⑤")
    if circled >= 2:
        return "객관식"
    if any(k in text for k in ("서술하시오", "설명하시오", "증명하시오", "과정을 쓰", "풀이 과정을")):
        return "서술형"
    return "단답형"


def classify_topic(text):
    t = text.lower()
    rules = [
        ("수열·급수", ["수열", "a_n", "sum _", "급수", "등비", "수렴"]),
        ("함수·역함수", ["역함수", "함수 f", "함수 g", "합성함수"]),
        ("지수·로그함수", ["ln", "log", "e^", "자연로그", "지수함수", "로그함수"]),
        ("삼각함수", ["sin", "cos", "tan", "csc", "sec", "삼각함수", "deg"]),
        ("함수의 극한", ["lim", "극한값", "한없이", "->", "rarrow"]),
        ("미분", ["f'", "g'", "도함수", "미분", "극댓값", "극솟값", "접선"]),
        ("적분", ["int _", "정적분", "부정적분", "적분"]),
        ("도형·좌표", ["좌표평면", "삼각형", "원 ", "부채꼴", "선분", "호 ", "넓이", "부피", "각도", "반지름"]),
        ("방정식·부등식", ["방정식", "부등식", "실근", "근의 합", "근의 곱"]),
        ("확률", ["확률", "사건", "독립", "조건부"]),
        ("경우의 수", ["경우의 수", "순열", "조합", "배열"]),
        ("통계", ["평균", "분산", "표준편차", "정규분포", "표본"]),
        ("집합·명제", ["집합", "명제", "필요조건", "충분조건"]),
        ("다항식", ["다항식", "인수분해", "나머지정리"]),
    ]
    scored = []
    for label, kws in rules:
        score = sum(1 for kw in kws if kw.lower() in t)
        if score:
            scored.append((score, label))
    if not scored:
        return "복합유형"
    scored.sort(key=lambda x: (-x[0], x[1]))
    labels = [x[1] for x in scored[:2]]
    return "·".join(labels)


def classify_eval_area(text):
    if any(k in text for k in ("그래프", "표를", "표 ", "자료", "도표")):
        return "자료해석"
    if any(k in text for k in ("<보기>", "< 보 기 >", "옳은 것", "참이다", "항상", "존재", "증명", "필요조건", "충분조건")):
        return "추론"
    if (len(text) >= 260 or any(k in text for k in ("그림과 같이", "좌표평면", "그릇", "부피", "넓이", "반원", "부채꼴", "교점", "최댓값", "최솟값"))):
        return "문제해결"
    if any(k in text for k in ("정의", "성질", "역함수", "개념", "의미", "조건을 만족")):
        return "이해"
    return "계산"


def estimate_complexity(text, eval_area):
    length_part = min(len(text) / 450.0, 1.0)
    eval_bonus = {"계산":0.00,"이해":0.10,"추론":0.35,"문제해결":0.45,"자료해석":0.25}.get(eval_area,0.10)
    multi = 0.15 if sum(1 for k in ("lim", "int _", "ln", "sin", "cos", "좌표평면", "그림과 같이") if k in text.lower()) >= 2 else 0
    return min(1.0 + 0.55*length_part + eval_bonus + multi, 1.9)


def parse_score_from_text(text):
    m = re.search(r"\[\s*(\d+(?:\.\d+)?)\s*점\s*\]", text)
    if not m:
        m = re.search(r"(?:배점\s*)?(\d+(?:\.\d+)?)\s*점", text)
    return float(m.group(1)) if m else None


def assign_scores(questions, eval_areas):
    n = len(questions)
    parsed = [parse_score_from_text(q) for q in questions]
    if all(x is not None for x in parsed) and abs(sum(parsed)-100) < 1e-6:
        return parsed, "HWPX 기존 배점 사용"
    weights = [estimate_complexity(q, e) for q, e in zip(questions, eval_areas)]
    totalw = sum(weights)
    raw = [100*w/totalw for w in weights]
    scores = [round(x*2)/2 for x in raw]
    diff = round((100 - sum(scores))*2)/2
    if abs(diff) >= 0.5:
        order = sorted(range(n), key=lambda i: (raw[i]-scores[i]), reverse=(diff>0))
        step = 0.5 if diff > 0 else -0.5
        k = int(round(abs(diff)/0.5))
        for j in range(k):
            i = order[j % n]
            if scores[i] + step >= 0.5:
                scores[i] += step
    scores = [int(s) if abs(s-round(s))<1e-9 else round(s,1) for s in scores]
    return scores, "난이도·문항부담 기준 자동 배점"


def col_letter(n):
    s = ''
    while n:
        n, r = divmod(n-1, 26)
        s = chr(65+r) + s
    return s


def split_ref(ref):
    m = re.match(r"([A-Z]+)(\d+)$", ref)
    if not m: raise ValueError(ref)
    col = 0
    for ch in m.group(1):
        col = col*26 + ord(ch)-64
    return col, int(m.group(2))


class XlsxPatcher:
    def __init__(self, path):
        self.path = path
        self.files = {}
        with zipfile.ZipFile(path, 'r') as z:
            for info in z.infolist():
                self.files[info.filename] = z.read(info.filename)
        self.sheet_paths = self._sheet_map()
        self.trees = {}

    def _sheet_map(self):
        wb = ET.fromstring(self.files['xl/workbook.xml'])
        rels = ET.fromstring(self.files['xl/_rels/workbook.xml.rels'])
        relmap = {r.attrib['Id']: r.attrib['Target'] for r in rels}
        mapping = {}
        for sh in wb.findall(f'.//{{{MAIN_NS}}}sheet'):
            name = sh.attrib['name']
            rid = sh.attrib[f'{{{REL_NS}}}id']
            target = relmap[rid].replace('\\','/')
            if target.startswith('/'):
                target = target.lstrip('/')
            elif not target.startswith('xl/'):
                target = 'xl/' + target.lstrip('./')
            mapping[name] = target
        return mapping

    def tree(self, sheet_name):
        if sheet_name not in self.sheet_paths:
            raise ValueError(f"필수 시트가 없습니다: {sheet_name}")
        path = self.sheet_paths[sheet_name]
        if path not in self.trees:
            self.trees[path] = ET.fromstring(self.files[path])
        return self.trees[path]

    def _get_or_create_cell(self, sheet_name, ref):
        root = self.tree(sheet_name)
        ns = MAIN_NS
        sheetData = root.find(f'{{{ns}}}sheetData')
        col, rownum = split_ref(ref)
        row = None
        for r in sheetData.findall(f'{{{ns}}}row'):
            if int(r.attrib.get('r','0')) == rownum:
                row = r; break
        if row is None:
            row = ET.Element(f'{{{ns}}}row', {'r': str(rownum)})
            inserted = False
            for idx, r in enumerate(list(sheetData)):
                if local(r.tag)=='row' and int(r.attrib.get('r','0')) > rownum:
                    sheetData.insert(idx, row); inserted=True; break
            if not inserted: sheetData.append(row)
        cell = None
        for c in row.findall(f'{{{ns}}}c'):
            if c.attrib.get('r') == ref:
                cell = c; break
        if cell is None:
            cell = ET.Element(f'{{{ns}}}c', {'r': ref})
            inserted=False
            for idx, c in enumerate(list(row)):
                if local(c.tag)!='c': continue
                ccol,_=split_ref(c.attrib['r'])
                if ccol > col:
                    row.insert(idx,cell); inserted=True; break
            if not inserted: row.append(cell)
        return cell

    def set_cell(self, sheet, ref, value=None, formula=None):
        c = self._get_or_create_cell(sheet, ref)
        style = c.attrib.get('s')
        for child in list(c):
            c.remove(child)
        c.attrib.clear(); c.attrib['r']=ref
        if style is not None: c.attrib['s']=style
        if formula is not None:
            f = ET.SubElement(c, f'{{{MAIN_NS}}}f')
            f.text = formula[1:] if formula.startswith('=') else formula
            return
        if value is None or value == '':
            return
        if isinstance(value, str):
            c.attrib['t'] = 'inlineStr'
            isel = ET.SubElement(c, f'{{{MAIN_NS}}}is')
            t = ET.SubElement(isel, f'{{{MAIN_NS}}}t')
            if value.startswith(' ') or value.endswith(' '):
                t.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
            t.text = value
        else:
            v = ET.SubElement(c, f'{{{MAIN_NS}}}v')
            v.text = str(value)

    def force_recalc(self):
        wb = ET.fromstring(self.files['xl/workbook.xml'])
        cp = wb.find(f'{{{MAIN_NS}}}calcPr')
        if cp is None:
            cp = ET.SubElement(wb, f'{{{MAIN_NS}}}calcPr')
        cp.set('calcMode','auto'); cp.set('fullCalcOnLoad','1'); cp.set('forceFullCalc','1')
        self.files['xl/workbook.xml'] = ET.tostring(wb, encoding='utf-8', xml_declaration=True)

    def save(self, out_path):
        for path, root in self.trees.items():
            self.files[path] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        self.force_recalc()
        with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in self.files.items(): z.writestr(name, data)


def fill_workbook(xlsx_path, hwpx_path, reviewed_rows, output_path):
    n = len(reviewed_rows)
    if n > 30: raise ValueError("현재 기본틀은 최대 30문항까지 지원합니다.")
    xp = XlsxPatcher(xlsx_path)
    required = ["테스트", "테스트정보", "계산파트(절대 건들지 말것)"]
    for s in required:
        if s not in xp.sheet_paths: raise ValueError(f"엑셀에 '{s}' 시트가 없습니다.")

    for i in range(30):
        excel_col = col_letter(7+i)
        xp.set_cell("테스트", f"{excel_col}2", i+1 if i < n else None)

    if n != 30:
        scores = [r['score'] for r in reviewed_rows]
        for i in range(30):
            excel_col = col_letter(7+i)
            xp.set_cell("테스트", f"{excel_col}106", scores[i] if i < n else None)

    for r in range(3,103):
        xp.set_cell("테스트", f"B{r}", formula=f'=IF(D{r}="","",RANK.EQ(E{r},$E$3:$E$102))')
        xp.set_cell("테스트", f"E{r}", formula=f'=IF(D{r}="","",100-(\'계산파트(절대 건들지 말것)\'!AE{r}))')
        xp.set_cell("테스트", f"F{r}", formula=f'=IF(D{r}="","",SUM(G{r}:AJ{r}))')
    xp.set_cell("테스트", "B105", formula='=COUNTA($D$3:$D$102)')
    xp.set_cell("테스트", "E105", formula='=IFERROR(AVERAGE(E3:E102),0)')
    xp.set_cell("테스트", "E106", formula='=IFERROR(MAX(E3:E102),0)')
    xp.set_cell("테스트", "E107", formula='=IFERROR(MIN(E3:E102),0)')
    xp.set_cell("테스트", "B106", formula='=COUNTA($G$2:$AJ$2)')
    for i in range(30):
        col = col_letter(7+i)
        xp.set_cell("테스트", f"{col}107", formula=f'=IF({col}$2="","",SUM({col}$3:{col}$102))')
        xp.set_cell("테스트", f"{col}108", formula=f'=IF({col}$2="","",IFERROR({col}107/$B$105,0))')
        xp.set_cell("테스트", f"{col}109", formula=f'=IF({col}$2="","",1-{col}108)')

    for i in range(30):
        row = 3+i
        if i < n:
            info = reviewed_rows[i]
            xp.set_cell("테스트정보", f"B{row}", i+1)
            xp.set_cell("테스트정보", f"C{row}", info['topic'])
            xp.set_cell("테스트정보", f"D{row}", info['eval'])
            test_col = col_letter(7+i)
            xp.set_cell("테스트정보", f"E{row}", formula=f'=테스트!{test_col}$109')
        else:
            for col in 'BCDE': xp.set_cell("테스트정보", f"{col}{row}", None)

    for i in range(30):
        c = col_letter(1+i); tc = col_letter(7+i)
        xp.set_cell("계산파트(절대 건들지 말것)", f"{c}1", formula=f'=테스트!{tc}$2')
        xp.set_cell("계산파트(절대 건들지 말것)", f"{c}2", formula=f'=테스트!{tc}$106')
    for r in range(3,103):
        for i in range(30):
            c = col_letter(1+i); tc=col_letter(7+i)
            xp.set_cell("계산파트(절대 건들지 말것)", f"{c}{r}", formula=f'=IF({c}$1="",0,테스트!{tc}{r}*{c}$2)')
        xp.set_cell("계산파트(절대 건들지 말것)", f"AE{r}", formula=f'=SUM(A{r}:AD{r})')

    xp.save(output_path)
    return output_path


def analyze(hwpx_path):
    qs = extract_hwpx_questions(hwpx_path)
    rows=[]; evals=[]
    for i,q in enumerate(qs,1):
        ev=classify_eval_area(q); evals.append(ev)
        rows.append({'num':i,'text':q,'format':detect_question_format(q),'topic':classify_topic(q),'eval':ev,'score':None})
    if len(qs) != 30:
        scores, source = assign_scores(qs, evals)
        for r,s in zip(rows,scores): r['score']=s
    else:
        source = "30문항: 기존 배점 유지"
    return rows, source


def default_output_path(xlsx_path):
    p=Path(xlsx_path)
    return str(p.with_name(p.stem + "_자동완성.xlsx"))
