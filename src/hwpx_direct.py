from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
import os
import re
from lxml import etree

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
NS = {"hp": HP}
SECTION_PATH = "Contents/section0.xml"
HEADER_PATH = "Contents/header.xml"
A4_WIDTH = "59528"
A4_HEIGHT = "84188"
SKIP_HEADINGS = {"서답형", "5지선다형", "객관식", "주관식"}
MEANINGFUL_TAGS = {
    "tbl", "pic", "rect", "ellipse", "container", "equation", "ole",
    "video", "line", "arc", "curve", "polygon", "connectLine", "textart",
    "endNote",
}


def _text_of(elem) -> str:
    return " ".join("".join(elem.itertext()).split())


def _safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", text).strip().rstrip(".")
    return text or "결과"


def _is_empty_layout_para(paragraph) -> bool:
    if _text_of(paragraph):
        return False
    for node in paragraph.iter():
        if etree.QName(node).localname in MEANINGFUL_TAGS:
            return False
    return True


def _find_local(root, local_name: str):
    for node in root.iter():
        if etree.QName(node).localname == local_name:
            return node
    return None


def _find_id(parent, id_value: str):
    for node in list(parent):
        if node.get("id") == str(id_value):
            return node
    return None


def _next_id(parent) -> int:
    values = []
    for node in list(parent):
        try:
            values.append(int(node.get("id")))
        except Exception:
            pass
    return (max(values) + 1) if values else 0


def _build_cover_header(header_bytes: bytes) -> tuple[bytes, dict[str, str]]:
    """표지 전용 문단/글자 스타일을 HWPX header.xml에 추가한다."""
    root = etree.fromstring(header_bytes)
    chars = _find_local(root, "charProperties")
    paras = _find_local(root, "paraProperties")
    if chars is None or paras is None:
        raise ValueError("HWPX header.xml에서 글자/문단 속성을 찾지 못했습니다.")

    base_char = _find_id(chars, "19") or _find_id(chars, "8") or list(chars)[0]
    base_para = _find_id(paras, "14") or list(paras)[0]

    ids: dict[str, str] = {}
    next_char = _next_id(chars)
    char_specs = [
        ("spacer", 700),
        ("info", 3200),
        ("student", 4500),
        ("slogan", 3400),
    ]
    for key, height in char_specs:
        cp = deepcopy(base_char)
        cp.set("id", str(next_char))
        cp.set("height", str(height))
        cp.set("textColor", "#000000")
        cp.set("shadeColor", "none")
        chars.append(cp)
        ids[key] = str(next_char)
        next_char += 1
    chars.set("itemCnt", str(len(list(chars))))

    pp = deepcopy(base_para)
    para_id = _next_id(paras)
    pp.set("id", str(para_id))
    pp.set("snapToGrid", "0")
    align = None
    for child in pp:
        if etree.QName(child).localname == "align":
            align = child
            break
    if align is None:
        align = etree.SubElement(pp, f"{{{HP}}}align")
    align.set("horizontal", "CENTER")
    align.set("vertical", "BASELINE")
    paras.append(pp)
    paras.set("itemCnt", str(len(list(paras))))
    ids["para_center"] = str(para_id)

    return (
        etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True),
        ids,
    )


def _force_a4(section_para) -> None:
    """구역의 용지를 원본과 무관하게 A4 세로로 고정한다."""
    for page_pr in section_para.xpath(".//hp:pagePr", namespaces=NS):
        page_pr.set("landscape", "NARROWLY")
        page_pr.set("width", A4_WIDTH)
        page_pr.set("height", A4_HEIGHT)


