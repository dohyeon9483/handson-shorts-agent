"""화면 전환·스크롤 시점과 특정 픽셀의 상태 변화를 찾는다.

    python scenes.py <video>                       # 화면이 크게 바뀌는 시점 목록
    python scenes.py <video> --pixel 1142,433      # 그 픽셀 색이 바뀌는 시점 (토글 켜짐/꺼짐 등)

화면에 붙는 표시(box·underline·circle·check·spot)는 **화면이 바뀌는 순간 끝나야 한다.**
스크롤 중에 동그라미가 제자리에 남으면 엉뚱한 것을 가리킨다(실측: 5-1 검색 결과 스크롤).
fx.py 가 같은 함수로 자동 가드를 건다. 여기서는 효과를 짤 때 시점을 눈으로 확인하는 데 쓴다.
"""
import argparse
import av
import numpy as np


def cuts(video, thresh=6.0, step=6, roi=(100, 1020, 60, 1900), start=0, end=None):
    """프레임 차이 평균이 thresh 를 넘는 시점(초). 탭 표시줄·작업표시줄은 roi 로 뺀다."""
    c = av.open(str(video)); s = c.streams.video[0]
    if start:
        c.seek(int(start / s.time_base), stream=s)
    y0, y1, x0, x1 = roi
    prev, out = None, []
    for i, fr in enumerate(c.decode(s)):
        if i % step:
            continue
        t = float(fr.pts * s.time_base)
        if t < start:
            continue
        if end is not None and t >= end:
            break
        # 효과 좌표와 같은 1920×1080 기준. 작은 원본도 빈 ROI가 되지 않는다.
        a = fr.reformat(width=1920, height=1080, format="gray").to_ndarray()[y0:y1:4, x0:x1:4].astype(np.int16)
        if prev is not None and np.abs(a - prev).mean() > thresh:
            out.append(round(t, 2))
        prev = a
    c.close()
    return out


def pixel_track(video, x, y):
    """(x, y) 픽셀이 '파란 계열(켜진 토글)'인지의 변화 시점."""
    c = av.open(str(video)); s = c.streams.video[0]
    prev, out = None, []
    for fr in c.decode(s):
        t = float(fr.pts * s.time_base)
        r, g, b = fr.to_ndarray(format="rgb24")[y, x].tolist()
        on = b > 180 and r < 120
        if on != prev:
            out.append((round(t, 2), "ON" if on else "off", (r, g, b)))
            prev = on
    c.close()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--pixel")
    ap.add_argument("--thresh", type=float, default=6.0)
    a = ap.parse_args()
    if a.pixel:
        x, y = map(int, a.pixel.split(","))
        for row in pixel_track(a.video, x, y):
            print(*row)
    else:
        print(cuts(a.video, a.thresh))
