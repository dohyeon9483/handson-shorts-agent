"""세로 쇼츠 렌더러(1080x1920) — 가로 강의 영상에서 구간을 골라 순서를 바꿔 붙이고, 세로 레이아웃으로 다시 짠다.

    python tools/shorts.py <spec.json>              # 렌더 → mp4
    python tools/shorts.py <spec.json> --preview    # 구간마다 정지 화면 한 장(몇 초면 끝남) → <out>_preview.jpg
    python tools/shorts.py <spec.json> --fps 15     # 빠른 렌더(움직임이 덜 부드러움)

핸즈온 세션용 이식판. 원본은 lecture-effects 스킬의 shorts.py(2026-10-15)이고 다른 점은 이것뿐이다.
  - ffmpeg 이 PATH 에 없으면 pip 패키지 imageio-ffmpeg 의 ffmpeg 를 쓴다(따로 설치할 필요 없음)
  - 인코더를 자동으로 고른다: NVIDIA → h264_nvenc, 맥 → h264_videotoolbox, 그 밖 → libx264
    (환경변수 HANDSON_ENCODER 로 강제할 수 있다)
  - '슉' 효과음 합성 함수를 이 파일 안에 넣었다
  - --preview, --fps, 진행률 표시

spec 형식은 .claude/skills/shorts-maker/SKILL.md 와 examples/ 를 본다.
"""
import argparse, json, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

import av, cv2, numpy as np
from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).parent
W, H = 1080, 1920
SP_TOP, FADE_TOP, FADE_BOT = 600, 340, 420
SR = 48000


# ---------------------------------------------------------------- ffmpeg · 인코더

def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg 를 찾지 못했습니다. `pip install imageio-ffmpeg` 를 하거나 ffmpeg 를 설치하세요.")


FF = ffmpeg_exe()
ENC_ARGS = {
    "h264_nvenc": ["-c:v", "h264_nvenc", "-cq", "19", "-preset", "p5"],
    "h264_videotoolbox": ["-c:v", "h264_videotoolbox", "-b:v", "10M"],
    "libx264": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"],
}


def pick_encoder():
    """실제로 짧게 인코딩해 보고 되는 것을 고른다(목록에만 있고 GPU 가 없으면 실패하므로)."""
    forced = os.environ.get("HANDSON_ENCODER")
    if forced:
        return forced
    order = ["h264_videotoolbox", "libx264"] if sys.platform == "darwin" else ["h264_nvenc", "libx264"]
    for enc in order:
        r = subprocess.run([FF, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                            *ENC_ARGS[enc][:2], "-f", "null", "-"], capture_output=True)
        if r.returncode == 0:
            return enc
    return "libx264"


# ---------------------------------------------------------------- 타임라인 · 자막

def resolve(p, base):
    p = Path(p)
    return p if p.is_absolute() else (base / p).resolve()


def caption_chunks(words, max_chars=14):
    """구간의 낱말 → 한 줄 자막 조각들. 쉼표·마침표에서 끊기를 우선, max_chars 를 넘기지 않는다."""
    out, cur = [], []
    for w in words:
        if cur and len(" ".join(x["w"] for x in cur + [w])) > max_chars:
            out.append(cur); cur = []
        cur.append(w)
        if w["w"][-1:] in ",.?!" and len(" ".join(x["w"] for x in cur)) >= 6:
            out.append(cur); cur = []
    if cur:
        if out and len(" ".join(x["w"] for x in cur)) <= 4 and len(" ".join(x["w"] for x in out[-1] + cur)) <= max_chars + 3:
            out[-1] += cur
        else:
            out.append(cur)
    return out


