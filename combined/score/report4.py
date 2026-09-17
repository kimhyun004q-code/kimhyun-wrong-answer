# -*- coding: utf-8 -*-
"""성적표 화면: 회차표 안에 숙제평가를 표시하고 공지 영역을 하단에 배치한다."""
import importlib.util
import os
import sys

# run3.py가 먼저 불러온 확장 파서를 기존 report3.py의 `import parse`에도 연결한다.
if "parse" not in sys.modules and "parse4" in sys.modules:
    sys.modules["parse"] = sys.modules["parse4"]

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE_PATH = os.path.join(_HERE, "report3.py")
_spec = importlib.util.spec_from_file_location("_report3_base", _BASE_PATH)
_base = importlib.util.module_from_spec(_spec)
sys.modules["_report3_base"] = _base
_spec.loader.exec_module(_base)

BRAND = _base.BRAND
TEACHER = _base.TEACHER
CARD_W = _base.CARD_W
SCALE = _base.SCALE
esc = _base.esc

_HW_CODE = {
    "◎": 4, "○": 3, "△": 2,
    "4": 4, "4.0": 4, "3": 3, "3.0": 3, "2": 2, "2.0": 2, "1": 1, "1.0": 1,
    "매우잘함": 4, "잘함": 3, "부족": 2, "부족함": 2,
    "미제출": 1, "안함": 1,
}
_HW_TEXT = {4: "매우잘함", 3: "잘함", 2: "부족함", 1: "미제출"}
_HW_CLASS = {4: "hw4", 3: "hw3", 2: "hw2", 1: "hw1"}


def _homework_grade(v):
    if v is None:
        return "-", "hw0"
    if isinstance(v, (int, float)):
        n = int(round(float(v)))
    else:
        s = str(v).strip()
        n = _HW_CODE.get(s)
        if n is None:
            try:
                n = int(round(float(s)))
            except Exception:
                return (s or "-"), "hw0"
    return _HW_TEXT.get(n, str(v)), _HW_CLASS.get(n, "hw0")


def _rank_text(r, s):
    total = s["반"]["응시자수"]
    tie = sum(1 for x in s.get("학생", {}).values() if x.get("점수") == r.get("점수"))
    return f"{r['등수']}/{total} (동석차 {tie}명)"


def _single_stats(st):
    r = st["rows"][0]
    if r.get("결시"):
        return "<div class='stats single'><div><span>응시</span><b>결시</b></div></div>"
    s = r["sess"]
    diff = r["점수"] - s["반"]["평균"]
    return (
        "<div class='stats single'>"
        f"<div><span>점수</span><b>{r['점수']:.0f}</b></div>"
        f"<div><span>평균 대비</span><b>{diff:+.1f}점</b></div>"
        f"<div><span>석차</span><b class='rank'>{esc(_rank_text(r, s))}</b></div>"
        "</div>"
    )


def _score_table(st):
    rows = []
    for r in st["rows"]:
        s = r["sess"]
        if r.get("결시"):
            rows.append(
                f"<tr><td>{esc(s['hwp']['차시'])}</td><td class='mute'>{esc(r.get('사유') or '결시')}</td>"
                "<td>-</td><td>-</td><td>-</td></tr>"
            )
            continue
        hw_text, hw_cls = _homework_grade(r.get("숙제"))
        rows.append(
            f"<tr><td>{esc(s['hwp']['차시'])}</td><td><b>{r['점수']:.0f}</b></td>"
            f"<td>{s['반']['평균']:.1f}</td><td><span class='hwbadge {hw_cls}'>{esc(hw_text)}</span></td>"
            f"<td>{', '.join(map(str, r['오답'])) or '-'}</td></tr>"
        )
    return "".join(rows)


def _areas(st):
    if not st.get("영역"):
        return "<p class='none'>영역별 데이터가 없습니다.</p>"
    out = []
    for a in st["영역"]:
        me = max(0, min(100, float(a["본인"])))
        avg = max(0, min(100, float(a["반"])))
        gap = me - avg
        me_pin = min(99.1, max(0.0, me))
        avg_pin = min(99.4, max(0.0, avg))
        out.append(
            f"<div class='area'>"
            f"<div class='area-head'><b>{esc(a['영역'])}</b>"
            f"<span><strong class='me-txt'>본인 {me:.0f}%</strong> · 반 {avg:.0f}% · <strong class='gap-txt'>{gap:+.0f}%p</strong></span></div>"
            f"<small>{esc(_base.AREA_DESC.get(a['영역'], ''))}</small>"
            f"<div class='track'><i style='width:{me:.1f}%'></i>"
            f"<em class='student-pin' style='left:{me_pin:.1f}%'></em>"
            f"<em class='avg-pin' style='left:{avg_pin:.1f}%'></em></div>"
            f"<div class='legend'><span class='legend-me'>● 본인 위치</span><span class='legend-avg'>│ 반 평균</span></div>"
            f"</div>"
        )
    return "".join(out)


def _rows_box(rows, empty_text, kind="notice"):
    if not rows:
        return f"<div class='info-empty'>{esc(empty_text)}</div>"
    parts = []
    multi = len(rows) > 1
    for label, text in rows:
        safe_text = esc(text).replace("\n", "<br>")
        label_html = f"<b>{esc(label)}</b><span class='sep'>·</span>" if (multi and label) else ""
        parts.append(f"<div class='info-row {kind}'>{label_html}<span>{safe_text}</span></div>")
    return "<div class='info-box'>" + "".join(parts) + "</div>"


