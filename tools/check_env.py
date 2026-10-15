"""실습 환경 점검 — 무엇이 빠졌는지 한눈에.

    python tools/check_env.py            # 설치 점검
    python tools/check_env.py --smoke    # + 체크포인트로 미리보기 한 장을 실제로 만들어 본다(10~30초)
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
for name, pat in [("샘플 영상(.mp4)", "*.mp4"), ("받아쓰기(.words.json)", "*.words.json"), ("받아쓰기(.vtt)", "*.vtt"),
                  ("샘플정보.md", "샘플정보.md"), ("예시 spec", "examples/*.json"), ("체크포인트 spec", "checkpoints/*.json")]:
    found = sorted(M.glob(pat))
    row(bool(found), f"media/ {name}", found[0].name if found else "→ 노션 가이드의 샘플 묶음을 media/ 폴더에 넣으세요")

if "--smoke" in sys.argv and ok_all:
    cps = sorted((M / "checkpoints").glob("*.json"))
    if cps:
        t = time.time()
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "shorts.py"), str(cps[0]), "--preview"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        prev = sorted((ROOT / "out").glob("*_preview.jpg"), key=lambda p: p.stat().st_mtime)
        good = r.returncode == 0 and prev and prev[-1].stat().st_mtime >= t - 1
        err = ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1][:120]
        row(bool(good), "미리보기 시험", f"{time.time() - t:.0f}초 · out/{prev[-1].name}" if good else "→ 오류: " + err)

print("\n" + ("모두 준비됐습니다. 이제 Claude Code 에서 이 폴더를 여세요." if ok_all else "❌ 항목을 고친 뒤 다시 실행하세요. 막히면 옆 사람이나 진행자에게!"))