def build_timeline(spec, base):
    d = json.loads(resolve(spec["words"], base).read_text(encoding="utf-8"))
    rep = spec.get("replace", {})
    segs, t = [], 0.0
    for g in spec["segments"]:
        dur = g["out"] - g["in"]
        ws = []
        for w in d["words"]:
            if g["in"] - .05 <= w["s"] < g["out"]:
                txt = w["w"].strip()
                for a, b in rep.items():
                    txt = txt.replace(a, b)
                ws.append({"w": txt, "s": t + w["s"] - g["in"], "e": t + min(w["e"], g["out"]) - g["in"]})
        caps = []
        for ch in caption_chunks(ws, spec.get("max_chars", 14)):
            words = [x["w"] for x in ch]
            if words[-1].endswith("."):
                words[-1] = words[-1][:-1]
            caps.append({"s": ch[0]["s"], "e": ch[-1]["e"], "words": words, "ws": [x["s"] for x in ch]})
        for a, b in zip(caps, caps[1:]):           # 사이 틈은 앞 자막을 늘려 메운다(깜빡임 없게)
            if b["s"] - a["e"] < .6:
                a["e"] = b["s"]
        segs.append(dict(g, t0=t, t1=t + dur, caps=caps))
        t += dur
    return segs, t


# ---------------------------------------------------------------- 화면 합성

def fade_alpha(h, top, bot):
    a = np.ones(h, np.float32)
    r = np.arange(top, dtype=np.float32) / top
    a[:top] = np.interp(r, [0, .45, 1], [0, .35, 1])
    shade = np.ones(h, np.float32)
    shade[h - bot:] = 1 - .6 * np.linspace(0, 1, bot)
    return a[:, None, None], shade[:, None, None]


def place_speaker(canvas, frame, sp, y0, top_fade):
    """원본 frame 의 (cx-cw/2, cy) 부터 폭 cw 를 1080 폭으로 키워 canvas 의 y0~맨 아래에 놓는다."""
    cw = sp.get("cw", 860); s = W / cw; h = H - y0
    x0 = int(sp.get("cx", 960) - cw / 2); y_src = int(sp.get("cy", 20)); ch = int(np.ceil(h / s))
    crop = frame[y_src:y_src + ch, max(0, x0):x0 + cw]
    big = cv2.resize(crop, (W, int(round(crop.shape[0] * s))), interpolation=cv2.INTER_CUBIC)[:h]
    hh = big.shape[0]
    a, shade = fade_alpha(hh, top_fade, min(FADE_BOT, hh))
    big = big.astype(np.float32) * shade * (1 - sp.get("dim", 0))
    reg = canvas[y0:y0 + hh].astype(np.float32)
    canvas[y0:y0 + hh] = (reg * (1 - a) + big * a).astype(np.uint8)


def place_pip(canvas, frame, p, k):
    x0, y0, cw, ch = p["crop"]; S = p["size"]
    crop = cv2.resize(frame[y0:y0 + ch, x0:x0 + cw], (S, S), interpolation=cv2.INTER_AREA).astype(np.float32)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32) + .5
    m = (np.clip(S / 2 - np.sqrt((xx - S / 2) ** 2 + (yy - S / 2) ** 2) + .5, 0, 1) * k)[:, :, None]
    reg = canvas[p["y"]:p["y"] + S, p["x"]:p["x"] + S].astype(np.float32)
    canvas[p["y"]:p["y"] + S, p["x"]:p["x"] + S] = (reg * (1 - m) + crop * m).astype(np.uint8)


def ease(x):
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


def zoom_at(g, ts):
    """구간 카메라 배율: cam 키프레임(cut = 즉시, push = dur 동안 부드럽게)."""
    z = 1.0
    for k in sorted(g.get("cam", []), key=lambda k: k["t"]):
        if ts < k["t"]:
            break
        if k.get("mode", "cut") == "push":
            z = z + (k["z"] - z) * ease((ts - k["t"]) / k.get("dur", 2.0))
        else:
            z = k["z"]
    return z


def shake_at(g, ts):
    dx = dy = 0.0
    for k in g.get("shake", []):
        a = ts - k["t"]
        if 0 <= a <= k.get("dur", .35):
            d = (1 - a / k.get("dur", .35)) ** 2 * k.get("amp", 26)
            dx += d * np.sin(a * 83); dy += d * np.cos(a * 61)
    return dx, dy