def _global_notice(st):
    return _rows_box(st.get("전체공지내역", []), "전체공지가 없습니다.", "global")


def _personal_notice(st):
    return _rows_box(st.get("개인공지내역", []), "개인공지가 없습니다.", "personal")


def _header(st, meta):
    return f"""<header><div class='brand'>{BRAND}</div><h1>{esc(st['이름'])}</h1><div class='sub'>{esc(meta.get('학원',''))} · {esc(meta.get('반명',''))} · {esc(meta.get('강사',''))}</div><div class='sub'>{esc(meta.get('기간',''))} · {esc(meta.get('범위',''))}</div></header>"""


def card(st, meta):
    header = _header(st, meta)
    if _base._is_single(st):
        return f"""<section class='card'>
{header}
{_single_stats(st)}
<h2>01 회차 성적</h2><table><thead><tr><th>회차</th><th>점수</th><th>반평균</th><th>숙제</th><th>오답</th></tr></thead><tbody>{_score_table(st)}</tbody></table>
<h2>02 전체 문항 분석</h2><div class='hint'>모든 문항의 본인 정오와 반 전체 정답률입니다.</div>{_base._all_questions_single(st)}
<h2>03 평가영역별 정답률</h2>{_areas(st)}
<h2>04 전체공지</h2>{_global_notice(st)}
<h2>05 개인공지</h2>{_personal_notice(st)}
</section>"""

    trend = esc(st["추이"])
    return f"""<section class='card'>
{header}
<div class='stats'><div><span>평균</span><b>{st['평균']:.1f}</b></div><div><span>반 평균 대비</span><b>{st['편차평균']:+.1f}</b></div><div><span>평균 석차</span><b>상위 {st['평균상위%']:.0f}%</b></div><div><span>추이</span><b>{trend}</b></div><div><span>최고·최저</span><b>{st['최고']:.0f}·{st['최저']:.0f}</b></div><div><span>응시</span><b>{st['응시']}회</b></div></div>
<h2>01 회차별 성적</h2><table><thead><tr><th>회차</th><th>점수</th><th>반평균</th><th>숙제</th><th>오답</th></tr></thead><tbody>{_score_table(st)}</tbody></table>
<h2>02 실점 문항</h2>{_base._wrong_table(st)}
<h2>03 평가영역별 정답률</h2>{_areas(st)}
<h2>04 전체공지</h2>{_global_notice(st)}
<h2>05 개인공지</h2>{_personal_notice(st)}
</section>"""


CSS = _base.CSS + """
.stats.single .rank{font-size:11px!important;line-height:1.28!important;white-space:normal}
.hwbadge{display:inline-block;padding:2px 6px;border-radius:999px;font-size:10px;font-weight:800;white-space:nowrap}
.hw4{background:#dff5e8;color:#176b43;border:1px solid #a9dec0}.hw3{background:#e3f0ff;color:#205f9c;border:1px solid #b9d8f7}.hw2{background:#fff0d9;color:#a25b00;border:1px solid #f1c77e}.hw1{background:#ffe3e1;color:#b53d36;border:1px solid #f3aaa5}.hw0{background:#f1f4f6;color:#6d7b87;border:1px solid #dfe5e9}
.area{margin:10px 0;background:#fbfeff;border:1px solid #d7e8ef;border-radius:9px;padding:8px 9px}.area-head{display:flex;justify-content:space-between;gap:8px;font-size:12px}.area-head>b{color:#144f70;font-size:13px}.area-head span{color:#5f7180;font-size:10px}.me-txt{color:#0b4b67;font-weight:900}.gap-txt{color:#135f7f;font-weight:900}.area small{display:block;color:#7b8d99;font-size:9px;margin:3px 0 5px}.track{height:11px;background:#e8f0f4;position:relative;border-radius:8px;overflow:visible}.track i{display:block;height:100%;background:#16879b;border-radius:8px}.track .student-pin{position:absolute;top:-4px;height:19px;width:4px;background:#073c56;border-radius:2px;z-index:3}.track .avg-pin{position:absolute;top:-2px;height:15px;width:2px;background:#f09168;border-radius:1px;z-index:2}.legend{display:flex;justify-content:flex-end;gap:10px;margin-top:3px;font-size:8px}.legend-me{color:#073c56;font-weight:800}.legend-avg{color:#c96f4e}
.info-box{display:flex;flex-direction:column;gap:6px}.info-row{font-size:11px;line-height:1.55;padding:8px 10px;border-radius:9px;border:1px solid #e0edf4;background:#fbfeff;color:#34495e}.info-row b{color:#277da8;margin-right:4px}.info-row .sep{color:#9aa9b5;margin-right:5px}.info-row.global{background:#f2f8ff;border-color:#d9eafb}.info-row.personal{background:#fff8ef;border-color:#f4e2c8}.info-empty{font-size:11px;color:#91a0ac;background:#f8fbfd;border:1px solid #e5eef3;border-radius:9px;padding:8px 10px}
"""


def build_html(students, meta):
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>" + CSS + "</style></head><body>" + "\n".join(card(s, meta) for s in students) + "</body></html>"
