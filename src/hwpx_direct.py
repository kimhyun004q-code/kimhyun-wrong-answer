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


def _section_template(root):
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

    # 결과물은 2단 고정: 왼쪽 단 1문제 / 오른쪽 단 1문제.
    for col_pr in p.xpath(".//hp:colPr", namespaces=NS):
        col_pr.set("type", "NEWSPAPER")
        col_pr.set("layout", "LEFT")
        col_pr.set("colCount", "2")
        col_pr.set("sameSz", "1")
        if not col_pr.get("sameGap"):
            col_pr.set("sameGap", "1000")

    # 미주는 문서 끝에 배치되게 유지한다.
    for placement in p.xpath(".//hp:endNotePr/hp:placement", namespaces=NS):
        placement.set("place", "END_OF_DOCUMENT")
        placement.set("beneathText", "0")

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


def _append_endnote_page_separator(root, para_pr: str, char_pr: str) -> None:
    """문제 본문과 문서 끝 미주 사이에 실제 본문 쪽 나누기를 넣는다.

    HWPX의 endNote 내부 문단 pageBreak는 미주 배치 단계에서 무시될 수 있다.
    따라서 END_OF_DOCUMENT 미주보다 앞선 마지막 본문 문단 자체를 새 페이지에서
    시작하도록 만들어, 모든 미주 해설이 문제 다음 새 페이지에 놓이게 한다.
    """
    separator = _label_para(
        para_pr,
        char_pr,
        "",
        page_break=True,
        column_break=False,
    )
    separator.set("id", "2147483647")
    root.append(separator)

    # 미주 안쪽에는 별도 쪽 나누기를 두지 않는다. 첫 미주부터 자연스럽게 이어 붙인다.
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
            self.entries = [(info, z.read(info.filename)) for info in z.infolist()]
            self.root = etree.fromstring(z.read(SECTION_PATH))

        self.para_pr, self.char_pr = _style_ids(self.root)
        self.template = _section_template(self.root)
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
            # 수기 모드에서는 엑셀 없이 HWPX 자체에서 전체 문항 수를 자동 인식한다.
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

                # 문항의 미주(endNote)를 제거하지 않는다.
                # 미주 본문도 ctrl/endNote 내부에 있으므로 문항 문단을 통째로 보존한다.
                cp = deepcopy(paragraph)
                cp.set("pageBreak", "0")
                cp.set("columnBreak", "0")
                if not _is_empty_layout_para(cp):
                    items.append(cp)
            if not items:
                raise ValueError(f"{q}번 문항 내용을 추출하지 못했습니다.")
            self.blocks[q] = items

    def _build_section(self, student: str, test_date: str, wrongs: list[int]) -> bytes:
        new_root = deepcopy(self.root)
        for child in list(new_root):
            new_root.remove(child)
        new_root.append(deepcopy(self.template))

        # 정확한 2단 배치:
        # 1번째 오답 -> 1페이지 왼쪽 단
        # 2번째 오답 -> 같은 페이지 오른쪽 단
        # 3번째 오답 -> 2페이지 왼쪽 단
        # 4번째 오답 -> 같은 페이지 오른쪽 단 ...
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

        # 핵심: 마지막 문제 뒤의 '본문'에 실제 쪽 나누기를 추가한다.
        # 문서 끝 미주는 이 새 페이지 다음에 렌더링된다.
        _append_endnote_page_separator(new_root, self.para_pr, self.char_pr)

        return etree.tostring(
            new_root,
            xml_declaration=True,
            encoding="UTF-8",
            standalone=True,
        )

    def generate(self, output_path: str, student: str, test_date: str, wrongs: list[int]) -> str:
        wrongs = sorted({int(q) for q in wrongs if 1 <= int(q) <= self.question_count})
        if not wrongs:
            raise ValueError(f"{student}: 오답 문항이 없습니다.")

        section_data = self._build_section(student, test_date, wrongs)
        preview = (
            f"{student}\n시험일 {test_date}\n오답문항: {', '.join(map(str, wrongs))}\n미주 포함 / 문제 뒤 실제 쪽 나누기\n"
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
    progress=None,
) -> list[str]:
    exam = HwpxExam(exam_path, question_count)
    targets = [s for s in students if s.get("wrongs")]
    results = []
    total = len(targets)
    for i, s in enumerate(targets, 1):
        student = str(s["name"]).strip()
        out = Path(result_dir) / f"{_safe_name(student)}_{_safe_name(test_date)}_오답.hwpx"
        exam.generate(str(out), student, test_date, list(s["wrongs"]))
        results.append(str(out))
        if progress:
            progress(i, total, student)
    return results