def cam_speaker(sp, z, sh, y0, focus):
    """강사 크롭을 배율 z 로 — focus(원본 좌표, 보통 얼굴)가 화면에서 제자리에 남게. sh = 흔들림(화면 px)."""
    if abs(z - 1) < 1e-4 and not any(sh):
        return sp
    cw = sp.get("cw", 860); s = W / cw; x0 = sp.get("cx", 960) - cw / 2; cy = sp.get("cy", 20)
    fx, fy = focus; X = (fx - x0) * s; Y = y0 + (fy - cy) * s
    cw2 = cw / z; s2 = s * z
    x0n = fx - (X + sh[0]) / s2; cyn = fy - (Y - y0 + sh[1]) / s2
    x0n = min(max(0.0, x0n), 1920 - cw2); cyn = max(0.0, cyn)
    return dict(sp, cw=int(round(cw2)), cx=x0n + cw2 / 2, cy=cyn)


def post_fx(canvas, g, ts, idx):
    """화면 전체 효과: glitch(색 분리 + 가로 띠 밀림) · flash(흰 번쩍)."""
    for p in g.get("post", []):
        a = ts - p["t"]; d = p.get("dur", .4)
        if not 0 <= a <= d:
            continue
        if p["type"] == "glitch":
            k = 1 - a / d; dx = int(26 * k) + 4
            canvas[:, :, 2] = np.roll(canvas[:, :, 2], -dx, axis=1); canvas[:, :, 0] = np.roll(canvas[:, :, 0], dx, axis=1)
            rng = np.random.default_rng(idx)
            for _ in range(int(3 + 5 * k)):
                y = int(rng.integers(300, H - 300)); h = int(rng.integers(12, 60))
                canvas[y:y + h] = np.roll(canvas[y:y + h], int(rng.integers(-90, 90)), axis=1)
        elif p["type"] == "flash":
            al = .85 * (1 - a / d)
            canvas[:] = (canvas.astype(np.float32) * (1 - al) + 255 * al).astype(np.uint8)
    return canvas


def shot(page, transparent=True):
    png = page.screenshot(omit_background=transparent, type="png")
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    if img.shape[2] == 3:
        img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    return img


class Frame:
    """한 프레임 합성기 — 렌더와 미리보기가 같은 코드를 쓴다."""

    def __init__(self, page, board, total):
        self.page, self.board, self.total = page, board, total
        self.cache_dom, self.cache, self.shots = None, None, 0

    def compose(self, g, cur, ts, idx):
        tl = g["t0"] + ts
        canvas = self.board.copy()
        lay = g.get("layout", "speaker")
        z, sh = zoom_at(g, ts), shake_at(g, ts); foc = g.get("focus", (960, 380))
        if lay == "speaker":
            place_speaker(canvas, cur, cam_speaker(g.get("speaker", {}), z, sh, SP_TOP, foc), SP_TOP, FADE_TOP)
        elif lay == "split":
            y0 = g.get("split_y", 900)
            place_speaker(canvas, cur, cam_speaker(g.get("speaker", {"cx": 960, "cy": 180, "cw": 880}), z, sh, y0, foc), y0, 300)
        if g.get("pip"):
            k = 1 - (1 - min(1.0, ts / .35)) ** 3
            place_pip(canvas, cur, g["pip"], k)
        capst = None                                   # 말자막: 지금 말하는 낱말
        for c in g["caps"]:
            if c["s"] <= tl < c["e"] + 1e-6:
                on = max([j for j, s0 in enumerate(c["ws"]) if s0 <= tl + .05] or [0])
                capst = {"words": c["words"], "on": on, "since": round(tl - c["ws"][on], 3)}; break
        seg_js = {k: g.get(k) for k in ("layout", "titles", "graphic", "pip", "cta", "split_y", "style", "fx", "cap_mode", "cap_size") if g.get(k) is not None}
        dom = self.page.evaluate("s=>render(s)", {"seg": seg_js, "ts": round(ts * 30) / 30, "cap": capst})
        if dom != self.cache_dom:                       # 그래픽이 바뀐 프레임만 다시 찍는다
            self.cache = shot(self.page); self.cache_dom = dom; self.shots += 1
        a = self.cache[:, :, 3:4].astype(np.float32) / 255
        if a.any():
            canvas = (canvas.astype(np.float32) * (1 - a) + self.cache[:, :, :3].astype(np.float32) * a).astype(np.uint8)
        if g.get("post"):
            canvas = post_fx(canvas, g, ts, idx)
        x1 = 60 + int((880 - 60) * (tl / self.total))   # 진행 막대
        cv2.rectangle(canvas, (60, 258), (880, 264), (60, 60, 60), -1)
        cv2.rectangle(canvas, (60, 258), (x1, 264), (0, 212, 255), -1)
        return canvas


