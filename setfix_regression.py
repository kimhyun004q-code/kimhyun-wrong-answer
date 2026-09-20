import sys
from pathlib import Path

sys.path.insert(0, str(Path("app").resolve()))
import ultrafast_core as c

def compact(s):
    return s.replace(" ", "").replace("{", "").replace("}", "")

cases = [
    (r"B=\{1,3,6\}", ["LEFT1,3,6RIGHT"]),
    (r"A^c\cup B^c=\{1,2,4,5,6\}", ["SMALLUNION", "LEFT1,2,4,5,6RIGHT"]),
    (r"A^c\cup B^c=(A\cap B)^c", ["SMALLUNION", "SMALLINTER"]),
    (r"3\in A\cap B", ["IN", "SMALLINTER"]),
    (r"U=\{1,2,3,4,5,6\}", ["LEFT1,2,3,4,5,6RIGHT"]),
    (r"A\cap B=\{3\}", ["SMALLINTER", "LEFT3RIGHT"]),
    (r"B-A=\{1,6\}", ["LEFT1,6RIGHT"]),
    (r"X\subset U", ["SUBSET"]),
    (r"(B\cup\{x\})-A", ["SMALLUNION", "LEFTxRIGHT"]),
    (r"U-B=\{2,4,5\}", ["LEFT2,4,5RIGHT"]),
]

for src, wants in cases:
    got = c.latex_to_hwp(src)
    chk = compact(got)
    print(src, "=>", got)
    for want in wants:
        assert want.replace(" ", "") in chk, (src, got, want)

print("SET NOTATION REGRESSION OK")
