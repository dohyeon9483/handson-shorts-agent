"""핸즈온 가로 강의 렌더러: night / elearn, 1920×1080, 30초 이하.

    python tools/landscape.py <spec.json> --preview --at 3 8
    python tools/landscape.py <spec.json> --plan ../강조계획서.md

원형: lecture-effects/scripts/fx.py 및 overlay.html (2026-10-15).
미리보기는 정지 JPG만 생성한다. 렌더 전에는 사람의 계획서 승인이 필요하다.
ffmpeg 경로와 NVIDIA/Mac/CPU 인코더 선택은 portable shorts.py와 공유한다.

spec 한 장이 영상 한 구간의 효과 목록이다. 시간은 초(영상 기준), 좌표는 원본 1920x1080 픽셀.
- zoom                              : 카메라. box 영역으로 밀어 들어갔다가 t1 에 빠진다
- box/underline/circle/check/spot   : 화면 부위에 붙는 표시(월드 좌표). 확대를 따라 움직인다
- caption/ref                       : 화면에 고정된 강조자막·참고자료 카드
- board                             : 분할 보드. 화면 녹화가 카드로 줄어들고(카메라) 옆에 단계 목록 (2026-10-11)
- hl/hand                           : 형광펜·손글씨 주석(월드 좌표)
- hdr/map/kinetic/recap             : 소주제 머리말·장 지도·핵심 문장·마무리 요약. kinetic/recap 은 뒤 화면을 흐린다
- broll                             : 외부 스톡 영상·이미지를 그 구간에 끼워 넣는다(file, from, kb, pan, credit) — 2026-10-14
- title/keyword/tags/doc/contrast/odometer/cards/road : 제안 9종 그래픽(overlay.html) — 2026-10-14
- pip                               : 강사 창(원형·둥근 사각) — 원본 영상을 실시간으로 잘라 넣는다
- reframe                           : 카메라가 화면을 키우며 강사를 한쪽으로 밀고 반대쪽은 보드 — 2026-10-14
- divider                           : 간지(장 구분 카드) — 새 주제가 시작될 때. sfx 로 '슉' — 2026-10-14
- whip                              : 휩 전환(화면이 휙 밀려나며 장면 전환 + 모션 블러, '슉' 효과음) — t, dur, dir, sfx
- subs                              : 디자인 말자막(영상에 넣음). words.json 에서 큐를 만든다(words, line, replace, keywords, one_line)
                                      style: box(기본·현재안) · pill(알약형) · card(밝은 카드형) — 2026-10-14
- illust                            : SVG 일러스트가 외곽선부터 그려지고 색이 찬다(svg_file, x, y, w, full, label) — 2026-10-14
- badge/crumb/def/nametag/ktext/feature/goals/quiz/summary : 이러닝 효과(theme "elearn") — 2026-10-15
                                      subs style "flat"(본고딕·직각·반투명), divider·reframe(board_side:"left") 의 이러닝 모양

확대는 OpenCV 서브픽셀 변환, 표시는 overlay.html(SVG/CSS)을 투명 배경으로 찍어 합성한다.
표시는 확대된 좌표에서 다시 그리므로 선 굵기·글자 크기가 확대 배율과 무관하게 일정하다.

spec 최상위 옵션
  src, out          : 경로. 상대경로면 spec 파일 위치 기준
  t0, t1            : 소스에서 이 구간만 렌더 (생략하면 전체)
  mode              : "burn"(기본, mp4) | "alpha"(표시만 투명 ProRes 4444 .mov — 프리미어 V2 용)
  overlay_fps       : 표시를 몇 fps 로 찍을지 (기본 30. 60fps 소스면 한 장을 두 프레임에 쓴다 → 약 2배 빠름)
  scene_guard       : 기본 true. 월드 좌표 표시는 화면 전환·스크롤 시점에서 자동으로 끝낸다.
                      효과마다 "keep": true 면 가드를 받지 않는다
  theme             : 없으면 기본(코랄·Pretendard). "night" = 나이트 스튜디오(차콜 질감·노란 칩·빨간 주석)
                      "elearn" = 한국 이러닝(밝은 바탕·코랄+네이비·G마켓 산스 제목·본고딕 말자막) — 2026-10-15
"""
import argparse, html, json, math, re, subprocess, sys, time
from pathlib import Path
import av, cv2, numpy as np
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from scenes import cuts as scene_cuts  # noqa: E402
from shorts import FF, ENC_ARGS, pick_encoder
from subtitles import read_vtt

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

W, H = 1920, 1080
WORLD = {"box", "underline", "circle", "check", "spot", "hl", "hand"}
BLUR = {"kinetic", "recap", "chart"}   # 뒤 화면을 흐리는 전체 화면 효과


def ease(x):  # easeInOutCubic
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


def _c(x):
    return min(1.0, max(0.0, x))


CURVES = {"inout": ease, "linear": _c, "out": lambda x: float(np.sin(_c(x) * np.pi / 2)),
          "in": lambda x: float(1 - np.cos(_c(x) * np.pi / 2))}


