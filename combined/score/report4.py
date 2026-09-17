# -*- coding: utf-8 -*-
"""성적표 화면: 반복취약/지도방향 대신 숙제·전체공지·개인공지를 표시한다."""
import importlib.util
import os
import sys

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
make_comment = _base.make_comment
esc = _base.esc


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


def _homework(st):
    return _rows_box(st.get("숙제내역", []), "숙제 정보가 없습니다.", "homework")


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
{_base._single_stats(st)}
<h2>01 회차 성적</h2><table><thead><tr><th>회차</th><th>점수</th><th>반평균</th><th>석차</th><th>오답</th></tr></thead><tbody>{_base._score_table(st)}</tbody></table>
<h2>02 전체 문항 분석</h2><div class='hint'>모든 문항의 본인 정오와 반 전체 정답률입니다.</div>{_base._all_questions_single(st)}
<h2>03 평가영역별 정답률</h2>{_base._areas(st)}
<h2>04 숙제</h2>{_homework(st)}
<h2>05 전체공지</h2>{_global_notice(st)}
<h2>06 개인공지</h2>{_personal_notice(st)}
</section>"""

    trend = esc(st["추이"])
    return f"""<section class='card'>
{header}
<div class='stats'><div><span>평균</span><b>{st['평균']:.1f}</b></div><div><span>반 평균 대비</span><b>{st['편차평균']:+.1f}</b></div><div><span>평균 석차</span><b>상위 {st['평균상위%']:.0f}%</b></div><div><span>추이</span><b>{trend}</b></div><div><span>최고·최저</span><b>{st['최고']:.0f}·{st['최저']:.0f}</b></div><div><span>응시</span><b>{st['응시']}회</b></div></div>
<h2>01 회차별 성적</h2><table><thead><tr><th>회차</th><th>점수</th><th>반평균</th><th>석차</th><th>오답</th></tr></thead><tbody>{_base._score_table(st)}</tbody></table>
<h2>02 실점 문항</h2>{_base._wrong_table(st)}
<h2>03 평가영역별 정답률</h2>{_base._areas(st)}
<h2>04 숙제</h2>{_homework(st)}
<h2>05 전체공지</h2>{_global_notice(st)}
<h2>06 개인공지</h2>{_personal_notice(st)}
</section>"""


CSS = _base.CSS + """
.info-box{display:flex;flex-direction:column;gap:6px}
.info-row{font-size:11px;line-height:1.55;padding:8px 10px;border-radius:9px;border:1px solid #e0edf4;background:#fbfeff;color:#34495e}
.info-row b{color:#277da8;margin-right:4px}.info-row .sep{color:#9aa9b5;margin-right:5px}
.info-row.homework{background:#f2fbf6;border-color:#d8efdf}.info-row.homework span{font-weight:700;color:#28765a}
.info-row.global{background:#f2f8ff;border-color:#d9eafb}
.info-row.personal{background:#fff8ef;border-color:#f4e2c8}
.info-empty{font-size:11px;color:#91a0ac;background:#f8fbfd;border:1px solid #e5eef3;border-radius:9px;padding:8px 10px}
"""


def build_html(students, meta):
    return "<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>" + CSS + "</style></head><body>" + "\n".join(card(s, meta) for s in students) + "</body></html>"
