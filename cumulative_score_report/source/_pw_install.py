# -*- coding: utf-8 -*-
"""exe 안에서 Chromium을 내려받는 진입점 (GUI가 --run 으로 호출)."""
import sys
from playwright.__main__ import main
sys.argv = ["playwright", "install", "chromium"]
main()