def zoom_target(box, margin=1.12, max_s=3.0):
    """box 를 16:9 로 넓혀 화면을 채우는 (s, cx, cy). 화면 밖이 보이지 않게 중심을 안으로 민다."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    s = min(W / (w * margin), H / (h * margin), max_s)
    hw, hh = W / (2 * s), H / (2 * s)
    return s, min(max(cx, hw), W - hw), min(max(cy, hh), H - hh)


def board_geom(b):
    """분할 보드: box(원본 영역)를 card 에 맞춰 넣는 배율과 위치. overlay.html 의 boardGeom() 과 같은 식."""
    cx, cy, cw, ch = b.get("card", (96, 190, 1000, 660))
    x, y, w, h = b["box"]
    sc = min(cw / w, ch / h)
    return sc, cx + cw / 2 - (x + w / 2) * sc, cy + ch / 2 - (y + h / 2) * sc


def board_p(b, t):
    d = b.get("ease", .8)
    return ease((t - b["t0"]) / d) if t < b["t0"] + d else (ease((b["t1"] - t) / d) if t > b["t1"] - d else 1.0)


def camera(t, zooms, dur=.7, boards=(), reframes=()):
    ident = (1.0, W / 2, H / 2)
    for r in reframes:                     # 리프레임: 강사(speaker_x)를 to_x 로, 위쪽은 top 만큼 — 화면 밖으로 밀 수 있다(빈 쪽은 보드가 덮음)
        if r["t0"] <= t <= r["t1"]:
            p = reframe_p(r, t)
            s = 1 + (r.get("scale", 1.3) - 1) * p
            sx = r.get("speaker_x", 960)
            scr = sx + (r.get("to_x", 470) - sx) * p
            return s, sx - (scr - W / 2) / s, (H / 2 - r.get("top", -80) * p) / s
    for b in boards:                       # 보드가 확대보다 먼저. 화면 좌표 = 원본 * s + (ox, oy)
        if b["t0"] <= t <= b["t1"]:
            sc, ox, oy = board_geom(b)
            p = board_p(b, t)
            s = 1 + (sc - 1) * p
            return s, (W / 2 - ox * p) / s, (H / 2 - oy * p) / s
    for z in zooms:
        if not z["t0"] <= t <= z["t1"]:
            continue
        tgt = zoom_target(z["box"], z.get("margin", 1.12), z.get("max", 3.0))
        if z.get("rate"):                   # 속도 기반: 초당 rate 만큼 커지다가 목표 배율에서 멈춤 — 사람이 거의 못 느끼게(2026-10-14)
            s = min(tgt[0], 1 + z["rate"] * (t - z["t0"]))
            a = (s - 1) / (tgt[0] - 1) if tgt[0] != 1 else 1
            return s, ident[1] + (tgt[1] - ident[1]) * a, ident[2] + (tgt[2] - ident[2]) * a
        # 들어갈 때(ease_in)와 나올 때(ease_out)를 따로. 0 이면 한 번에 — 2026-10-14
        #   cut:true            → 둘 다 0 (두 번째 카메라처럼 바로 잘라 들어가고 바로 풀림)
        #   ease_in:2.5, ease_out:0 → 천천히 밀고 들어갔다가 다음 컷에서 한 번에 풀림(사용자 선호)
        #   ease_in:"full"      → 구간 전체에 걸쳐 들어간다(끝나는 순간 목표 배율)
        #   curve: inout(기본, 처음·끝 부드럽게) · linear(일정한 속도) · out(바로 움직여 점점 느려짐) · in(점점 빨라짐)
        d = z.get("ease", dur)
        di, do = (0, 0) if z.get("cut") else (z.get("ease_in", d), z.get("ease_out", d))
        if di == "full":
            di = z["t1"] - z["t0"] - (do or 0)
        cv = CURVES.get(z.get("curve", "inout"), ease)
        if di > 0 and t < z["t0"] + di:
            k = cv((t - z["t0"]) / di)
        elif do > 0 and t > z["t1"] - do:
            k = cv((z["t1"] - t) / do)
        else:
            k = 1
        s = float(np.exp(np.log(tgt[0]) * k))          # 배율은 로그 공간에서 보간해야 속도가 고르다
        a = (s - 1) / (tgt[0] - 1) if tgt[0] != 1 else k  # 중심은 배율 진행에 맞춰 이동
        return s, ident[1] + (tgt[1] - ident[1]) * a, ident[2] + (tgt[2] - ident[2]) * a
    return ident


def warp(img, cam):
    s, cx, cy = cam
    if abs(s - 1) < 1e-4:
        return img
    M = np.float32([[s, 0, W / 2 - s * cx], [0, s, H / 2 - s * cy]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def blur_amount(t, fx):
    """kinetic/recap 이 떠 있는 동안 뒤 화면을 흐리는 정도 0~1."""
    k = 0.0
    for e in fx:
        if e["t0"] <= t <= e["t1"]:
            kin = 1.0 if e.get("snap_in") else ease((t - e["t0"]) / .4)
            kout = 1.0 if e.get("snap_out") else ease((e["t1"] - t) / .35)
            k = max(k, min(kin, kout))
    return k


class Broll:
    """B-roll 소스 하나. 영상은 앞에서부터 차례로 읽고(구간 안에서 시간이 뒤로 가지 않으므로), 이미지는 켄번스로 천천히 민다.
    결과는 화면 크기(1920x1080)를 꽉 채우도록 잘라 맞춘다(cover)."""

    def __init__(self, e, base):
        self.e = e
        p = resolve(e["file"], base)
        self.img = None
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            from PIL import Image
            self.img = np.asarray(Image.open(p).convert("RGB"))[:, :, ::-1].copy()
        else:
            self.c = av.open(str(p)); self.s = self.c.streams.video[0]
            off = float(e.get("from", 0))
            if off > 0:
                self.c.seek(int(off / self.s.time_base), stream=self.s)
            self.it = self.c.decode(self.s); self.cur = None; self.cur_t = -1.0; self.off = off

    @staticmethod
    def cover(img, zoom=1.0, ax=.5, ay=.5):
        h, w = img.shape[:2]
        sc = max(W / w, H / h) * zoom
        r = cv2.resize(img, (int(round(w * sc)), int(round(h * sc))), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_CUBIC)
        x0 = int((r.shape[1] - W) * ax); y0 = int((r.shape[0] - H) * ay)
        return r[y0:y0 + H, x0:x0 + W]

    def frame(self, tr):
        e = self.e
        if self.img is not None:                 # 켄번스: 1.0 → 1.0+kb 로 천천히, pan 방향(ax,ay)
            dur = max(e["t1"] - e["t0"], .1)
            kb = e.get("kb", .08); z = 1 + kb * min(1.0, max(0.0, tr / dur))
            return self.cover(self.img, z, *e.get("pan", (.5, .5)))
        target = self.off + tr
        while self.cur_t < target - 1e-3:
            try:
                f = next(self.it)
            except StopIteration:
                break                            # 소스가 짧으면 마지막 프레임에서 멈춘다
            self.cur = f.to_ndarray(format="bgr24"); self.cur_t = float(f.pts * self.s.time_base)
        return self.cover(self.cur) if self.cur is not None else None

    def alpha(self, t):
        e = self.e; fi = e.get("fade_in", .35); fo = e.get("fade_out", .35)
        a = 1.0
        if fi > 0:
            a = min(a, (t - e["t0"]) / fi)
        if fo > 0:
            a = min(a, (e["t1"] - t) / fo)
        return max(0.0, min(1.0, a))


def reframe_p(r, t):
    di, do = r.get("ease_in", 1.2), r.get("ease_out", 0)
    if t < r["t0"] + di:
        return ease((t - r["t0"]) / di)
    if do > 0 and t > r["t1"] - do:
        return ease((r["t1"] - t) / do)
    return 1.0


def _eo(x):  # overlay.html easeOut 과 같은 식
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def apply_pips(img, raw, t, pips):
    """강사 창: 원본 프레임(raw)의 crop 영역을 원형·둥근 사각 창에 실시간으로 넣는다. 테두리는 overlay.html 의 pip 이 그린다.
    등장 크기·투명도는 overlay 의 life(.35,.3)·easeOut 과 같은 식이어야 테두리와 맞는다."""
    for e in pips:
        if not e["t0"] <= t <= e["t1"]:
            continue
        o = 0.0 if (t < e["t0"] or t > e["t1"]) else min(1.0, max(0.0, (e["t1"] - t) / .3))
        k = _eo((t - e["t0"]) / .35) * o
        if k <= 0:
            continue
        sc = .9 + .1 * k
        x0, y0, cw, ch = e["crop"]
        if e.get("shape") == "rect":
            w, h = e["w"] * sc, e["h"] * sc
            X, Y = e["x"] + e["w"] / 2 - w / 2, e["y"] + e["h"] / 2 - h / 2
        else:
            w = h = 2 * e["r"] * sc
            X, Y = e["cx"] - w / 2, e["cy"] - h / 2
        W2, H2 = max(2, int(round(w))), max(2, int(round(h)))
        src = raw[max(0, y0):y0 + ch, max(0, x0):x0 + cw]
        s = max(W2 / src.shape[1], H2 / src.shape[0])
        r_ = cv2.resize(src, (max(W2, int(round(src.shape[1] * s))), max(H2, int(round(src.shape[0] * s)))), interpolation=cv2.INTER_AREA)
        ox, oy = (r_.shape[1] - W2) // 2, (r_.shape[0] - H2) // 2
        patch_ = r_[oy:oy + H2, ox:ox + W2].astype(np.float32)
        yy, xx = np.mgrid[0:H2, 0:W2].astype(np.float32) + .5
        if e.get("shape") == "rect":
            rad = 12.0 * sc
            dx = np.maximum(np.abs(xx - W2 / 2) - (W2 / 2 - rad), 0); dy = np.maximum(np.abs(yy - H2 / 2) - (H2 / 2 - rad), 0)
            m = np.clip(rad - np.sqrt(dx * dx + dy * dy) + .5, 0, 1)
        else:
            rr = W2 / 2
            m = np.clip(rr - np.sqrt((xx - rr) ** 2 + (yy - rr) ** 2) + .5, 0, 1)
        a = (m * k)[:, :, None]
        X0, Y0 = int(round(X)), int(round(Y))
        xa, ya = max(0, X0), max(0, Y0); xb, yb = min(W, X0 + W2), min(H, Y0 + H2)
        if xb <= xa or yb <= ya:
            continue
        reg = img[ya:yb, xa:xb].astype(np.float32)
        pp = patch_[ya - Y0:yb - Y0, xa - X0:xb - X0]; aa = a[ya - Y0:yb - Y0, xa - X0:xb - X0]
        img[ya:yb, xa:xb] = (reg * (1 - aa) + pp * aa).astype(np.uint8)
    return img


def blend(base, rgba):
    a = rgba[:, :, 3:4].astype(np.float32) / 255.0
    if not a.any():
        return base
    return (base.astype(np.float32) * (1 - a) + rgba[:, :, :3].astype(np.float32) * a).astype(np.uint8)


def roi(rgba):
    """투명 레이어에서 그려진 부분의 상자만 잘라 둔다 → (y0, x0, rgb, 알파 0~1). 아무것도 없으면 None."""
    ys, xs = np.nonzero(rgba[:, :, 3])
    if not len(ys):
        return None
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    part = rgba[y0:y1, x0:x1]
    return y0, x0, part[:, :, :3].astype(np.float32), part[:, :, 3:4].astype(np.float32) / 255.0


def blend_roi(base, r):
    """그려진 상자 안만 합성한다. blend() 와 결과가 같고, 화면 전체 부동소수 합성(프레임당 수십 ms)을 피한다."""
    y0, x0, rgb, a = r
    reg = base[y0:y0 + rgb.shape[0], x0:x0 + rgb.shape[1]]
    reg[:] = (reg.astype(np.float32) * (1 - a) + rgb * a).astype(np.uint8)
    return base


def resolve(p, base):
    p = Path(p)
    return p if p.is_absolute() else (base / p).resolve()


def _wrap2(words, L):
    """낱말 목록을 1~2줄로. 한 줄에 들어가면 한 줄, 아니면 아랫줄이 조금 더 긴 쪽으로 균형 있게."""
    txt = " ".join(words)
    if len(txt) <= L + 2 or len(words) < 2:
        return [txt]
    best, bi = 1e9, 1
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        cost = abs(len(a) - len(b)) + (0 if len(b) >= len(a) else 3) + (0 if words[i - 1][-1:] in ",?!" else 2)
        cost += 100 * max(0, len(a) - L - 2) + 100 * max(0, len(b) - L - 2)
        nxt, prv = words[i], words[i - 1]               # 숫자와 단위("천만 / 원이"), 의존명사 앞에서는 끊지 않는다
        if (len(nxt) <= 3 and nxt[:1] in "원명개건배년달시분초수것줄") or prv[-1:].isdigit() or prv in ("몇", "한", "두", "세", "월"):
            cost += 12
        if cost < best:
            best, bi = cost, i
    return [" ".join(words[:bi]), " ".join(words[bi:])]


def load_subs(effects, base):
    """subs 효과: words.json(낱말 시각)에서 말자막 큐를 만든다 — 2026-10-14.
    한 줄 line(22)자, 최대 2줄. 넘치면 낱말 시각으로 쪼갠다(쉼표 뒤 우선). 문장 끝 마침표는 뺀다.
    replace: {"틀린": "맞는"} 은 STT 오인식 교정(근거가 있는 것만, 계획서에 표시된다)."""
    for e in effects:
        if e.get("type") != "subs" or e.get("cues"):
            continue
        if e.get("vtt") and not e.get("words"):
            off = e.get("offset", 0)
            e["cues"] = [dict(s=c["s"]-off, e=c["e"]-off,
                              lines=[html.escape(line) for line in c["text"].splitlines()])
                         for c in read_vtt(resolve(e["vtt"], base))]
            e.setdefault("t0", 0); e.setdefault("t1", 1e9)
            continue
        if not e.get("words"):
            continue
        L = e.get("line", 22); rep = e.get("replace", {})
        d = json.loads(resolve(e["words"], base).read_text(encoding="utf-8"))
        ws = [(w["s"], w["e"], w["w"].strip()) for w in d["words"] if w["w"].strip()]
        segs = d.get("segments") or [{"start": ws[0][0], "end": ws[-1][1]}]
        cues = []
        for sg in segs:
            sw = [w for w in ws if sg["start"] - .05 <= w[0] < sg["end"] - .01]
            # 2줄(2L)에 안 들어가면 k 조각으로 균등하게 — 이상적인 자리 ±8자 안에 문장부호(. , ?)가 있으면 그 뒤에서 자른다
            full = " ".join(x[2] for x in sw)
            per = (L + 2) if e.get("one_line") else (2 * L - 2)      # 한 줄 자막이면 조각 = 한 줄
            k = max(1, -(-len(full) // per))
            ends, acc = [], 0
            for x in sw:
                acc += len(x[2]) + 1; ends.append(acc)
            cuts, last = [], -1
            for j in range(1, k):
                ideal = len(full) * j / k
                cand = [i for i in range(last + 1, len(sw) - 1)]
                if not cand:
                    break
                score = lambda i: abs(ends[i] - ideal) - (8 if sw[i][2][-1:] in ".,?!" else 0)
                i = min(cand, key=score); cuts.append(i); last = i
            chunks, prev = [], 0
            for i in cuts + [len(sw) - 1]:
                chunks.append(sw[prev:i + 1]); prev = i + 1
            chunks = [c for c in chunks if c]
            for ch in chunks:
                words = [x[2] for x in ch]
                txt = " ".join(words)
                for a, b in rep.items():
                    txt = txt.replace(a, b)
                txt = txt[:-1] if txt.endswith(".") else txt
                for kw in e.get("keywords", []):         # 핵심어 강조(스타일마다 노란 글자 / 형광펜) — 큐마다 처음 한 번
                    if kw in txt:
                        txt = txt.replace(kw, f"<mark>{kw}</mark>", 1)
                cues.append({"s": round(ch[0][0], 3), "e": round(ch[-1][1], 3),
                             "lines": [txt] if e.get("one_line") else _wrap2(txt.split(" "), L)})
        for a, b in zip(cues, cues[1:]):                 # 사이가 0.35초 안이면 이어 붙여 깜빡임을 없앤다
            if 0 < b["s"] - a["e"] < .35:
                a["e"] = b["s"]
        off = e.get("offset", 0)                          # spec 의 t0 만큼 당긴다(부분 렌더)
        e["cues"] = [dict(c, s=c["s"] - off, e=c["e"] - off) for c in cues]
        e.setdefault("t0", 0); e.setdefault("t1", 1e9)


def apply_whips(img, t, whips):
    """휩 전환: t 를 가운데로 dur 동안 화면이 dir 쪽으로 휙 밀려나고(가속) 새 장면이 반대쪽에서 밀려 들어온다(감속).
    가운데에서 이동·모션 블러가 가장 커서 장면이 바뀌는 순간이 가려진다. np.roll 이라 빈 곳이 없다."""
    for w in whips:
        d = w.get("dur", .5); a = w["t"] - d / 2
        if not a <= t <= a + d:
            continue
        u = (t - a) / d; sg = -1 if w.get("dir", "left") == "left" else 1
        if u < .5:
            sh = sg * (u / .5) ** 2 * W * .5
        else:
            sh = -sg * (1 - (u - .5) / .5) ** 2 * W * .5
        k = int(w.get("blur", 240) * max(0.0, 1 - abs(u - .5) * 2) ** 1.5) // 2 * 2 + 1
        img = np.roll(img, int(round(sh)), axis=1)
        if k > 2:
            img = cv2.blur(img, (k, 1))
    return img


def whoosh(path, sr=48000, dur=.6, seed=7):
    """'슉' 효과음 — 잡음에 차단 주파수가 올라갔다 내려가는 저역 통과 필터 + 산 모양 볼륨(직접 합성, 외부 소스 아님)."""
    import wave
    rng = np.random.default_rng(seed)
    n = int(sr * dur); x = np.linspace(0, 1, n)
    noise = rng.standard_normal(n)
    fc = 250 + 3800 * np.sin(np.pi * np.clip(x / .9, 0, 1)) ** 2          # 250Hz → 4kHz → 250Hz
    alpha = 1 - np.exp(-2 * np.pi * fc / sr)
    y = np.empty(n); acc = 0.0
    for i in range(n):
        acc += alpha[i] * (noise[i] - acc); y[i] = acc
    env = np.sin(np.pi * np.clip(x, 0, 1)) ** 2 * (1 - .3 * x)
    y = y * env; y = y / (np.abs(y).max() + 1e-9) * .5
    st = np.stack([y * (1 - .35 * x), y * (.65 + .35 * x)], 1)            # 왼→오로 살짝 지나가게
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes((st * 32767).astype("<i2").tobytes())


def mix_sfx(out, times, vol=.55):
    """렌더한 mp4 에 효과음을 times(초) 에 섞는다. 영상은 그대로 복사."""
    if not times:
        return
    tmp = out.with_name(out.stem + "_sfx" + out.suffix); wav = out.with_name("_whoosh.wav")
    whoosh(wav)
    n = len(times)
    fl = f"[1:a]asplit={n}" + "".join(f"[s{i}]" for i in range(n)) + ";" if n > 1 else "[1:a]acopy[s0];"
    for i, tm in enumerate(times):
        ms = max(0, int((tm - .3) * 1000))
        fl += f"[s{i}]adelay={ms}|{ms},volume={vol}[d{i}];"
    fl += "[0:a]" + "".join(f"[d{i}]" for i in range(n)) + f"amix=inputs={n + 1}:normalize=0:duration=first[a]"
    subprocess.run([FF, "-nostdin", "-v", "error", "-y", "-i", str(out), "-i", str(wav), "-filter_complex", fl,
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(tmp)], check=True)
    tmp.replace(out); wav.unlink(missing_ok=True)


def load_svgs(effects, base):
    """illust 의 svg_file 을 읽어 svg 문자열로 넣는다(overlay 는 file:// 을 직접 못 읽으므로)."""
    for e in effects:
        if e.get("svg_file") and not e.get("svg"):
            e["svg"] = resolve(e["svg_file"], base).read_text(encoding="utf-8")


def prepare(spec, base, src):
    fx = [dict(e) for e in spec["effects"] if not e.get("skip")]   # 계획서에서 체크 해제한 효과
    # A top-level subtitle path can be inherited by an explicit subs effect.
    for effect in fx:
        if effect.get("type") == "subs":
            if not effect.get("words") and not effect.get("vtt"):
                for key in ("words", "vtt"):
                    if spec.get(key):
                        effect[key] = spec[key]
            if effect.get("vtt"):
                effect.setdefault("offset", spec.get("t0", 0))
    for e in fx:                                   # 카드 이미지는 file:// 로 넘긴다
        if e.get("img") and not str(e["img"]).startswith(("http", "file:", "data:")):
            e["img"] = resolve(e["img"], base).as_uri()
    load_svgs(fx, base)
    load_subs(fx, base)
    # 휩 전환 가운데(±0.3초)에서 시작·끝나는 효과는 그 순간으로 맞추고 페이드를 없앤다 — 새 장면이 전환 순간에 이미 다 떠 있어야 한다
    for w in [e for e in fx if e["type"] == "whip"]:
        for e in fx:
            if e is w or e["type"] in ("whip", "subs", "zoom"):
                continue
            if abs(e["t0"] - w["t"]) <= .3:
                e["t0"], e["snap_in"] = w["t"], True
            if abs(e["t1"] - w["t"]) <= .3:
                e["t1"], e["snap_out"] = w["t"], True
    zooms = [e for e in fx if e["type"] == "zoom"]
    marks = [e for e in fx if e["type"] != "zoom"]
    if spec.get("scene_guard", True):
        t_off = spec.get("t0", 0)
        cs = [c - t_off for c in scene_cuts(src, start=t_off, end=spec.get("t1"))]
        for e in marks:
            if e["type"] in WORLD and not e.get("keep"):
                nxt = [c for c in cs if e["t0"] + .3 < c < e["t1"]]
                if nxt:
                    print(f"  [가드] {e['type']} {e['t0']}~{e['t1']} → 화면 전환 {nxt[0]}s 에서 끝냄")
                    e["t1"] = nxt[0]
        # 가드가 1.5초도 안 남기면 깜빡임으로 보인다(실측: 0.5초짜리 검색창 네모·동그라미) → 빼고 알린다.
        # 그 대상이 정말 필요하면 spec 에서 시점을 전환 뒤로 옮기거나, 전환 뒤에도 같은 자리면 "keep": true.
        short = [e for e in marks if e["type"] in WORLD and e["t1"] - e["t0"] < 1.5]
        for e in short:
            print(f"  [가드] {e['type']} {e['t0']}~{e['t1']} → 1.5초 미만이라 뺌. spec 시점·keep 을 검토할 것")
        marks = [e for e in marks if e not in short]
    return zooms, marks


def open_page(p, marks, theme=None):
    b = p.chromium.launch(args=["--allow-file-access-from-files"])
    page = b.new_page(viewport={"width": W, "height": H})
    page.goto((HERE / "landscape_overlay.html").resolve().as_uri())
    page.wait_for_load_state("networkidle")
    page.evaluate("t=>setTheme(t)", theme)            # 테마 글꼴까지 받은 뒤에 시작
    page.evaluate("document.fonts.ready")
    page.evaluate("list=>setEffects(list)", marks)
    return b, page


def shot(page):
    png = page.screenshot(omit_background=True, type="png")
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    if img.shape[2] == 3:      # 화면 전체를 불투명하게 덮으면(장 지도 등) 크롬이 알파 없는 PNG 를 준다
        img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
    return img


def load(spec_path):
    path = Path(spec_path).resolve()
    spec = json.loads(path.read_text(encoding="utf-8-sig"))
    base = path.parent
    src, out = resolve(spec["src"], base), resolve(spec["out"], base)
    if src == out:
        raise ValueError("출력 경로는 원본과 달라야 합니다.")
    with av.open(str(src)) as cin:
        vs = cin.streams.video[0]
        duration = float(vs.duration * vs.time_base) if vs.duration is not None else float(cin.duration / av.time_base)
    start, end = float(spec.get("t0", 0)), float(spec.get("t1", duration))
    if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= duration + .05:
        raise ValueError(f"잘못된 구간: {start}~{end}; 원본 {duration:.2f}초")
    if end - start > 30.001:
        raise ValueError("핸즈온 결과물은 30초 이하입니다. t0/t1 구간을 줄여 주세요.")
    if spec.get("theme") not in ("night", "elearn"):
        raise ValueError("가로 양식 theme 은 night 또는 elearn 입니다.")
    if not isinstance(spec.get("effects"), list):
        raise ValueError("effects 목록이 필요합니다.")
    if spec.get("mode", "burn") not in ("burn", "alpha"):
        raise ValueError("mode 는 burn 또는 alpha 입니다.")
    if out.exists() and out.samefile(src):
        raise ValueError("출력 파일이 원본과 같습니다.")
    spec["t0"], spec["t1"] = start, end
    return spec, base, src, out


def preview(spec_path, at=None):
    """승인 전 정지 이미지. --at 은 t0 기준 상대 초이며 영상은 만들지 않는다."""
    spec, base, src, out = load(spec_path)
    zooms, marks = prepare(spec, base, src)
    duration = spec["t1"] - spec["t0"]
    if at is None:
        times = sorted(set(min(duration - .001, max(0, (float(e.get("t0", 0)) + float(e.get("t1", duration))) / 2))
                           for e in marks))[:8] or [duration / 2]
    else:
        times = at
    if not times or not all(math.isfinite(t) and 0 <= t < duration for t in times):
        raise ValueError("--at 은 출력 구간 안의 상대 초여야 합니다.")
    boards = [e for e in marks if e["type"] == "board"]
    reframes = [e for e in marks if e["type"] == "reframe"]
    pips = [e for e in marks if e["type"] == "pip"]
    brolls = [Broll(e, base) for e in marks if e["type"] == "broll"]
    tiles = []
    with sync_playwright() as p, av.open(str(src)) as cin:
        browser, page = open_page(p, marks, spec["theme"])
        try:
            vs = cin.streams.video[0]
            for t in times:
                target = spec["t0"] + t
                cin.seek(int(target / vs.time_base), stream=vs)
                frame = next((fr for fr in cin.decode(vs) if float(fr.pts * vs.time_base) >= target - .02), None)
                if frame is None:
                    raise ValueError(f"프레임을 읽을 수 없습니다: {target}")
                raw = cv2.resize(frame.to_ndarray(format="bgr24"), (W, H))
                cam = camera(t, zooms, boards=boards, reframes=reframes)
                img = warp(raw.copy(), cam)
                blur = blur_amount(t, [e for e in marks if e["type"] in BLUR])
                if blur > .02:
                    img = cv2.GaussianBlur(img, (0, 0), 10 * blur)
                for br in brolls:
                    if br.e["t0"] <= t <= br.e["t1"]:
                        f, a = br.frame(t - br.e["t0"]), br.alpha(t)
                        if f is not None and a > 0:
                            img = cv2.addWeighted(f, a, img, 1-a, 0)
                page.evaluate("([t,c])=>render(t,c)", [t, {"s":cam[0], "cx":cam[1], "cy":cam[2]}])
                img = blend(img, shot(page))
                img = apply_pips(img, raw, t, pips)
                tile = cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA)
                cv2.putText(tile, f"{spec['theme']}  +{t:.2f}s", (12, 345), cv2.FONT_HERSHEY_SIMPLEX, .6, (255,255,255), 2)
                tiles.append(tile)
        finally:
            browser.close()
    sheet = out.with_name(out.stem + "_preview.jpg")
    if sheet == src:
        raise ValueError("미리보기 경로가 원본과 같습니다.")
    sheet.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".jpg", np.vstack(tiles))[1].tofile(str(sheet))
    print(f"미리보기: {sheet} ({len(times)}장 · {duration:.1f}초 구간 · MP4 생성 없음)")
    return sheet


