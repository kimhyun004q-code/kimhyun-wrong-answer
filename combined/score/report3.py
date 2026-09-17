# -*- coding: utf-8 -*-
import html
from parse import AREA_DESC

BRAND = "김현수학"
TEACHER = "김현T"
CARD_W = 420
SCALE = 3


def esc(x):
    return html.escape(str(x if x is not None else ""))


def make_comment(st):
    lines = []
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
            rows.append(f"<tr><td>{esc(s['hwp']['차시'])}</td><td><b>{r['점수']:.0f}</b></td><td>{s['반']['평균']:.1f}</td><td>{r['등수']}/{s['반']['응시자수']}</td><td>{', '.join(map(str,r['오답'])) or '-'}</td></tr>")
    return "".join(rows)


def _wrong_table(st):
    if not st["오답"]:
        return "<p class='none'>실점 문항이 없습니다.</p>"
    rows = []
    for w in st["오답"]:
        rows.append(f"<tr><td>{esc(w['차시'])}</td><td>{w['번호']}번</td><td>{esc(w['유형'])}</td><td>{esc(w['영역'])}</td><td>{w['반정답률']*100:.0f}%</td><td>{esc(w['분류'])}</td></tr>")
    return "<table class='detail'><thead><tr><th>회차</th><th>문항</th><th>유형</th><th>영역</th><th>반 정답률</th><th>분류</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


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


def card(st, meta):
    trend=esc(st["추이"])
    comments="".join(f"<p>{esc(x)}</p>" for x in make_comment(st))
    return f"""<section class='card'>
<header><div class='brand'>{BRAND}</div><h1>{esc(st['이름'])}</h1><div class='sub'>{esc(meta.get('학원',''))} · {esc(meta.get('반명',''))} · {esc(meta.get('강사',''))}</div><div class='sub'>{esc(meta.get('기간',''))} · {esc(meta.get('범위',''))}</div></header>
<div class='stats'><div><span>평균</span><b>{st['평균']:.1f}</b></div><div><span>반 평균 대비</span><b>{st['편차평균']:+.1f}</b></div><div><span>평균 석차</span><b>상위 {st['평균상위%']:.0f}%</b></div><div><span>추이</span><b>{trend}</b></div><div><span>최고·최저</span><b>{st['최고']:.0f}·{st['최저']:.0f}</b></div><div><span>응시</span><b>{st['응시']}회</b></div></div>
<h2>01 회차별 성적</h2><table><thead><tr><th>회차</th><th>점수</th><th>반평균</th><th>석차</th><th>오답</th></tr></thead><tbody>{_score_table(st)}</tbody></table>
<h2>02 실점 문항</h2>{_wrong_table(st)}
<h2>03 평가영역별 정답률</h2>{_areas(st)}
<h2>04 반복 취약 유형</h2>{_weak(st)}
<h2>05 지도 방향</h2><div class='comments'>{comments}</div>
<footer>응시한 회차의 데이터만으로 산출되었습니다.</footer></section>"""


CSS="""
*{box-sizing:border-box} body{margin:0;background:#edf1f5;color:#10203a;font-family:'Malgun Gothic','Noto Sans KR',sans-serif;font-variant-numeric:tabular-nums}.card{width:420px;margin:0 auto 20px;background:#fff;padding:18px 16px 16px}.brand{font-weight:800;font-size:17px;text-align:right}.card h1{font-size:34px;margin:4px 0 2px}.sub{font-size:11px;color:#7d8796;margin:2px 0}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:#dfe4ea;margin:12px 0}.stats div{background:white;padding:8px 4px}.stats span{display:block;font-size:10px;color:#7d8796}.stats b{display:block;font-size:20px;margin-top:2px}h2{font-size:14px;border-bottom:1px solid #dfe4ea;padding:0 0 5px;margin:17px 0 7px}table{width:100%;border-collapse:collapse;font-size:11px}th{background:#f3f6f9;color:#5c6779;padding:5px 3px}td{border-bottom:1px solid #edf0f3;padding:5px 3px;text-align:center}.detail td:nth-child(3){text-align:left}.mute,.none{color:#98a2b0}.none{font-size:12px;background:#f3f6f9;padding:8px;text-align:center}.area{margin:9px 0}.area>div:first-child{display:flex;justify-content:space-between;font-size:12px}.area span{font-size:10px;color:#7d8796}.area small{display:block;color:#98a2b0;font-size:9px;margin:2px 0 3px}.track{height:10px;background:#f0f3f6;position:relative}.track i{display:block;height:100%;background:#10203a}.track em{position:absolute;top:-2px;height:14px;width:2px;background:#c0392b}.weak{list-style:none;padding:0}.weak li{border-left:3px solid #c0392b;padding:4px 7px;margin:5px 0;font-size:12px}.weak span{color:#c0392b;font-weight:700}.weak small{display:block;color:#98a2b0;margin-top:2px}.comments p{font-size:12px;line-height:1.55;margin:5px 0;padding-left:10px;position:relative}.comments p:before{content:'•';position:absolute;left:0;color:#98a2b0}footer{border-top:1px solid #dfe4ea;margin-top:15px;padding-top:8px;font-size:9px;text-align:center;color:#98a2b0}
"""


def build_html(students, meta):
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>"+CSS+"</style></head><body>"+"\n".join(card(s,meta) for s in students)+"</body></html>"
