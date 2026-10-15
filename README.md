# 강의 영상으로 쇼츠 만들기 — AI로 날개 피자 핸즈온

2분짜리 강의 영상 하나를 AI 에이전트에게 맡겨 **세로 쇼츠(1080×1920)** 로 만들어 봅니다.
여러분은 코드를 쓰지 않습니다. **기획을 고르고, 결과를 보고, 고쳐 달라고 말하는 것**까지가 여러분 몫입니다.

```
강의 영상(가로) ─▶ 받아쓰기 ─▶ 에이전트가 기획안 3개 ─▶ 고르기 ─▶ 미리보기 ─▶ 렌더 ─▶ "이렇게 고쳐 줘"
```

## 1. 준비 (세미나 전에, 10분)

1. **Python 3.11~3.12** 설치 — [python.org](https://www.python.org/downloads/) (Windows 는 설치 화면에서 *Add python.exe to PATH* 체크)
2. **Claude Code** 데스크톱 앱(또는 터미널) 로그인 — 유료 계정 필요. Codex 도 됩니다.
3. 이 레포를 받습니다: 초록 **Code** 버튼 → *Download ZIP* → 압축 풀기 (git 을 쓰면 `git clone`)
4. 노션 가이드에서 **샘플 묶음(zip)** 을 받아 압축을 풀고 `media/` 폴더에 넣습니다 → [`media/README.md`](media/README.md)
5. 설치 스크립트를 실행합니다 (레포 폴더에서):
   - Windows: `powershell -ExecutionPolicy Bypass -File setup\setup_windows.ps1`
   - Mac: `bash setup/setup_mac.sh`
6. 마지막에 **모두 ✅** 가 나오면 끝. ❌ 가 있으면 화살표(→) 안내대로 고치고 `python tools/check_env.py` 를 다시 실행합니다.

> ffmpeg 는 따로 설치하지 않아도 됩니다(파이썬 패키지에 들어 있음). 크로미움은 설치 스크립트가 받습니다(약 150MB).
> 렌더 중에 글꼴을 인터넷에서 받으므로 와이파이가 필요합니다.

## 2. 실습 (세미나 당일)

Claude Code 에서 **이 폴더를 열고**, 아래 프롬프트를 차례로 보냅니다. 문장은 자유롭게 바꿔도 됩니다 → [`prompts/프롬프트카드.md`](prompts/프롬프트카드.md)

| # | 보낼 말 | 무엇이 일어나나 |
|---|---|---|
| ① | 이 프로젝트는 뭐 하는 곳이야? 너는 어떤 에이전트고, 영상으로 어떤 편집을 할 수 있어? | 에이전트가 영상팀 직무처럼 자기소개 |
| ② | 샘플 영상으로 30초 안쪽 쇼츠를 만들고 싶어. 받아쓰기를 읽고 기획안 3개를 제안해 줘. | 훅·구간·화면 배치가 담긴 기획안 3개 |
| ③ | 2번 안으로 만들어 줘. | spec 작성 → 미리보기 한 장 → 렌더(2~5분) |
| ④ | (결과를 보고) 제목을 더 짧게 / 첫 3초를 더 세게 / 캡컷처럼 효과 넣어 줘 | spec 만 고쳐 다시 렌더 |

결과는 `out/` 폴더에 생깁니다.

## 3. 직접 돌려 보기 (선택)

```bash
python tools/shorts.py media/checkpoints/<체크포인트>.json --preview   # 몇 초 — 구간마다 한 장
python tools/shorts.py media/checkpoints/<체크포인트>.json             # 렌더(약 1~3분)
python tools/shorts.py media/examples/<예시>.json --fps 15             # 예시, 빠르게
```

## 4. 막힐 때

| 증상 | 해결 |
|---|---|
| `python` 을 찾을 수 없음 | Python 설치 때 *Add to PATH* 체크했는지. Mac 은 `python3` |
| `check_env` 에 ❌ | 줄 끝 → 안내대로. 그래도 안 되면 옆 사람과 한 대로 같이 |
| 렌더가 너무 느림 | `--fps 15`, 또는 "구간을 3개로 줄여 줘" |
| 제목 글꼴이 이상함 | 인터넷 연결 확인(글꼴 CDN) |
| 시간이 없음 | `media/checkpoints/` spec 을 렌더해 결과부터 보고 거기서 고치기 |

## 폴더

```
AGENTS.md / CLAUDE.md          에이전트가 읽는 지침(누구인지·규칙)
.claude/skills/shorts-maker/   쇼츠 만드는 절차와 spec 사용법
tools/shorts.py                렌더러(가로 → 세로 쇼츠)    tools/check_env.py  환경 점검
media/                         실습 영상·받아쓰기·예시 spec(노션에서 받기, 레포에는 없음)
work/  out/                    여러분 spec / 결과 영상
```

## 사용 범위

- 샘플 영상은 강사의 동의를 받아 **세미나 실습용으로만** 노션으로 나눕니다(이 레포에는 없음). 영상과 결과물을 외부에 올리지 마세요.
- 효과음은 코드로 직접 합성한 것이고, 글꼴은 상업 이용 가능한 무료 글꼴(Pretendard·G마켓 산스·East Sea Dokdo·Noto Color Emoji)입니다.
- 렌더러는 모두의연구소 강의 영상 제작 작업장의 `lecture-effects` 스킬(2026-10)에서 쇼츠 부분만 떼어 노트북용으로 고친 것입니다.
