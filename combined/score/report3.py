# -*- coding: utf-8 -*-
import html
from parse import AREA_DESC

BRAND = "김현수학"
TEACHER = "김현T"
CARD_W = 420
SCALE = 3


def esc(x):
    return html.escape(str(x if x is not None else ""))


def _is_single(st):
    return len(st.get("rows", [])) == 1


def _rank_text(r, s):
    base = f"{r['등수']}/{s['반']['응시자수']}"
    tie_count = sum(1 for x in s.get("학생", {}).values() if x.get("점수") == r.get("점수"))
    if tie_count >= 2:
        return f"{base} (동석차 {tie_count}명)"
    return base


def make_comment(st):
    lines = []
    if _is_single(st):
        c = st.get("분류집계", {})
        if c.get("실수", 0):
            lines.append(f"정답률이 높은 문항에서의 실점이 {c.get('실수',0)}개 있어 계산·조건 확인 과정을 점검하겠습니다.")
        if c.get("개인취약", 0):
            lines.append(f"개인 취약 문항 {c.get('개인취약',0)}개는 오답노트와 유사문항으로 바로 보완하겠습니다.")
        if c.get("공통오답문제", 0):
            lines.append(f"공통 고난도 오답 {c.get('공통오답문제',0)}개는 풀이 구조와 핵심 개념을 다시 정리하겠습니다.")
        if not lines:
            lines.append("이번 회차의 전 문항 정답률을 기준으로 현재 강점과 보완 문항을 확인했습니다.")
        lines.append("틀린 문제는 개인별 오답노트와 연결해 다음 시험 전에 다시 확인하겠습니다.")
        return lines[:4]

    if st.get("취약"):
        names = ", ".join(w["유형"] for w in st["취약"][:2])
        lines.append(f"반복 취약 유형은 {names}입니다. 같은 유형을 다시 풀어 정확도를 높이겠습니다.")
    c = st.get("분류집계", {})
    if c.get("실수", 0):
        lines.append(f"정답률이 높은 문항에서의 실점이 {c.get('실수',0)}개 있어 계산·조건 확인 습관을 점검하겠습니다.")
    if c.get("개인취약", 0):
        lines.append(f"개인 취약 문항 {c.get('개인취약',0)}개는 유사문항 반복으로 보완하겠습니다.")
    if c.get("공통오답문제", 0):
        lines.append(f"공통 고난도 오답 {c.get('공통오답문제',0)}개는 풀이 구조를 다시 정리하겠습니다.")
    if not lines:
        lines.append("현재 성취 흐름을 유지하면서 오답 복습과 다음 회차 준비를 이어가겠습니다.")
    lines.append("다음 시험에서는 틀린 문제를 다시 맞힐 수 있도록 오답노트와 연계해 지도하겠습니다.")
    return lines[:4]


def _score_table(st):
    rows = []
    for r in st["rows"]:
        s = r["sess"]
        if r["결시"]:
            rows.append(f"<tr><td>{esc(s['hwp']['차시'])}</td><td class='mute'>{esc(r.get('사유') or '결시')}</td><td>-</td><td>-</td><td>-</td></tr>")
        else:
            rows.append(f"<tr><td>{esc(s['hwp']['차시'])}</td><td><b>{r['점수']:.0f}</b></td><td>{s['반']['평균']:.1f}</td><td>{esc(_rank_text(r,s))}</td><td>{', '.join(map(str,r['오답'])) or '-'}</td></tr>")
    return "".join(rows)