def open_page(p):
    b = p.chromium.launch(args=["--allow-file-access-from-files"]); page = b.new_page(viewport={"width": W, "height": H})
    page.goto((HERE / "shorts_overlay.html").resolve().as_uri()); page.wait_for_load_state("networkidle")
    page.evaluate("document.fonts.ready"); page.evaluate("Promise.all([400,600,700,800,900].map(w=>document.fonts.load(`${w} 40px Pretendard`,'가')))")
    page.evaluate("()=>Promise.all(['40px \"East Sea Dokdo\"','700 40px GmarketSans','500 40px GmarketSans','40px \"Noto Color Emoji\"'].map(f=>document.fonts.load(f,'가😀')))")
    page.evaluate("boardOnly(true)"); page.evaluate("s=>render(s)", {"seg": {}, "ts": 0})
    page.evaluate("document.getElementById('stage').innerHTML=''")
    board = shot(page, False)[:, :, :3].copy()
    page.evaluate("boardOnly(false)")
    return b, page, board


def frame_at(cin, vs, t):
    """원본에서 t 초에 가장 가까운 프레임 한 장."""
    cin.seek(int(max(0, t - .5) / vs.time_base), stream=vs)
    cur = None
    for f in cin.decode(vs):
        cur = f.to_ndarray(format="bgr24")
        if float(f.pts * vs.time_base) >= t - .02:
            break
    return cur


# ---------------------------------------------------------------- 효과음(직접 합성, 외부 소스 아님)

def whoosh_wave(dur=.6, seed=7):
    """'슉' — 잡음에 차단 주파수가 250Hz→4kHz→250Hz 로 움직이는 저역 통과 필터 + 산 모양 볼륨."""
    rng = np.random.default_rng(seed)
    n = int(SR * dur); x = np.linspace(0, 1, n)
    noise = rng.standard_normal(n)
    fc = 250 + 3800 * np.sin(np.pi * np.clip(x / .9, 0, 1)) ** 2
    alpha = 1 - np.exp(-2 * np.pi * fc / SR)
    y = np.empty(n); acc = 0.0
    for i in range(n):
        acc += alpha[i] * (noise[i] - acc); y[i] = acc
    env = np.sin(np.pi * np.clip(x, 0, 1)) ** 2 * (1 - .3 * x)
    y = y * env; y = y / (np.abs(y).max() + 1e-9) * .5
    return np.stack([y * (1 - .35 * x), y * (.65 + .35 * x)], 1)


