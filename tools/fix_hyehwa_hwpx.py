from __future__ import annotations
import io, os, re, shutil, sys, tempfile, urllib.request, zipfile
from pathlib import Path
from PIL import Image, ImageOps
from lxml import etree

HWPX_URL = "https://sdmntprcentralus.oaiusercontent.com/files/00000000-f968-81f5-aecb-97a5fe6160b5/raw?se=2026-09-16T08%3A08%3A56Z&sp=r&sv=2026-02-06&sr=b&scid=1d92564a-e2a2-5a1a-9b39-f3918c625d41&skoid=80e81ea6-3c08-46f9-bd84-b87176742bcd&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-09-16T06%3A17%3A54Z&ske=2026-09-17T06%3A17%3A54Z&sks=b&skv=2026-02-06&sig=kfIh9y1iPtwOJbyPnLmW7aDx0yijacHX6trs2SsA/hs%3D"
PAGE1_URL = "https://sdmntprwestcentralus.oaiusercontent.com/files/00000000-9d54-81fb-8bb3-bd4edd3dfbfd/raw?se=2026-09-16T08%3A09%3A06Z&sp=r&sv=2026-02-06&sr=b&scid=9430af8e-511f-5e66-b2e1-ab394427a214&skoid=80e81ea6-3c08-46f9-bd84-b87176742bcd&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-09-16T02%3A45%3A31Z&ske=2026-09-17T02%3A45%3A31Z&sks=b&skv=2026-02-06&sig=AUuFP9laQWh/untPvTYvb4HGuLEuNs1r7KjnBSR2%2BIA%3D"
PAGE4_URL = "https://sdmntprnorthcentralus.oaiusercontent.com/files/00000000-6340-822f-8c01-4a94c7ed3ea1/raw?se=2026-09-16T08%3A09%3A23Z&sp=r&sv=2026-02-06&sr=b&scid=137ba211-448d-5290-bcfa-e3b8f0838a47&skoid=80e81ea6-3c08-46f9-bd84-b87176742bcd&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2026-09-15T19%3A06%3A54Z&ske=2026-09-16T19%3A06%3A54Z&sks=b&skv=2026-02-06&sig=RLjoAAuGYqLQInwZL3KZvlmCga%2BF45w5Hfz1ofVCeis%3D"

OUTNAME = "기출의 현장_대구혜화여자고등학교_2학년_2026_1학기중간_미적분1_해설미주완성.hwpx"

def download(url: str, path: Path):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        path.write_bytes(r.read())

