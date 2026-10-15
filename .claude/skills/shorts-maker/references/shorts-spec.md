# 쇼츠 spec 레퍼런스


```jsonc
{
  "src": "../media/<영상>.mp4", "words": "../media/<영상>.words.json", "out": "../out/내쇼츠.mp4",
  "fps": 30, "max_chars": 14,                 // 말자막 한 줄 최대 글자(캡컷식은 11)
  "replace": {"틀린 말": "맞는 말"},          // 사용자가 확정한 교정만 적용
  "sfx_auto": true,                           // 레이아웃이 바뀌는 경계에 '슉'
  "segments": [ { "in": 29.4, "out": 36.6, "layout": "speaker", ... } ]   // 적힌 순서대로 이어 붙는다
}
```

### 구간(segment) 공통
| 키 | 뜻 |
|---|---|
| `in`, `out` | 원본 초 |
| `layout` | `speaker`(강사 크게, 위에 제목) · `split`(위 그래픽, 아래 강사) · `board`(그래픽 + 원형 강사 창) |
| `speaker` | 원본에서 잘라 올 영역. **샘플 영상 기본값 `{"cx":960,"cy":20,"cw":860}`**, 어둡게 깔려면 `"dim":0.3` |
| `split_y` | split 에서 강사가 시작하는 y(기본 900). split 의 speaker 기본값 `{"cx":960,"cy":180,"cw":880}` |
| `pip` | board 의 원형 강사 창. **샘플 영상 기본값 `{"x":650,"y":300,"size":220,"crop":[640,160,640,640]}`** |
| `titles` | `[{t, t1?, chip?, html, size}]` — `t` 는 구간 안 시각. `<mark>` 는 노란 강조, `<br>` 줄바꿈. 2줄·줄당 10자 안팎, size 80~110 |
| `graphic` | `{"type":"doc", title, rows[], hl_at, hand, hand_at}` 정산서(금액 흐림·'예시') / `{"type":"chart", chip, title, values[], colors[], note}` 막대(‘예시’) |
| `cta` | `{"at":0.6, "y":520, "html":"▶ 본편: …"}` 마지막 안내 버튼 |
| `_why` | 근거 메모(렌더는 무시). "[원본초] 그때 한 말" 을 적어 두면 고치기 쉽다 |

### 캡컷식 — 구간에 `"style":"cc"`
| 키 | 뜻 |
|---|---|
| `cap_mode`, `cap_size` | `box`(지금 낱말 초록 상자·튕김) · `karaoke`(말한 낱말까지 노랗게), 80 |
| `titles[].speed` | 제목 둘레 속도선 깜빡임 |
| `focus` | 확대 중심(얼굴). 샘플 영상 `[960,400]` |
| `cam` | `[{t, z, mode:"cut"\|"push", dur}]` — cut 즉시 펀치인(1.15~1.3), push 천천히(1.08~1.12) |
| `shake` | `[{t, dur:0.4, amp:30}]` 흔들림 |
| `post` | `[{type:"glitch"\|"flash", t, dur}]` 화면 전체 |
| `fx` | `emoji{ch,x,y,size,rot}` · `chip{html,emoji,x,y,rot}` 스티커 · `stamp{text:"✕",x,y,size}` · `search{html,y}` · `glitch_text{text,y}` · `label{text,x,y}` · `big{small,html,y}` · `list{items:[{t,text,emoji}],y}` · `odo{value,unit,dur,to_html,to_at,y}` · `subscribe{x,y}` · `arrow{x,y,text}` — 모두 `t`(구간 안 시각), `t1` 선택 |
| `sfx` | `[{t, kind}]` — pop · ppyong(뿅) · ttaeng(땡) · dudung(두둥) · ding · whoosh (전부 직접 합성) |

강한 효과(글리치·두둥)는 반전에 한 번만. 3초 넘게 아무 변화 없는 화면이 없게.

### 세로 화면 배치 규칙(정해진 값)
위 0~288 은 휴대폰 UI 자리(진행 막대만) · 제목 300~580 · 강사 600~맨 아래 · **얼굴 y 890~1230 은 가리지 않는다** ·
말자막은 y 1420 근처 가운데 · 오른쪽 192px 은 버튼 자리라 비운다. fx 의 `x`,`y` 도 이 범위를 지킨다.

## 막힐 때
- `python tools/check_env.py` — 무엇이 빠졌는지 알려 준다. 결과를 보여 주고, 참여자가 준비를 요청했으면 AGENTS.md '실습 준비 요청' 순서로 고친다.
- 렌더가 너무 느리면 `--fps 15`, 또는 구간을 줄인다.
- 급하면 선택한 양식의 spec을 15~20초, 최소 효과로 작성해 미리보기부터 확인한다.
