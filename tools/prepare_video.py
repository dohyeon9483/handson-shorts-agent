"""영상만 있어도 실습 준비: 메타데이터·대표 프레임·필요시 STT를 work/에 만든다."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import av
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def prepare(src, transcribe=False, model="small", gpu=False):
    src = Path(src).resolve()
    if not src.is_file():
        raise ValueError(f"영상이 없습니다: {src}")
    key = hashlib.sha256(str(src).encode()).hexdigest()[:8]
    dest = ROOT / "work" / "sources" / f"{src.stem}_{key}"
    dest.mkdir(parents=True, exist_ok=True)
    with av.open(str(src)) as c:
        vs = c.streams.video[0]
        duration = float(vs.duration * vs.time_base) if vs.duration else float(c.duration / av.time_base)
        times = np.linspace(min(1, duration / 4), max(0.01, duration - .2), 6)
        tiles = []
        for t in times:
            c.seek(int(float(t) / vs.time_base), stream=vs)
            fr = next((f for f in c.decode(vs) if float(f.pts * vs.time_base) >= t - .02), None)
            if fr is None:
                continue
            frame = fr.to_ndarray(format="bgr24")
            h, w = frame.shape[:2]
            resized = cv2.resize(frame, (480, max(1, round(h * 480 / w))))
            tile = np.full((300, 480, 3), 30, dtype=np.uint8)
            # Letterbox: preserve arbitrary input aspect ratios.
            ratio = min(480 / w, 270 / h)
            resized = cv2.resize(frame, (round(w * ratio), round(h * ratio)))
            y, x = (270-resized.shape[0])//2, (480-resized.shape[1])//2
            tile[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
            cv2.putText(tile, f"{t:.2f}s", (8, 291), cv2.FONT_HERSHEY_SIMPLEX, .6, (255,255,255), 1)
            tiles.append(tile)
        if not tiles:
            raise ValueError("대표 프레임을 읽지 못했습니다.")
        while len(tiles) < 6:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:6])])
        cv2.imencode(".jpg", sheet)[1].tofile(str(dest / "frames.jpg"))
        meta = {"source": str(src), "duration": duration, "width": vs.width, "height": vs.height,
                "audio": bool(c.streams.audio), "frames": str(dest / "frames.jpg"), "status": "needs_agent_scene_map"}
    existing_words = src.with_suffix(".words.json")
    existing_vtt = src.with_suffix(".vtt")
    words = dest / (src.stem + ".words.json")
    vtt = dest / (src.stem + ".vtt")
    if not existing_vtt.exists() and not vtt.exists() and transcribe:
        if not meta["audio"]:
            raise ValueError("음성 트랙이 없어 받아쓰기를 만들 수 없습니다.")
        cmd = [sys.executable, str(ROOT / "tools/transcribe.py"), str(src), "--out-dir", str(dest), "--model", model]
        subprocess.run(cmd + (["--gpu"] if gpu else []), check=True)
    meta["words"] = str(existing_words) if existing_words.exists() else (str(words) if words.exists() else None)
    meta["vtt"] = str(existing_vtt) if existing_vtt.exists() else (str(vtt) if vtt.exists() else None)
    meta["timing"] = "word" if meta["words"] else ("cue" if meta["vtt"] else "missing")
    (dest / "source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print("에이전트: frames.jpg와 VTT를 읽어 work/에 장면 지도를 작성하세요. STT 표기는 사람 확인 전입니다.")
    if not meta["vtt"]:
        print("받아쓰기 없음: 준비 요청 범위에서 requirements-transcribe.txt를 설치하고 --transcribe로 다시 실행하세요.")
    elif not meta["words"]:
        print("VTT 문장 시각을 그대로 사용합니다. STT와 단어 시각 추정은 하지 않습니다.")
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("--transcribe", action="store_true")
    ap.add_argument("--model", default="small")
    ap.add_argument("--gpu", action="store_true")
    a = ap.parse_args()
    prepare(a.video, a.transcribe, a.model, a.gpu)
