import sys
from pathlib import Path

sys.path.insert(0, str(Path('app').resolve()))
import ultrafast_core as c

tests = {
    r'B=\{1,3,6\}': ['LEFT { 1,3,6 RIGHT }'],
    r'A^c\cup B^c=\{1,2,4,5,6\}': ['SMALLUNION', 'LEFT { 1,2,4,5,6 RIGHT }'],
    r'A^c\cup B^c=(A\cap B)^c': ['SMALLUNION', 'SMALLINTER'],
    r'3\in A\cap B': [' IN ', 'SMALLINTER'],
    r'U=\{1,2,3,4,5,6\}': ['LEFT { 1,2,3,4,5,6 RIGHT }'],
    r'B-A=\{1,6\}': ['LEFT { 1,6 RIGHT }'],
    r'X\subset U': ['SUBSET'],
    r'(B\cup\{x\})-A': ['SMALLUNION', 'LEFT { x RIGHT }'],
    r'U-B=\{2,4,5\}': ['LEFT { 2,4,5 RIGHT }'],
}
for src, wants in tests.items():
    got = c.latex_to_hwp(src)
    print(src, '=>', got)
    for want in wants:
        assert want in got, (src, got, want)

print('SET NOTATION REGRESSION OK')
