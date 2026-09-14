from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import re
import fitz

@dataclass
class Start:
    q: int
    page: int
    x0: float
    y0: float
    col: int
    lane: int
    text: str

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def _likely_question(text: str) -> bool:
    t = _norm(text)
    if len(t) < 8:
        return False
    banned = ("시험이 시작", "답안지", "계산은 문제지", "시간이 남", "연습은 실전", "숙제", "성명")
    if any(x in t for x in banned):
        return False
    if "정답 및 해설" in t:
        return False
    return ("?" in t) or bool(re.search(r"구하시오[.\s]*$", t))

def _block_items(page):
    d = page.get_text("dict")
    items = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        lines = []
        for ln in b.get("lines", []):
            text = "".join(sp.get("text", "") for sp in ln.get("spans", []))
            if text.strip():
                lines.append(text)
        text = _norm(" ".join(lines))
        if not text:
            continue
        x0, y0, x1, y1 = b["bbox"]
        items.append((x0, y0, x1, y1, text))
    return items

def detect_question_clips(pdf_path: str, expected_count: int) -> dict[int, list[tuple[int, tuple[float,float,float,float]]]]:
    doc = fitz.open(pdf_path)
    candidates = []
    solution_marker = None

    for pi, page in enumerate(doc):
        for x0, y0, x1, y1, text in _block_items(page):
            if "정답 및 해설" in text and solution_marker is None:
                solution_marker = (pi, x0, y0)
            if _likely_question(text):
                candidates.append((pi, x0, y0, x1, y1, text, page.rect.width))

    if solution_marker:
        candidates = [c for c in candidates if (c[0], c[2]) < (solution_marker[0], solution_marker[2])]

    left = sum(1 for c in candidates if c[1] < c[6] * 0.45)
    right = sum(1 for c in candidates if c[1] > c[6] * 0.50)
    two_col = left >= 2 and right >= 2

    starts = []
    for c in candidates:
        pi, x0, y0, x1, y1, text, pw = c
        col = 0 if not two_col or x0 < pw / 2 else 1
        lane = pi * (2 if two_col else 1) + col
        starts.append((lane, y0, pi, x0, y0, col, text))
    starts.sort(key=lambda z: (z[0], z[1]))

    if len(starts) != expected_count:
        if len(starts) > expected_count:
            starts = starts[:expected_count]
        else:
            doc.close()
            preview = "\n".join(f"- p{z[2]+1}: {_norm(z[6])[:80]}" for z in starts)
            raise RuntimeError(f"문항 시작을 {len(starts)}개만 인식했습니다. 엑셀상 문항 수는 {expected_count}개입니다.\n인식 내용:\n{preview}")

    objs = []
    for idx, z in enumerate(starts, start=1):
        lane, yy, pi, x0, y0, col, text = z
        objs.append(Start(idx, pi, x0, y0, col, lane, text))

    lane_count = 2 if two_col else 1
    def lane_rect(lane: int, y0: float, y1: float):
        pi = lane // lane_count
        col = lane % lane_count
        page = doc[pi]
        w, h = page.rect.width, page.rect.height
        if two_col:
            if col == 0:
                x0, x1 = 10, w / 2 - 5
            else:
                x0, x1 = w / 2 + 5, w - 10
        else:
            x0, x1 = 10, w - 10
        r = fitz.Rect(x0, max(8, y0), x1, min(h - 8, y1))
        return pi, (r.x0, r.y0, r.x1, r.y1)

    if solution_marker:
        spi, sx, sy = solution_marker
        scol = 0 if not two_col or sx < doc[spi].rect.width / 2 else 1
        end_lane = spi * lane_count + scol
        end_y = sy - 8
    else:
        end_lane = objs[-1].lane
        end_y = doc[objs[-1].page].rect.height - 10

    result = {}
    for i, s in enumerate(objs):
        if i + 1 < len(objs):
            n = objs[i + 1]
            final_lane, final_y = n.lane, n.y0 - 10
        else:
            final_lane, final_y = end_lane, end_y
        segs = []
        for lane in range(s.lane, final_lane + 1):
            page = doc[lane // lane_count]
            start_y = s.y0 - 18 if lane == s.lane else 10
            stop_y = final_y if lane == final_lane else page.rect.height - 10
            if stop_y > start_y + 8:
                segs.append(lane_rect(lane, start_y, stop_y))
        result[s.q] = segs
    doc.close()
    return result

def render_question_images(source_pdf: str, clips: dict, out_dir: str, dpi: int = 140,
                           only_questions: set[int] | None = None) -> dict[int, list[dict]]:
    """Render only needed question segments once as compact JPEGs for much faster HWP insertion/save."""
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    src = fitz.open(source_pdf)
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    result = {}
    needed = set(int(q) for q in only_questions) if only_questions else None

    for q, segs in clips.items():
        q = int(q)
        if needed is not None and q not in needed:
            continue
        items = []
        for idx, (page_no, rect_tuple) in enumerate(segs, 1):
            rect = fitz.Rect(*rect_tuple)
            page = src[page_no]
            pix = page.get_pixmap(matrix=matrix, clip=rect, alpha=False, colorspace=fitz.csRGB)
            path = out_root / f"q{q:03d}_{idx}.jpg"
            try:
                pix.save(str(path), jpg_quality=88)
            except TypeError:
                path.write_bytes(pix.tobytes("jpeg", jpg_quality=88))

            px_w, px_h = pix.width, pix.height
            width_mm = min(170.0, px_w / dpi * 25.4)
            height_mm = width_mm * (px_h / max(px_w, 1))
            items.append({"path": str(path), "width_mm": width_mm, "height_mm": height_mm})
        result[q] = items
    src.close()
    return result
