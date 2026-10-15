#!/usr/bin/env bash
# 실습 환경 설치 (macOS) — 레포 폴더에서 실행:  bash setup/setup_mac.sh
set -e
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 tools/check_env.py --smoke
