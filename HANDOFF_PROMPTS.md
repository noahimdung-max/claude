# 새 세션 이어가기 프롬프트

## 1. 첫 메시지 (컨텍스트 주입) — 이거 먼저 붙여넣기

```
마인크래프트 낚시 매크로 프로젝트 이어서 작업할 거야. 코드 먼저 읽고 시작해.

[프로젝트]
- Windows 마크 낚시 매크로 (커스텀 서버, Shift 미니게임). Python + tkinter, exe 배포.
- 저장소 noahimdung-max/claude, 브랜치 claude/bold-darwin-1zygnn, 소스 minecraft_fishing/
- 파일: fishing_macro.py(Macro 클래스), winapi.py(캡처/입력/PostMessage), common.py(DEFAULTS, 찌/자막/툴팁 검출, 리소스팩),
  app.py(UI), analysis.py(로그 분석), tests/(fakes.py 가짜 화면 + test_*.py), .github/workflows/build-exe.yml, CHANGELOG.md(저장소 루트)
- 현재 최신: v1.8.1 릴리즈됨. v1.8.2(백그라운드 모드 안정화)는 커밋/푸시만 됨, 빌드 안 함.

[작업 규칙]
- 릴리즈: build-exe.yml 을 workflow_dispatch 로 version 입력해서 실행 (mcp__github__actions_run_trigger). push 런은 릴리즈 단계 스킵되니 monitor 할 때 event=workflow_dispatch 만 볼 것.
- 버전별 노트는 CHANGELOG.md 에서 가져옴. 옛 릴리즈는 수정 금지. exe 이름에 버전 포함.
- 커밋 전: python -m pyflakes *.py tests/*.py, python -m unittest discover -s tests (33개, 약 50초)
- 리눅스 샌드박스라 실제 마크/윈도우 테스트 불가. 실제 동작은 내가 준 macro.log 로 판단. 검증 안 된 건 "검증 안 됨"이라고 말해.
- 내가 올린 config.json 에 디스코드 웹훅 URL 있음. 절대 출력/커밋하지 마.

[내 응답 스타일]
한국어, 짧고 결론 먼저, 서론/면책 금지, 모르면 모른다고, 내 접근이 문제면 바로 말해, 코드는 실제 동작하는 것만, 수정은 변경점만 설명.

[핵심 사실 (실서버 로그로 확인됨)]
- 진짜 입질 = 찌 픽셀 수가 0으로 떨어짐. 찌는 입질 아니어도 7~15px 움찔함(→ 0.3초 이상 낮아져야 입질).
- 툴팁 내구도 숫자는 초록색. 서버 미니게임 3.9~5.2초.
- 속도 기반 입질 규칙은 오탐 17번 냈음 → 제거함. 비슷한 민감도 규칙 다시 넣지 마.
- 찌 리소스팩 경로: 26.1+ textures/entity/fishing/fishing_hook.png, 이전 entity/fishing_hook.png. 팩 형식 26.1.2=84, 26.3=97 (위키 검색 기준, 실마크 미검증).
- 백그라운드 모드: WGC 캡처 → 실패 시 PrintWindow, 입력은 PostMessage. 마크 F3+P(창 뒤로 가도 일시정지 안 함) 필요, 최소화 금지, 자동 수리는 일반 모드 전용.
```

## 2. 모드/리소스팩 새로 깐 환경 반영용

```
내 마크 환경이 바뀌었어. 지금 설치된 것: [모드/리소스팩/셰이더/버전 목록 적기]
이것들이 매크로에 미치는 영향 점검해줘:
1) 찌 검출 (셰이더/리소스팩이 찌 색·밝기 바꾸는지 → bobber_mask, find_bobber)
2) 자막(입질 소리 자막) 위치/폰트/크기 (자막 템플릿 매칭)
3) 툴팁 내구도 읽기 (F3+H, 모드 UI가 툴팁을 바꾸는지)
4) 백그라운드 모드 (FPS 제한/Dynamic FPS 계열 모드, 포커스 잃을 때 동작)
확실한 것과 추측을 구분해서 말하고, 코드로 대응 가능한 것만 수정해.
```

## 3. 로그 분석 / 버그 수정

```
첨부한 macro.log 분석해서 원인 찾아줘. analysis.py 의 분석 결과(python analysis.py macro.log) 먼저 보고,
오탐/미탐/못 던짐 구분. 재현 시험을 tests/ 에 추가한 뒤 수정하고, 변경점만 알려줘.
실제 로그와 안 맞는 가짜 시뮬레이션(예: 지터 없는 잔잔한 찌)으로 통과했다고 하지 마.
```

## 4. 릴리즈

```
수정 끝났으면: CHANGELOG.md 에 v<버전> 항목 추가 → 테스트/pyflakes → 커밋·푸시 →
build-exe.yml workflow_dispatch(version=<버전>) → 빌드 끝날 때까지 모니터(workflow_dispatch 런만) →
다운로드 링크와 변경 요약 보고.
```

## 5. 남은 일

- v1.8.2 빌드/릴리즈 (백그라운드 모드: 일시정지 메뉴 감지, WGC 창 위치 추적, 캡처 끊김 재오픈) — 아직 안 함
- 실제 윈도우 검증 대기: v1.8.x 리소스팩 적용 여부, 움찔 규칙의 오탐 감소, 백그라운드 모드 수정 효과
- 선택: left_click_cps 15~20, '다시 던지기 전 대기' 단축으로 사이클 시간 줄이기 (분석 패널로 확인)
- 사용자가 "1." 로 시작한 요청이라 후속 번호 항목이 더 있을 수 있음