def main(spec_path, plan=None):
    spec, base, src, out = load(spec_path)
    plan_path = resolve(plan, base) if plan else None
    if not plan_path or not plan_path.is_file() or not re.search(r"(?m)^\s*상태\s*:\s*승인\s*$", plan_path.read_text(encoding="utf-8-sig")):
        raise ValueError("렌더 전에 강조계획서 승인이 필요합니다. 상태: 승인인 파일을 --plan 으로 지정하세요.")
    out.parent.mkdir(parents=True, exist_ok=True)
    zooms, marks = prepare(spec, base, src)
    boards = [e for e in marks if e["type"] == "board"]
    reframes = [e for e in marks if e["type"] == "reframe"]
    pips = [e for e in marks if e["type"] == "pip"]
    whips = [e for e in marks if e["type"] == "whip"]
    sfx_times = [w["t"] for w in whips if w.get("sfx", True)] + [e["t0"] + .15 for e in marks if e["type"] == "divider" and e.get("sfx", True)]
    blurs = [e for e in marks if e["type"] in BLUR]
    brolls = [Broll(e, base) for e in marks if e["type"] == "broll"]
    t_start, t_end = spec.get("t0", 0), spec.get("t1")
    alpha = spec.get("mode") == "alpha"
    if alpha and (boards or blurs or brolls):
        print("  [알파] board(화면 줄이기)·kinetic/recap(뒤 흐림)은 영상 자체를 바꾸므로 투명 레이어에 담기지 않는다 — 번인으로 렌더할 것")

    cin = av.open(str(src)); vs = cin.streams.video[0]
    fps = float(vs.average_rate)
    ofps = min(fps, spec.get("overlay_fps", 30))
    if alpha:
        cmd = [FF, "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
               "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-vendor", "apl0", str(out)]
    else:
        cmd = [FF, "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
               "-ss", str(t_start), *(["-t", str(t_end - t_start)] if t_end else []), "-i", str(src),
               "-map", "0:v", "-map", "1:a?", *ENC_ARGS[pick_encoder()], "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    blank = np.zeros((H, W, 4), np.uint8)

    t0c = time.time(); n = shots = 0; cache_key, cache, cache_roi, cache_dom = None, None, None, None
    with sync_playwright() as p:
        b, page = open_page(p, marks, spec.get("theme"))
        if t_start:
            cin.seek(int(t_start / vs.time_base), stream=vs)
        for fr in cin.decode(vs):
            t = float(fr.pts * vs.time_base)
            if t < t_start - 1e-6:
                continue
            if t_end and t >= t_end:
                break
            tt = t - t_start
            cam = camera(tt, zooms, boards=boards, reframes=reframes)
            rgba = rgn = None
            if any(e["t0"] <= tt <= e["t1"] for e in marks):
                # 같은 표시 프레임(overlay_fps 기준)·같은 카메라면 이전 촬영을 재사용
                key = (round(tt * ofps), round(cam[0], 4), round(cam[1], 1), round(cam[2], 1))
                if key != cache_key:
                    # 표시는 그려지는 0.5초 남짓만 움직이고 그 뒤로는 멈춰 있다 → 그린 결과(DOM)가 직전과
                    # 같으면 다시 찍지 않는다. (실측 1-1: 촬영 3,966장 → 534장, 결과 프레임은 완전히 같음)
                    k, dom = page.evaluate(
                        "([t,c])=>{const n=render(t,c);return [n,document.getElementById('stage').innerHTML]}",
                        [key[0] / ofps, {"s": cam[0], "cx": cam[1], "cy": cam[2]}])
                    if dom != cache_dom:
                        cache = shot(page) if k else None
                        cache_roi = roi(cache) if cache is not None else None
                        cache_dom = dom; shots += 1 if k else 0
                    cache_key = key
                rgba, rgn = cache, cache_roi
            if alpha:
                enc.stdin.write((rgba if rgba is not None else blank).tobytes())
            else:
                raw = cv2.resize(fr.to_ndarray(format="bgr24"), (W, H))
                pip_on = any(e["t0"] <= tt <= e["t1"] for e in pips)
                img = warp(raw.copy() if pip_on else raw, cam)
                k = blur_amount(tt, blurs) if blurs else 0
                if k > .02:
                    img = cv2.GaussianBlur(img, (0, 0), 10 * k)
                for br in brolls:                   # B-roll 은 원본 화면을 덮고, 표시(출처·패널)는 그 위에
                    if br.e["t0"] <= tt <= br.e["t1"]:
                        f = br.frame(tt - br.e["t0"]); a = br.alpha(tt)
                        if f is not None and a > 0:
                            img = f.copy() if a >= 1 else cv2.addWeighted(f, a, img, 1 - a, 0)
                if rgn is not None:
                    img = blend_roi(img, rgn)
                if pip_on:
                    img = apply_pips(img, raw, tt, pips)
                if whips:
                    img = apply_whips(img, tt, whips)
                enc.stdin.write(img.tobytes())
            n += 1
        b.close()
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg 인코딩 실패 — 결과물을 사용하지 마세요.")
    cin.close()
    if not alpha and spec.get("sfx", True):
        mix_sfx(out, sorted(sfx_times), spec.get("sfx_vol", .55))
    print(f"{out.name}: {n} 프레임 · 표시 촬영 {shots} 장 · {time.time() - t0c:.0f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="가로 강의 양식 2종: night / elearn (30초 이하)")
    ap.add_argument("spec")
    ap.add_argument("--preview", action="store_true", help="정지 JPG만 생성")
    ap.add_argument("--at", type=float, nargs="+", help="미리보기 시각(구간 상대 초)")
    ap.add_argument("--plan", help="사람이 승인한 강조계획서 경로(spec 기준)")
    args = ap.parse_args()
    if args.at and not args.preview:
        ap.error("--at 은 --preview 와 함께 사용하세요.")
    preview(args.spec, args.at) if args.preview else main(args.spec, args.plan)