def synth(kind):
    def tt(d):
        return np.arange(int(SR * d)) / SR
    if kind == "pop":
        t = tt(.1); f = 1200 * (260 / 1200) ** (t / .1); ph = 2 * np.pi * np.cumsum(f) / SR
        y = np.sin(ph) * np.exp(-t * 45) * .8
    elif kind == "ppyong":
        t = tt(.24); f = 480 * (1800 / 480) ** (t / .24); ph = 2 * np.pi * np.cumsum(f) / SR
        y = np.tanh(3 * np.sin(ph)) * np.sin(np.pi * t / .24) ** .7 * .38
    elif kind == "ttaeng":
        t = tt(.5); y = (np.sign(np.sin(2 * np.pi * 180 * t)) + np.sign(np.sin(2 * np.pi * 191 * t))) * .5
        y = y * np.minimum(1, t / .005) * (1 - t / .5) * .22
    elif kind == "dudung":
        y = np.zeros(int(SR * .9))
        for st in (0, .3):
            t = tt(.55); f = 110 * (45 / 110) ** (t / .45); ph = 2 * np.pi * np.cumsum(f) / SR
            hit = np.sin(ph) * np.exp(-t * 6.5) * .95
            i = int(st * SR); n = min(len(hit), len(y) - i); y[i:i + n] += hit[:n]
    elif kind == "ding":
        t = tt(1.3); y = sum(a * np.sin(2 * np.pi * 1568 * m * t) for m, a in ((1, 1), (2.76, .4), (5.4, .18))) * np.exp(-t * 4.5) * .32
    elif kind == "whoosh":
        return whoosh_wave()
    else:
        raise ValueError(f"모르는 효과음: {kind} (pop·ppyong·ttaeng·dudung·ding·whoosh)")
    return np.stack([y, y], 1)


def mix_events(out, events, total, vol=.5):
    """효과음들을 한 트랙(wav)으로 만들어 영상 소리에 섞는다. events = [(초, 종류)]."""
    if not events:
        return
    import wave
    trk = np.zeros((int(SR * (total + 2)), 2)); cache = {}
    for t, kind in events:
        if kind not in cache:
            cache[kind] = synth(kind)
        snd = cache[kind]; i = max(0, int((t - (.3 if kind == "whoosh" else 0)) * SR))
        n = min(len(snd), len(trk) - i); trk[i:i + n] += snd[:n]
    trk = np.clip(trk * vol, -1, 1)
    wav = out.with_name("_sfx.wav"); tmp = out.with_name(out.stem + "_sfx" + out.suffix)
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(SR); wf.writeframes((trk * 32767).astype("<i2").tobytes())
    subprocess.run([FF, "-v", "error", "-y", "-i", str(out), "-i", str(wav), "-filter_complex",
                    "[0:a][1:a]amix=inputs=2:normalize=0:duration=first[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", str(tmp)], check=True)
    tmp.replace(out); wav.unlink(missing_ok=True)


# ---------------------------------------------------------------- 실행

def load(spec_path):
    spec_path = Path(spec_path); base = spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    src, out = resolve(spec["src"], base), resolve(spec["out"], base)
    if not src.exists():
        sys.exit(f"원본 영상이 없습니다: {src}\n  → media/ 폴더에 OT_촬영본.mp4 를 넣었는지 확인하세요(README 참고).")
    out.parent.mkdir(parents=True, exist_ok=True)
    segs, total = build_timeline(spec, base)
    return spec, src, out, segs, total


def preview(spec_path):
    """구간마다 가운데쯤 한 장 → 가로로 이어 붙인 미리보기 jpg. 렌더 전에 배치·제목을 확인하는 용도."""
    spec, src, out, segs, total = load(spec_path)
    t0 = time.time(); tiles = []
    with sync_playwright() as p:
        b, page, board = open_page(p); fr = Frame(page, board, total)
        cin = av.open(str(src)); vs = cin.streams.video[0]
        for k, g in enumerate(segs):
            dur = g["t1"] - g["t0"]
            ts = min(dur - .05, max(1.2, dur * .55))      # 제목·그래픽이 다 뜬 뒤쯤
            img = fr.compose(g, frame_at(cin, vs, g["in"] + ts), ts, k)
            img = cv2.resize(img, (360, 640), interpolation=cv2.INTER_AREA)
            cv2.putText(img, f"{k + 1}  {g['in']:.1f}-{g['out']:.1f}s", (12, 628), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 2)
            tiles.append(img)
        b.close()
    sheet = out.with_name(out.stem + "_preview.jpg")
    cv2.imencode(".jpg", np.hstack(tiles))[1].tofile(str(sheet))
    print(f"미리보기: {sheet}  ({len(segs)} 구간 · 완성 길이 {total:.1f}초 · {time.time() - t0:.0f}s)")