def _section_template(root, col_count: int = 2, hide_first_background: bool = False):
    source = None
    for p in root:
        if p.xpath(".//hp:secPr", namespaces=NS):
            source = p
            break
    if source is None:
        raise ValueError("HWPX에서 문서 구역 설정(secPr)을 찾지 못했습니다.")

    p = deepcopy(source)
    for child in list(p):
        if etree.QName(child).localname != "run":
            p.remove(child)
            continue
        keep = []
        for item in list(child):
            local = etree.QName(item).localname
            if local == "ctrl":
                for ctrl_child in list(item):
                    if etree.QName(ctrl_child).localname != "colPr":
                        item.remove(ctrl_child)
                if len(item):
                    keep.append(item)
            elif local == "secPr":
                keep.append(item)
        for item in list(child):
            if item not in keep:
                child.remove(item)
        if not keep:
            p.remove(child)

    _force_a4(p)

    for col_pr in p.xpath(".//hp:colPr", namespaces=NS):
        col_pr.set("type", "NEWSPAPER")
        col_pr.set("layout", "LEFT")
        col_pr.set("colCount", str(max(1, int(col_count))))
        col_pr.set("sameSz", "1")
        if not col_pr.get("sameGap"):
            col_pr.set("sameGap", "1000")

    for placement in p.xpath(".//hp:endNotePr/hp:placement", namespaces=NS):
        placement.set("place", "END_OF_DOCUMENT")
        placement.set("beneathText", "0")

    for visibility in p.xpath(".//hp:secPr/hp:visibility", namespaces=NS):
        if hide_first_background:
            visibility.set("hideFirstMasterPage", "1")
            visibility.set("hideFirstFooter", "1")
            visibility.set("hideFirstHeader", "1")
            visibility.set("hideFirstPageNum", "1")
        else:
            visibility.set("hideFirstMasterPage", "0")
            visibility.set("hideFirstFooter", "0")
            visibility.set("hideFirstHeader", "0")
            visibility.set("hideFirstPageNum", "0")

    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")
    return p


def _style_ids(root) -> tuple[str, str]:
    for p in root:
        para_pr = p.get("paraPrIDRef")
        for run in p.findall(f"{{{HP}}}run"):
            if run.find(f"{{{HP}}}t") is not None and run.get("charPrIDRef"):
                text = _text_of(run)
                if text and len(text) < 80:
                    return para_pr or "0", run.get("charPrIDRef")
    return "0", "0"


def _label_para(
    para_pr: str,
    char_pr: str,
    text: str,
    page_break: bool = False,
    column_break: bool = False,
):
    p = etree.Element(f"{{{HP}}}p")
    p.set("id", "2147483648")
    p.set("paraPrIDRef", para_pr)
    p.set("styleIDRef", "0")
    p.set("pageBreak", "1" if page_break else "0")
    p.set("columnBreak", "1" if column_break else "0")
    p.set("merged", "0")
    run = etree.SubElement(p, f"{{{HP}}}run")
    run.set("charPrIDRef", char_pr)
    t = etree.SubElement(run, f"{{{HP}}}t")
    t.text = text
    return p


def _cover_para(text: str, styles: dict[str, str], kind: str):
    return _label_para(styles["para_center"], styles[kind], text)


def _append_cover(
    root,
    cover_template,
    problem_template,
    styles: dict[str, str],
    student: str,
    class_name: str,
    round_name: str,
    test_date: str,
) -> None:
    root.append(deepcopy(cover_template))

    for _ in range(3):
        root.append(_cover_para("", styles, "spacer"))

    class_text = (class_name or "").strip() or "-"
    round_text = (round_name or "").strip() or "-"
    exam_date = (test_date or "").strip() or "-"

    root.append(_cover_para(f"반명  {class_text}", styles, "info"))
    root.append(_cover_para(f"회차  {round_text}", styles, "info"))
    root.append(_cover_para(f"시험응시일  {exam_date}", styles, "info"))

    for _ in range(2):
        root.append(_cover_para("", styles, "spacer"))

    root.append(_cover_para(f"{student}(오답노트)", styles, "student"))

    for _ in range(2):
        root.append(_cover_para("", styles, "spacer"))

    root.append(_cover_para("성적이 오르는 신뢰의 이름 김현수학", styles, "slogan"))

    problem_start = deepcopy(problem_template)
    problem_start.set("pageBreak", "1")
    problem_start.set("columnBreak", "0")
    root.append(problem_start)


