# 김현수학 누적 성적표

이 폴더는 `누적성적표.zip`에서 확인한 성적표 생성 프로그램을 별도로 정리하기 위한 위치입니다.

## 원본 보관 상태
- 전달받은 ZIP에는 `김현수학누적성적표.exe`가 포함되어 있습니다.
- Python 소스 파일도 포함되어 있습니다: `성적표_GUI.py`, `build_xlsx.py`, `discover.py`, `parse.py`, `report3.py`, `run3.py`, `build_exe.py` 등.
- 실행 파일의 전체 배포 폴더와 PyInstaller 빌드 산출물도 ZIP 안에 포함되어 있었습니다.

## 주의
이 문서는 프로젝트 위치를 표시하는 안내 파일입니다. ZIP에 들어 있던 실행 파일과 소스 전체가 이 GitHub 폴더에 업로드되었다는 의미는 아닙니다. 실제 소스 파일은 별도로 추가해야 합니다.

## 권장 업로드 구성
- Python 소스와 `.spec` 파일
- `requirements.txt` 및 사용법
- EXE는 GitHub Release 자산으로 별도 배포
- `build/`, `__pycache__/`, `dist/` 내부의 중복 라이브러리는 저장소에 넣지 않음