def render(spec_path, fps_override=None):
    spec, src, out, segs, total = load(spec_path)
    fps = fps_override or spec.get("fps", 30)
    enc_name = pick_encoder()
    print(f"{len(segs)} 구간 · {total:.1f}초 · 자막 {sum(len(s['caps']) for s in segs)} 조각 · {fps}fps · 인코더 {enc_name}")

    tmp = Path(tempfile.mkdtemp())
    # 소리: 구간마다 잘라 아주 짧게 페이드하고 이어 붙인다(이음새 딸깍 없게)
    fl = f"[0:a]asplit={len(segs)}" + "".join(f"[i{i}]" for i in range(len(segs))) + ";" if len(segs) > 1 else "[0:a]acopy[i0];"
    fl += "".join(f"[i{i}]atrim={g['in']}:{g['out']},asetpts=PTS-STARTPTS,afade=t=in:d=0.02,afade=t=out:st={g['out'] - g['in'] - .03:.3f}:d=0.03[a{i}];"
                 for i, g in enumerate(segs)) + "".join(f"[a{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=0:a=1[a]"
    wav = tmp / "a.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-filter_complex", fl, "-map", "[a]", str(wav)], check=True)

    enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                            "-i", str(wav), "-map", "0:v", "-map", "1:a", *ENC_ARGS[enc_name],
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], stdin=subprocess.PIPE)
    t0c = time.time(); done = 0; n_all = int(round(total * fps)); last = 0
    with sync_playwright() as p:
        b, page, board = open_page(p); fr = Frame(page, board, total)
        cin = av.open(str(src)); vs = cin.streams.video[0]
        for g in segs:
            cin.seek(int(max(0, g["in"] - .5) / vs.time_base), stream=vs)
            it = cin.decode(vs); cur = None; cur_t = -1
            n = int(round((g["t1"] - g["t0"]) * fps))
            for i in range(n):
                ts = i / fps; target = g["in"] + ts
                while cur_t < target - .5 / fps:
                    try:
                        f = next(it)
                    except StopIteration:
                        break
                    cur = f.to_ndarray(format="bgr24"); cur_t = float(f.pts * vs.time_base)
                enc.stdin.write(fr.compose(g, cur, ts, i).tobytes())
                done += 1
                if time.time() - last > 3:
                    last = time.time(); el = last - t0c
                    print(f"  렌더 {done / fps:5.1f}/{total:.1f}초  ({el:.0f}s 경과, 약 {el / done * (n_all - done):.0f}s 남음)", flush=True)
        b.close()
    enc.stdin.close(); enc.wait()
    ev = [(g["t0"], "whoosh") for a, g in zip(segs, segs[1:]) if a.get("layout") != g.get("layout")] if spec.get("sfx_auto", True) else []
    ev += [(g["t0"] + e["t"], e["kind"]) for g in segs for e in g.get("sfx", [])]
    if spec.get("sfx", True):
        mix_events(out, sorted(ev), total, spec.get("sfx_vol", .5))
    print(f"완성: {out}\n  {total:.1f}초 · 그래픽 촬영 {fr.shots} 장 · 효과음 {len(ev)} · {time.time() - t0c:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="세로 쇼츠 렌더러")
    ap.add_argument("spec")
    ap.add_argument("--preview", action="store_true", help="구간마다 정지 화면 한 장만(빠름)")
    ap.add_argument("--fps", type=int, help="렌더 fps 를 낮춰 빠르게(예: 15)")
    a = ap.parse_args()
    preview(a.spec) if a.preview else render(a.spec, a.fps)