def _wrong_table(st):
    if not st["오답"]:
        return "<p class='none'>실점 문항이 없습니다.</p>"
    rows = []
    for w in st["오답"]:
        rows.append(f"<tr><td>{esc(w['차시'])}</td><td>{w['번호']}번</td><td>{esc(w['유형'])}</td><td>{esc(w['영역'])}</td><td>{w['반정답률']*100:.0f}%</td><td>{esc(w['분류'])}</td></tr>")
    return "<table class='detail'><thead><tr><th>회차</th><th>문항</th><th>유형</th><th>영역</th><th>반 정답률</th><th>분류</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _all_questions_single(st):
    if not st.get("rows"):
        return "<p class='none'>문항 데이터가 없습니다.</p>"
    r = st["rows"][0]
    if r.get("결시"):
        return "<p class='none'>해당 회차는 미응시입니다.</p>"
    s = r["sess"]
    wrong = set(r.get("오답", []))
    rows = []
    for q in s.get("문항번호", []):
        qi = s["문항"].get(q, {})
        is_wrong = q in wrong
        result = "오답" if is_wrong else "정답"
        cls = "bad" if is_wrong else "good"
        rate = s.get("정답률", {}).get(q, 0) * 100
        rows.append(
            f"<tr><td><b>{q}</b></td><td class='{cls}'>{result}</td>"
            f"<td>{rate:.0f}%</td><td class='left'>{esc(qi.get('유형',''))}</td><td>{esc(qi.get('영역',''))}</td></tr>"
        )
    if not rows:
        return "<p class='none'>문항 데이터가 없습니다.</p>"
    return (
        "<table class='detail allq'><thead><tr>"
        "<th>문항</th><th>본인</th><th>반 정답률</th><th>유형</th><th>영역</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _areas(st):
    if not st["영역"]:
        return "<p class='none'>영역별 데이터가 없습니다.</p>"
    out=[]
    for a in st["영역"]:
        gap=a["본인"]-a["반"]
        out.append(f"<div class='area'><div><b>{esc(a['영역'])}</b><span>본인 {a['본인']:.0f}% · 반 {a['반']:.0f}% · {gap:+.0f}%p</span></div><small>{esc(AREA_DESC.get(a['영역'],''))}</small><div class='track'><i style='width:{max(0,min(100,a['본인'])):.1f}%'></i><em style='left:{max(0,min(100,a['반'])):.1f}%'></em></div></div>")
    return "".join(out)


def _weak(st):
    if not st["취약"]:
        return "<p class='none'>2회 이상 반복된 취약 유형이 없습니다.</p>"
    return "<ul class='weak'>"+"".join(f"<li><b>{esc(w['유형'])}</b> <span>{w['횟수']}회</span><small>{esc(' · '.join(f'{ch} {q}번' for ch,q,_ in w['상세']))}</small></li>" for w in st["취약"])+"</ul>"


def _single_stats(st):
    r = st["rows"][0]
    if r.get("결시"):
        return "<div class='stats single'><div><span>응시</span><b>결시</b></div></div>"
    s = r["sess"]
    return (
        "<div class='stats single'>"
        f"<div><span>점수</span><b>{r['점수']:.0f}</b></div>"
        f"<div><span>반 평균</span><b>{s['반']['평균']:.1f}</b></div>"
        f"<div><span>석차</span><b class='rank'>{esc(_rank_text(r,s))}</b></div>"
        "</div>"
    )


def card(st, meta):
    comments="".join(f"<p>{esc(x)}</p>" for x in make_comment(st))
    header = f"""<header><div class='brand'>{BRAND}</div><h1>{esc(st['이름'])}</h1><div class='sub'>{esc(meta.get('학원',''))} · {esc(meta.get('반명',''))} · {esc(meta.get('강사',''))}</div><div class='sub'>{esc(meta.get('기간',''))} · {esc(meta.get('범위',''))}</div></header>"""

    if _is_single(st):
        return f"""<section class='card'>
{header}
{_single_stats(st)}
<h2>01 회차 성적</h2><table><thead><tr><th>회차</th><th>점수</th><th>반평균</th><th>석차</th><th>오답</th></tr></thead><tbody>{_score_table(st)}</tbody></table>
<h2>02 전체 문항 분석</h2><div class='hint'>모든 문항의 본인 정오와 반 전체 정답률입니다.</div>{_all_questions_single(st)}
<h2>03 평가영역별 정답률</h2>{_areas(st)}
<h2>04 지도 방향</h2><div class='comments'>{comments}</div>
<footer>이번 회차 전체 문항의 반 정답률과 본인 결과를 기준으로 산출되었습니다.</footer></section>"""

    trend=esc(st["추이"])
    return f"""<section class='card'>
{header}
<div class='stats'><div><span>평균</span><b>{st['평균']:.1f}</b></div><div><span>반 평균 대비</span><b>{st['편차평균']:+.1f}</b></div><div><span>평균 석차</span><b>상위 {st['평균상위%']:.0f}%</b></div><div><span>추이</span><b>{trend}</b></div><div><span>최고·최저</span><b>{st['최고']:.0f}·{st['최저']:.0f}</b></div><div><span>응시</span><b>{st['응시']}회</b></div></div>
<h2>01 회차별 성적</h2><table><thead><tr><th>회차</th><th>점수</th><th>반평균</th><th>석차</th><th>오답</th></tr></thead><tbody>{_score_table(st)}</tbody></table>
<h2>02 실점 문항</h2>{_wrong_table(st)}
<h2>03 평가영역별 정답률</h2>{_areas(st)}
<h2>04 반복 취약 유형</h2>{_weak(st)}
<h2>05 지도 방향</h2><div class='comments'>{comments}</div>
<footer>응시한 회차의 데이터만으로 산출되었습니다.</footer></section>"""


CSS="""
*{box-sizing:border-box}
body{margin:0;background:#f6fbff;color:#243447;font-family:'Malgun Gothic','Noto Sans KR',sans-serif;font-variant-numeric:tabular-nums}
.card{width:420px;margin:0 auto 20px;background:#ffffff;padding:18px 16px 16px;border-top:6px solid #69b7e6}
header{background:linear-gradient(135deg,#eef9ff,#f5fff9);border:1px solid #dceff8;border-radius:12px;padding:11px 12px 10px;margin:-4px 0 10px}
.brand{font-weight:800;font-size:17px;text-align:right;color:#2c8fc3}.card h1{font-size:34px;margin:3px 0 2px;color:#173a59}.sub{font-size:11px;color:#6f8294;margin:2px 0}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;background:transparent;margin:12px 0}.stats div{background:#f2f9ff;border:1px solid #d8edf9;border-radius:10px;padding:9px 6px;text-align:center}.stats div:nth-child(2){background:#f1fcf7;border-color:#d8f1e5}.stats div:nth-child(3){background:#fff8ef;border-color:#f5e4cb}.stats span{display:block;font-size:10px;color:#6f8294}.stats b{display:block;font-size:20px;margin-top:2px;color:#1d5f88}.stats div:nth-child(2) b{color:#27876a}.stats div:nth-child(3) b{color:#b77725}.stats.single .rank{font-size:13px;line-height:1.25;margin-top:5px}
h2{font-size:14px;color:#247dab;border-bottom:2px solid #d9eef8;padding:0 0 5px;margin:17px 0 7px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:11px;border:1px solid #e2edf3;border-radius:8px;overflow:hidden}th{background:#eaf7ff;color:#416a82;padding:6px 3px}td{border-bottom:1px solid #edf3f6;padding:5px 3px;text-align:center;background:#fff}tbody tr:nth-child(even) td{background:#fbfdff}tbody tr:last-child td{border-bottom:0}
.detail td:nth-child(3){text-align:left}.allq td:nth-child(3){text-align:center}.allq .left{text-align:left}.good{font-weight:800;color:#208568;background:#ecfbf4!important}.bad{font-weight:800;color:#d95f57;background:#fff0ef!important}.hint{font-size:9px;color:#8092a2;margin:-2px 0 6px}.mute,.none{color:#8fa0ad}.none{font-size:12px;background:#f4faff;border:1px solid #e0eff7;border-radius:8px;padding:8px;text-align:center}
.area{margin:10px 0;background:#fbfeff;border:1px solid #e4f0f5;border-radius:8px;padding:7px 8px}.area>div:first-child{display:flex;justify-content:space-between;font-size:12px}.area b{color:#286f96}.area span{font-size:10px;color:#6f8294}.area small{display:block;color:#8ca0ad;font-size:9px;margin:2px 0 4px}.track{height:10px;background:#e8f4f8;position:relative;border-radius:8px;overflow:visible}.track i{display:block;height:100%;background:linear-gradient(90deg,#71c7f0,#63d0aa);border-radius:8px}.track em{position:absolute;top:-2px;height:14px;width:2px;background:#ff9a76}
.weak{list-style:none;padding:0}.weak li{border-left:4px solid #ff9a76;background:#fff8f3;padding:5px 8px;margin:5px 0;font-size:12px;border-radius:0 8px 8px 0}.weak span{color:#dc6b45;font-weight:700}.weak small{display:block;color:#8b9aa6;margin-top:2px}.comments{background:#f7fcff;border:1px solid #dfedf5;border-radius:9px;padding:6px 8px}.comments p{font-size:12px;line-height:1.55;margin:5px 0;padding-left:12px;position:relative}.comments p:before{content:'•';position:absolute;left:0;color:#69b7e6}footer{border-top:1px solid #dfeaf0;margin-top:15px;padding-top:8px;font-size:9px;text-align:center;color:#91a0ac}
"""


def build_html(students, meta):
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>"+CSS+"</style></head><body>"+"\n".join(card(s,meta) for s in students)+"</body></html>"
