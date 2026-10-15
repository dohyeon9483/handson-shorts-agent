# 실습 환경 설치 (Windows PowerShell) — 레포 폴더에서 실행:  powershell -ExecutionPolicy Bypass -File setup\setup_windows.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
python tools\check_env.py
