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
}


def _text_of(elem) -> str:
    return " ".join("".join(elem.itertext()).split())


def _safe_name(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', "_", text).strip().rstrip(".")
    return text or "결과"


def _strip_endnotes(paragraph):
    for end in list(paragraph.xpath(".//hp:endNote", namespaces=NS)):
        ctrl = end.getparent()
        ctrl.remove(end)
        if etree.QName(ctrl).localname == "ctrl" and len(ctrl) == 0:
            parent = ctrl.getparent()
            parent.remove(ctrl)
    return paragraph


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


def _label_para(para_pr: str, char_pr: str, text: str, page_break: bool):
    p = etree.Element(f"{{{HP}}}p")
    p.set("id", "2147483648")
    p.set("paraPrIDRef", para_pr)
    p.set("styleIDRef", "0")
    p.set("pageBreak", "1" if page_break else "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")
    run = etree.SubElement(p, f"{{{HP}}}run")
    run.set("charPrIDRef", char_pr)
    t = etree.SubElement(run, f"{{{HP}}}t")
    t.text = text
    return p


class HwpxExam:
    """HWPX 시험지를 한 번 읽고, 한컴 실행 없이 학생별 HWPX를 만든다."""

    def __init__(self, source_path: str, expected_question_count: int):
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

        if len(anchors) < expected_question_count:
            raise ValueError(
                f"시험지에서 문항을 {len(anchors)}개만 찾았습니다. "
                f"엑셀의 문항 수는 {expected_question_count}개입니다."
            )
        if len(anchors) > expected_question_count:
            anchors = anchors[:expected_question_count]
        self.question_count = expected_question_count
        self.anchors = anchors
        self.blocks: dict[int, list] = {}

        for q, start in enumerate(anchors, start=1):
            end = anchors[q] if q < len(anchors) else self.answer_index
            items = []
            for paragraph in self.root[start:end]:
                txt = _text_of(paragraph).strip()
                if txt in SKIP_HEADINGS:
                    continue
                cp = _strip_endnotes(deepcopy(paragraph))
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

        first = True
        for q in wrongs:
            if q not in self.blocks:
                raise ValueError(f"시험지에서 {q}번 문항을 찾지 못했습니다.")
            label = f"[오답 {q}번]  {student}  {test_date}"
            new_root.append(_label_para(self.para_pr, self.char_pr, label, page_break=not first))
            first = False
            for p in self.blocks[q]:
                new_root.append(deepcopy(p))

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
            f"{student}\n시험일 {test_date}\n오답문항: {', '.join(map(str, wrongs))}\n"
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
            etree.fromstring(check.read(SECTION_PATH))

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
