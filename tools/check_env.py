"""실습 환경 점검 — 무엇이 빠졌는지 한눈에.

    python tools/check_env.py            # 설치 점검
    python tools/check_env.py --smoke    # + 코드 데모로 네 양식 실제 미리보기 시험
"""
import importlib, platform, subprocess, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
ok_all = True


def row(ok, name, msg=""):
    global ok_all
    ok_all &= ok
    print(f"{'✅' if ok else '❌'} {name:<22} {msg}")


print(f"OS {platform.system()} {platform.release()} · Python {sys.version.split()[0]}\n")

row(sys.version_info >= (3, 10), "Python 3.10 이상", "" if sys.version_info >= (3, 10) else "→ python.org 에서 3.11~3.12 설치")

missing = []
for mod, pkg in [("av", "av"), ("cv2", "opencv-python-headless"), ("numpy", "numpy"), ("playwright", "playwright"), ("imageio_ffmpeg", "imageio-ffmpeg")]:
    try:
        importlib.import_module(mod)
    except Exception:
        missing.append(pkg)
row(not missing, "파이썬 패키지", f"→ 빠짐: {', '.join(missing)}  (pip install -r requirements.txt)" if missing else "")

ff = None
if not missing:
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import shorts
        ff = shorts.FF
        row(True, "ffmpeg", ff)
        t = time.time(); enc = shorts.pick_encoder()
        row(True, "영상 인코더", f"{enc}" + ("  (GPU 없음 — 렌더가 조금 느립니다)" if enc == "libx264" else "  (빠름)"))
    except SystemExit as e:
        row(False, "ffmpeg", str(e))
    except Exception as e:
        row(False, "렌더러 불러오기", repr(e))

if "playwright" not in missing:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page()
            pg.goto((ROOT / "tools" / "shorts_overlay.html").as_uri()); pg.wait_for_load_state("networkidle")
            fonts = pg.evaluate("()=>document.fonts.load('900 40px Pretendard','가').then(f=>f.length)")
            b.close()
        row(True, "크로미움(Playwright)")
        row(fonts > 0, "글꼴 내려받기(인터넷)", "" if fonts > 0 else "→ 와이파이 확인. 글꼴 CDN 에 접속하지 못하면 제목 글꼴이 바뀝니다")
    except Exception as e:
        row(False, "크로미움(Playwright)", "→ python -m playwright install chromium" + f"  ({type(e).__name__})")

M = ROOT / "media"
videos = sorted(M.rglob("*.mp4"))
print(f"\n실습 원본: {len(videos)}개. 배포 샘플의 VTT·words.json을 재사용합니다. VTT만으로 문장 자막도 가능합니다.")
if not videos:
    print("→ 노션 샘플 영상 또는 본인 영상을 media/에 넣으세요. 도구 점검은 계속합니다.")
for name in ("landscape.py", "landscape_overlay.html", "shorts.py", "shorts_overlay.html", "subtitles.py", "prepare_video.py", "transcribe.py"):
    row((ROOT / "tools" / name).exists(), name)
row((ROOT / "docs/styles/index.html").exists(), "대표 양식 이미지 갤러리")

if "--smoke" in sys.argv and ok_all:
    t = time.time()
    r = subprocess.run([sys.executable, str(ROOT / "tools/style_previews.py")], capture_output=True, text=True, encoding="utf-8", errors="replace")
    prev = [ROOT / f"docs/styles/{i}.jpg" for i in range(1,5)]
    good = r.returncode == 0 and all(p.exists() and p.stat().st_mtime >= t-1 for p in prev)
    err = ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1][:120]
    row(good, "4양식 미리보기 시험", f"{time.time()-t:.0f}초 · 합성 데모, 샘플 영상 불필요" if good else "→ 오류: " + err)

print("\n" + ("도구 준비 완료. prepare_video.py로 선택한 원본의 기존 자막·대표 화면을 확인하세요. 샘플 STT 재실행은 필요 없습니다." if ok_all else "❌ 항목을 고친 뒤 다시 실행하세요."))
sys.exit(0 if ok_all else 1)
