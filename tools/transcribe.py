"""내 영상 받아쓰기 — 쇼츠 렌더러가 읽는 .vtt 와 .words.json(낱말 시각)을 만든다. (세미나 뒤 선택)

    pip install -r requirements-transcribe.txt          # 처음 한 번(약 100MB + 모델)
    python tools/transcribe.py media/내영상.mp4           # → media/내영상.vtt, media/내영상.words.json
    python tools/transcribe.py media/내영상.mp4 --model medium   # 더 정확, 더 느림

faster-whisper(Whisper)로 받아 적는다. 기본은 CPU(int8). NVIDIA GPU 가 있으면 --gpu (CUDA 라이브러리가 없어 실패하면 CPU 로 다시).
CPU 기준 small 모델로 2분 영상에 1~3분 걸린다. 처음 실행 때 모델을 내려받는다(small 약 500MB).
받아쓰기는 고유명사(사람 이름·제품명)를 자주 틀린다 — 결과를 읽고 틀린 말을 spec 의 replace 에 넣는다.
"""
import argparse, json, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def ts(t):
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--model", default="small"); ap.add_argument("--lang", default="ko"); ap.add_argument("--gpu", action="store_true", help="NVIDIA GPU 로(실패하면 CPU)")
    a = ap.parse_args()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper 가 없습니다 → pip install -r requirements-transcribe.txt")
    src = Path(a.video)
    if not src.exists():
        sys.exit(f"파일이 없습니다: {src}")
    def run(dev, ct):
        model = WhisperModel(a.model, device=dev, compute_type=ct); print(f"모델 {a.model} · {dev}")
        segs, _ = model.transcribe(str(src), language=a.lang, word_timestamps=True, vad_filter=True,
                                   condition_on_previous_text=False)
        out_segs, words = [], []
        for s in segs:                       # 실제 계산은 여기서 일어난다(GPU 라이브러리 문제도 여기서 난다)
            out_segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text})
            for w in s.words or []:
                if w.word.strip():
                    words.append({"s": round(w.start, 2), "e": round(w.end, 2), "w": w.word.strip()})
            print(f"  {s.start:6.1f}  {s.text.strip()}")
        return out_segs, words

    try:
        out_segs, words = run("cuda", "float16") if a.gpu else run("cpu", "int8")
    except Exception as e:  # noqa: BLE001  NVIDIA 가 있어도 CUDA 라이브러리(cublas 등)가 없으면 여기서 실패 → CPU 로
        if not a.gpu:
            sys.exit(f"받아쓰기 실패: {e}")
        print(f"GPU 로 안 됨({type(e).__name__}) → CPU 로 다시 합니다"); out_segs, words = run("cpu", "int8")
    base = src.with_suffix("")
    Path(f"{base}.words.json").write_text(json.dumps({"clip": src.stem, "segments": out_segs, "words": words}, ensure_ascii=False, indent=1), encoding="utf-8")
    vtt = ["WEBVTT", ""] + [f"{ts(s['start'])} --> {ts(s['end'])}\n{s['text'].strip()}\n" for s in out_segs]
    Path(f"{base}.vtt").write_text("\n".join(vtt), encoding="utf-8")
    print(f"\n완료: {base}.vtt · {base}.words.json  (문장 {len(out_segs)} · 낱말 {len(words)})")
    print("다음: 받아쓰기를 읽고 틀린 고유명사를 확인하세요. 에이전트에게 \"이 영상으로 쇼츠 기획안 3개\" 라고 말하면 됩니다.")


if __name__ == "__main__":
    main()