def pad_to_aspect(im: Image.Image, aspect: float, margin=10):
    im = im.convert("RGB")
    w,h = im.size
    cur=w/h
    if abs(cur-aspect)<0.01:
        return im
    if cur<aspect:
        nw=int(round(h*aspect)); canvas=Image.new("RGB",(nw,h),"white"); canvas.paste(im,((nw-w)//2,0)); return canvas
    nh=int(round(w/aspect)); canvas=Image.new("RGB",(w,nh),"white"); canvas.paste(im,(0,(nh-h)//2)); return canvas

def save_crop(page: Image.Image, box, target_path: Path):
    crop = page.crop(box).convert("RGB")
    try:
        old=Image.open(target_path); aspect=old.width/old.height; old.close()
    except Exception:
        aspect=crop.width/crop.height
    crop=pad_to_aspect(crop,aspect)
    # keep print quality comfortably above 300 DPI for the small figure frame
    if crop.width < 1500:
        nh=round(crop.height*1500/crop.width); crop=crop.resize((1500,nh),Image.Resampling.LANCZOS)
    suffix=target_path.suffix.lower()
    if suffix in (".jpg",".jpeg"):
        crop.save(target_path,"JPEG",quality=96,dpi=(300,300))
    else:
        crop.save(target_path,"PNG",dpi=(300,300),optimize=True)

def first_picture_ids(section_xml: Path):
    data=section_xml.read_text(encoding="utf-8",errors="ignore")
    ids=[]
    for pat in [r'binaryItemIDRef="([^"]+)"', r'href="([^"]+)"']:
        for m in re.finditer(pat,data):
            x=m.group(1)
            if x not in ids: ids.append(x)
    return ids

def resolve_bindata(root: Path, bid: str):
    # direct filename candidates
    for p in (root/"BinData").glob("*"):
        if p.stem==bid or p.name==bid or bid in p.name:
            return p
    # look in manifest/content.hpf for id -> href
    for mf in [root/"Contents"/"content.hpf", root/"content.hpf"]:
        if mf.exists():
            txt=mf.read_text(encoding="utf-8",errors="ignore")
            # item may have id and href in either order
            for m in re.finditer(r'<[^>]+>',txt):
                tag=m.group(0)
                if re.search(r'\bid=["\']'+re.escape(bid)+r'["\']',tag):
                    hm=re.search(r'\bhref=["\']([^"\']+)["\']',tag)
                    if hm:
                        q=root/hm.group(1)
                        if q.exists(): return q
                        q=root/"Contents"/hm.group(1)
                        if q.exists(): return q
    return None

def patch_unions(section: Path):
    txt=section.read_text(encoding="utf-8",errors="strict")
    before=txt
    # The generated file used HWP equation's large UNION operator. In interval notation it must be a normal union glyph.
    txt=re.sub(r'(?i)\bUNION\b','∪',txt)
    # Also repair an isolated plain U only when it is between interval right/left delimiters in an equation script.
    txt=re.sub(r'(?<=RIGHT\s\))\s+U\s+(?=LEFT\s\()',' ∪ ',txt)
    section.write_text(txt,encoding="utf-8")
    return before.count("UNION")+before.count("union"), txt.count("∪")

def main():
    repo=Path.cwd(); outdir=repo/"out"; outdir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); src=td/"input.hwpx"; p1=td/"p1.png"; p4=td/"p4.png"; work=td/"work"
        download(HWPX_URL,src); download(PAGE1_URL,p1); download(PAGE4_URL,p4)
        with zipfile.ZipFile(src) as z: z.extractall(work)
        sec=work/"Contents"/"section0.xml"
        if not sec.exists(): raise RuntimeError("Contents/section0.xml not found")
        n_old,n_new=patch_unions(sec)
        ids=first_picture_ids(sec)
        # only IDs that can be resolved to BinData, in document order
        pics=[]
        for bid in ids:
            q=resolve_bindata(work,bid)
            if q and q.suffix.lower() in (".png",".jpg",".jpeg",".bmp",".gif") and q not in pics:
                pics.append(q)
        if len(pics)<2:
            # fallback: document contains only the two problem figures in this generated file
            allimgs=[p for p in (work/"BinData").glob("*") if p.suffix.lower() in (".png",".jpg",".jpeg",".bmp",".gif")]
            for p in sorted(allimgs):
                if p not in pics: pics.append(p)
        if not pics: raise RuntimeError("No embedded problem image found")
        page1=Image.open(p1)
        # Q3: exact original graph only (exclude stem and choices), with a little white margin
        save_crop(page1,(420,135,700,450),pics[0])
        if len(pics)>=2:
            page4=Image.open(p4)
            # Q14: original schematic only
            save_crop(page4,(60,620,300,820),pics[1])
        # XML well-formedness check
        xml_files=list(work.rglob("*.xml")) + list(work.rglob("*.hpf"))
        bad=[]
        for x in xml_files:
            try: etree.parse(str(x))
            except Exception as e: bad.append(f"{x.relative_to(work)}: {e}")
        if bad: raise RuntimeError("XML invalid: "+" | ".join(bad))
        out=outdir/OUTNAME
        with zipfile.ZipFile(out,"w") as z:
            mime=work/"mimetype"
            if mime.exists(): z.write(mime,"mimetype",compress_type=zipfile.ZIP_STORED)
            for f in sorted(work.rglob("*")):
                if not f.is_file(): continue
                rel=f.relative_to(work).as_posix()
                if rel=="mimetype": continue
                z.write(f,rel,compress_type=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(out) as z:
            err=z.testzip()
            if err: raise RuntimeError(f"ZIP CRC error: {err}")
        text=sec.read_text(encoding="utf-8",errors="ignore")
        qa=[]
        qa.append(f"union_operator_tokens_replaced={n_old}")
        qa.append(f"unicode_union_count_after={n_new}")
        qa.append(f"picture_ids={ids}")
        qa.append(f"resolved_pictures={[str(p.relative_to(work)) for p in pics]}")
        qa.append(f"xml_files_checked={len(xml_files)}")
        qa.append("zip_crc=OK")
        qa.append(f"contains_출제의도={'[출제의도]' in text}")
        (outdir/"qa.txt").write_text("\n".join(qa),encoding="utf-8")
        print("\n".join(qa))
        print(out)

if __name__=="__main__": main()