def _append_endnote_page_separator(root, para_pr: str, char_pr: str) -> None:
    separator = _label_para(
        para_pr,
        char_pr,
        "",
        page_break=True,
        column_break=False,
    )
    separator.set("id", "2147483647")
    root.append(separator)

    for note in root.xpath(".//hp:endNote", namespaces=NS):
        paras = note.xpath("./hp:subList/hp:p", namespaces=NS)
        if paras:
            paras[0].set("pageBreak", "0")
            paras[0].set("columnBreak", "0")


class HwpxExam:
    """HWPX 시험지를 한 번 읽고, 한컴 실행 없이 학생별 HWPX를 만든다."""

    def __init__(self, source_path: str, expected_question_count: int | None = None):
        self.source_path = str(Path(source_path).resolve())
        if Path(self.source_path).suffix.lower() != ".hwpx":
            raise ValueError("이 고속 버전은 HWPX 시험지만 지원합니다. HWP 파일은 한글에서 HWPX로 저장해 주세요.")

        with ZipFile(self.source_path, "r") as z:
            names = z.namelist()
            if SECTION_PATH not in names:
                raise ValueError("HWPX에서 Contents/section0.xml을 찾지 못했습니다.")
            if HEADER_PATH not in names:
                raise ValueError("HWPX에서 Contents/header.xml을 찾지 못했습니다.")
            self.entries = [(info, z.read(info.filename)) for info in z.infolist()]
            self.root = etree.fromstring(z.read(SECTION_PATH))
            self.output_header, self.cover_styles = _build_cover_header(z.read(HEADER_PATH))

        self.para_pr, self.char_pr = _style_ids(self.root)
        self.cover_template = _section_template(self.root, 1, hide_first_background=True)
        self.problem_template = _section_template(self.root, 2, hide_first_background=False)
        self.answer_index = len(self.root)
        anchors: list[int] = []

        for i, paragraph in enumerate(self.root):
            txt = _text_of(paragraph)
            if "정답 및 해설" in txt:
                self.answer_index = i
                break
            if paragraph.xpath(".//hp:endNote", namespaces=NS):
                anchors.append(i)

        if not anchors:
            raise ValueError("시험지에서 문항 시작점을 찾지 못했습니다.")

        requested = int(expected_question_count or 0)
        if requested > 0:
            if len(anchors) < requested:
                raise ValueError(
                    f"시험지에서 문항을 {len(anchors)}개만 찾았습니다. "
                    f"엑셀의 문항 수는 {requested}개입니다."
                )
            if len(anchors) > requested:
                anchors = anchors[:requested]
            self.question_count = requested
        else:
            self.question_count = len(anchors)

        self.anchors = anchors
        self.blocks: dict[int, list] = {}

        for q, start in enumerate(anchors, start=1):
            end = anchors[q] if q < len(anchors) else self.answer_index
            items = []
            for paragraph in self.root[start:end]:
                txt = _text_of(paragraph).strip()
                if txt in SKIP_HEADINGS:
                    continue

                cp = deepcopy(paragraph)
                cp.set("pageBreak", "0")
                cp.set("columnBreak", "0")
                if not _is_empty_layout_para(cp):
                    items.append(cp)
            if not items:
                raise ValueError(f"{q}번 문항 내용을 추출하지 못했습니다.")
            self.blocks[q] = items

    def _build_section(
        self,
        student: str,
        test_date: str,
        wrongs: list[int],
        class_name: str = "",
        round_name: str = "",
    ) -> bytes:
        new_root = deepcopy(self.root)
        for child in list(new_root):
            new_root.remove(child)

        _append_cover(
            new_root,
            self.cover_template,
            self.problem_template,
            self.cover_styles,
            student,
            class_name,
            round_name,
            test_date,
        )

        for idx, q in enumerate(wrongs):
            if q not in self.blocks:
                raise ValueError(f"시험지에서 {q}번 문항을 찾지 못했습니다.")

            page_break = idx > 0 and idx % 2 == 0
            column_break = idx % 2 == 1
            label = f"[오답 {q}번]  {student}  {test_date}"
            new_root.append(
                _label_para(
                    self.para_pr,
                    self.char_pr,
                    label,
                    page_break=page_break,
                    column_break=column_break,
                )
            )
            for p in self.blocks[q]:
                new_root.append(deepcopy(p))

        _append_endnote_page_separator(new_root, self.para_pr, self.char_pr)

        return etree.tostring(
            new_root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )

    def generate(
        self,
        output_path: str,
        student: str,
        test_date: str,
        wrongs: list[int],
        class_name: str = "",
        round_name: str = "",
    ) -> str:
        wrongs = sorted({int(q) for q in wrongs if 1 <= int(q) <= self.question_count})
        if not wrongs:
            raise ValueError(f"{student}: 오답 문항이 없습니다.")

        section_data = self._build_section(
            student,
            test_date,
            wrongs,
            class_name=class_name,
            round_name=round_name,
        )
        preview = (
            f"{student}(오답노트)\n"
            f"반명 {class_name}\n"
            f"회차 {round_name}\n"
            f"시험응시일 {test_date}\n"
            f"오답문항: {', '.join(map(str, wrongs))}\n"
        ).encode("utf-8")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_suffix(out.suffix + ".tmp")
        if temp.exists():
            temp.unlink()

        with ZipFile(temp, "w") as zout:
            for info, original in self.entries:
                if info.filename == SECTION_PATH:
                    data = section_data
                elif info.filename == HEADER_PATH:
                    data = self.output_header
                elif info.filename == "Preview/PrvText.txt":
                    data = preview
                else:
                    data = original
                zout.writestr(info, data)

        with ZipFile(temp, "r") as check:
            if check.read("mimetype") != b"application/hwp+zip":
                raise ValueError("생성된 HWPX의 mimetype 검증에 실패했습니다.")
            check_root = etree.fromstring(check.read(SECTION_PATH))
            endnotes = check_root.xpath(".//hp:endNote", namespaces=NS)
            if len(endnotes) != len(wrongs):
                raise ValueError(
                    f"생성 결과의 미주 수({len(endnotes)})가 오답 문항 수({len(wrongs)})와 일치하지 않습니다."
                )
            section_count = len(check_root.xpath(".//hp:secPr", namespaces=NS))
            if section_count < 2:
                raise ValueError("표지와 문제를 분리하는 구역 설정 검증에 실패했습니다.")

            page_nodes = check_root.xpath(".//hp:secPr/hp:pagePr", namespaces=NS)
            if not page_nodes or any(
                n.get("width") != A4_WIDTH or n.get("height") != A4_HEIGHT
                for n in page_nodes
            ):
                raise ValueError("오답노트 A4 용지 설정 검증에 실패했습니다.")

            visibility_nodes = check_root.xpath(".//hp:secPr/hp:visibility", namespaces=NS)
            if not visibility_nodes or visibility_nodes[0].get("hideFirstMasterPage") != "1":
                raise ValueError("표지 첫 페이지 바탕쪽 감추기 설정 검증에 실패했습니다.")

            top_paras = [x for x in list(check_root) if etree.QName(x).localname == "p"]
            if not top_paras or top_paras[-1].get("pageBreak") != "1":
                raise ValueError("문제와 미주 사이 실제 쪽 나누기 검증에 실패했습니다.")

        os.replace(temp, out)
        return str(out)


def generate_student_files(
    exam_path: str,
    result_dir: str,
    students: list[dict],
    question_count: int,
    test_date: str,
    class_name: str = "",
    round_name: str = "",
    progress=None,
) -> list[str]:
    exam = HwpxExam(exam_path, question_count)
    targets = [s for s in students if s.get("wrongs")]
    results = []
    total = len(targets)
    for i, s in enumerate(targets, 1):
        student = str(s["name"]).strip()
        out = Path(result_dir) / f"{_safe_name(student)}_{_safe_name(test_date)}_오답.hwpx"
        exam.generate(
            str(out),
            student,
            test_date,
            list(s["wrongs"]),
            class_name=class_name,
            round_name=round_name,
        )
        results.append(str(out))
        if progress:
            progress(i, total, student)
    return results