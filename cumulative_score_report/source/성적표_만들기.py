# -*- coding: utf-8 -*-
"""성적표 만들기 — 대치온 파일이 든 폴더만 지정하면 끝난다.

    python3 성적표_만들기.py [파일폴더] [출력폴더]

파일폴더에 넣을 것 (손으로 옮겨 적을 것은 없다):
    260803_80D5_S1.xlsx   대치온에서 내려받은 회차 결과 (필수)
    260803.hwp            같은 날짜 시험지 (선택 — 차시 번호를 읽는 용도)
    …최근 4회분

만들어지는 것:
    성적표_반명_기간.xlsx        대시보드 + 학생별 시트 (수식으로 연결됨)
    성적표_반명_기간_이미지/     학생별 PNG (카톡 발송용)
    성적표_반명_기간_이미지.zip
    성적표_반명_기간.pdf         보관용
    성적표_반명_기간_집계.xlsx

두 번째부터는 워크북의 '지도 방향'에 고쳐 쓴 문장을 그대로 이어받는다.
"""
import os, sys, subprocess, glob

HERE = os.path.dirname(os.path.abspath(__file__))
UP = sys.argv[1] if len(sys.argv) > 1 else "/mnt/user-data/uploads"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/mnt/user-data/outputs"
RECALC = "/mnt/skills/public/xlsx/scripts/recalc.py"


def run(label, args):
    print(f"\n▶ {label}")
    r = subprocess.run([sys.executable] + args, cwd=HERE, text=True,
                       encoding="utf-8", errors="replace", capture_output=True)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr.rstrip())
        sys.exit(f"[중단] {label} 실패")


print("=" * 60)
print(f"입력 폴더: {UP}")
print(f"출력 폴더: {OUT}")
print("=" * 60)

# 1) 엑셀 워크북 (먼저 만들어야 이미지가 코멘트를 이어받는다)
run("엑셀 워크북 만드는 중", ["build_xlsx.py", UP, OUT])

books = sorted(glob.glob(os.path.join(OUT, "성적표*.xlsx")))
books = [b for b in books if not b.endswith("집계.xlsx")]
if books and os.path.exists(RECALC):
    print("\n▶ 수식 계산 중 (LibreOffice)")
    r = subprocess.run([sys.executable, RECALC, books[-1], "300"],
                       text=True, capture_output=True)
    print(r.stdout.rstrip())

# 2) 학생별 이미지 + PDF + 집계
run("학생별 이미지 만드는 중", ["run3.py", UP, OUT])

print("\n" + "=" * 60)
for f in sorted(os.listdir(OUT)):
    p = os.path.join(OUT, f)
    if os.path.isdir(p):
        print(f"  {f}/  ({len(os.listdir(p))}장)")
    else:
        print(f"  {f}  ({os.path.getsize(p)/1024/1024:.1f}MB)")
print("=" * 60)
print("완료. 다음 회차에는 새 파일만 폴더에 넣고 다시 실행하세요.")
