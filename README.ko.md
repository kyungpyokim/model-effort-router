# Model Effort Router (v3.1.0)

[English](README.md) | 한국어

Codex, Claude Code, Antigravity를 위한 크로스 플랫폼 번들로, 코딩 작업(Task)을 분석하여 최적의 모델과 추론 노력도(Effort) 프로필로 라우팅합니다.

세 플랫폼 모두 동일한 2차원 라우팅 축을 공유합니다.
- **`task_type` 축**: `implementation`, `design`, `review`, `local_refactoring`, `architectural_refactoring`
- **`level` (난이도) 축**: `L1` ~ `L5`. 여기에 별도의 **리스크 티어**(`standard` / `elevated` / `critical`)가 있어 고위험 작업의 계획/판단 단계 effort를 끌어올립니다.
- 각 플랫폼별 고유 모델 및 추론 강도에 매핑:
  - **Codex**: luna / terra / sol
  - **Claude Code**: haiku / sonnet / opus
  - **Antigravity**: Flash / Pro / Sonnet Thinking / Opus Thinking

전체 원칙: **중요한 판단에는 상위 모델 토큰을 쓰고, 이미 결정된 작업은 충분한 가장 저렴한 모델로 실행합니다.** Codex는 "Sol이 생각하고 검증하며, Luna와 Terra가 구현한다." Claude Code는 "Opus가 생각하고 검증하며, Haiku와 Sonnet이 구현한다." 자세한 내용은 [실행 역할과 파이프라인](#실행-역할과-파이프라인)을 참고하세요.

---

## 계단식 사전 분류기 (Cascading preflight classifier)

분류기(Classifier)는 난이도를 직접 채점하지 않습니다. 작업에 대한 **16가지 명확한 팩트(Fact)**만을 답변합니다.
(수정 파일 수, 모듈/서비스 경계 초과 여부, 결과/해결책 인지 여부, 새로운 아키텍처 구조 필요 여부, 보안/결제 로직 변경 또는 검토 여부, 보안 도메인, 퍼블릭 API 변경, 영속 데이터 변경, 비가역적 변경, 신뢰 경계(Trust boundary) 변경, 영향 반경(Blast radius), 무음 실패로 인한 중대한 피해 여부)

`scripts/router.py`에 정의된 `DIFFICULTY_RULES`가 이 팩트들을 바탕으로 최종 난이도 레벨을 결정합니다. 일치하는 가장 높은 규칙이 적용되며, 라우트 JSON의 `matched_rules`에 해당 규칙 이름이 기록됩니다.

`unknown`은 난이도나 위험이 아니라 "지금 정보로는 yes/no를 판단할 근거가 부족하다"는 뜻입니다. unknown 팩트는 어떤 규칙에도 일치하지 않고, 레벨·티어·위험 플래그를 올리지 않으며, 더 강한 분류기를 호출하는 근거도 되지 않습니다. 분류기는 플랫폼당 하나의 모델이며, unknown은 다음 순서로 해결합니다.

1. **읽기 전용 조회 최대 1회**: 같은 모델이 아직 unknown인 팩트를 확정하는 데 필요한 부분만 읽고 답합니다. 조회는 unknown이던 팩트만 채우며, 1차 응답이 이미 답한 팩트는 바꾸지 않습니다. `--repo-aware`에서는 1차 분류가 이미 저장소를 읽으므로 두 번째 호출이 없습니다.
2. **사용자에게 질문**: 그래도 남은 unknown(요구사항·의도·컨텍스트 부족)은 사용자에게 묻습니다. 라우트 JSON에 `unresolved_facts`와 `questions`가 담기고, 라우터는 종료 코드 `3`으로 끝나 런처가 멈추며, 터미널에서는 직접 질문합니다. `--answer FACT=VALUE`(반복 가능)로 답하면 아직 unknown인 팩트만 채워집니다. 선택 팩트 `requires_code_understanding`은 조회하지만 질문하지 않으며, unknown이면 저렴한 구현 모델이 유지됩니다.

플랫폼별 분류 모델(에스컬레이션 모델은 없습니다):

- **Codex**: `gpt-5.6-luna` (low)
- **Claude Code**: `claude-sonnet-5` (effort 없음)
- **Antigravity**: `Gemini 3.8 Flash (Medium)`

각 사전 분류는 격리된 임시 디렉토리에서 실행되며 구조화된 JSON(`task_type`, `facts`, `delegability`, `evidence`, `reason`)을 검증한 뒤 프로필을 선택합니다. 읽기 전용인 `design` 및 `review` 작업의 경우 `files_touched`가 `0`으로 처리됩니다. Claude Code 또는 Codex 세션 내에서는 라우트 스킬이 인세션 `difficulty-assessor` 에이전트를 통해 동일한 프롬프트를 실행하고 `--classification-file`로 JSON을 전달합니다. 라우트 스킬은 이 1회 분류에서 저장소를 읽고(`--repo-aware`), `unresolved_facts`가 남으면 다른 모델을 부르는 대신 사용자에게 묻습니다. `--classification-file`의 `{"primary", "lookup"}` 엔벨로프는 같은 모델의 조회 1회를 첫 응답에 합칩니다.

사전 분류 프로세스가 0이 아닌 종료 코드로 끝나면 1회 재시도하며, 타임아웃 발생 시에는 재시도하지 않습니다. 재시도 후에도 실패하거나 실행할 수 없거나 잘못된 JSON을 반환하는 경우:

- 터미널 환경에서는 stderr를 통해 `task_type`과 `level`(또는 `critical`)을 사용자에게 직접 질의하고, 그 답변을 결정론적 매트릭스를 통해 라우팅하여 추측 대신 실제 경로를 도출합니다 (`--no-prompt`로 건너뛰기 가능).
- 비인터랙티브 환경에서는 표준 출력(stdout)에 안전한 기본 경로(`implementation` / `L3` / 안전한 기준 모델)를 출력하고, stderr에 실패 원인을 보고하며 0이 아닌 코드로 종료합니다 (`set -e` 스크립트 실행 중단 지원).

### 기본 사용법

```bash
python3 scripts/router.py --platform codex --format json "여러 서비스의 OAuth 인증 장애를 분석하고 수정"
```

작업 유형을 이미 알고 있는 경우 고정할 수 있으며, 난이도 레벨과 리스크 플래그는 자동으로 분류됩니다.

```bash
python3 scripts/router.py --platform codex --task-type design "결제 데이터 마이그레이션 설계"
```

한 번 분류한 결과를 저장하여 그대로 재실행(Replay)하려면 JSON으로 저장한 뒤 전달합니다.

```bash
python3 scripts/router.py --platform codex --format json "작업" > /tmp/model-effort-route.json
plugins/codex-model-effort-router/bin/codex-route --route-file /tmp/model-effort-route.json
```

결과 JSON에는 `verification.recommended` 및 `verification.skipped` 항목도 포함됩니다. 이 항목들은 이유와 함께 저장소 독립적인 검증 권장 사항을 식별하며, 셸 명령이나 실제 실행 결과가 아닙니다. 선택된 실행기는 권장 검증을 수신하여 적용 가능한 기존 저장소 검증을 선택하고, 각 결과 또는 실행하지 않은 이유를 보고합니다. 라우트 파일 재생(replay) 시에는 이 JSON 안내를 무시하고 저장된 실행 단계만 재사용합니다.

### 체이닝 파이프라인

비대화형 런처(`codex-route`, `claude-route`, `agy-route`) 실행은 `scripts/pipeline.py`를 거칩니다: 계획 -> 구현 -> 결정적 테스트 -> Sol/Opus 통합 리뷰 1회. 모든 코드 변경은 `MODEL_EFFORT_ROUTER_TEST_CMD` 또는 `pipeline.py --test-cmd`로 결정적 검사를 제공해야 하며, 없으면 모델 실행 전에 거부됩니다. `trivial_edit`만 계획과 리뷰를 건너뛰고 테스트는 항상 실행하며, 다른 코드 변경은 `max(level, L2)`의 계획·리뷰 행을 사용합니다. 리뷰 FAIL은 라우트의 구현 모델이 1회 수정하고, 다음 실패는 1회 재계획한 뒤 중단합니다. Claude 구현/수정 단계만 `acceptEdits`로 실행되고 계획/리뷰 단계는 코드를 수정할 수 없습니다. 라우트 파일에는 라우터가 생성한 argv 형태만 허용됩니다. 런처는 단계마다 `phase=...` 한 줄을 남깁니다(`MODEL_EFFORT_ROUTER_VERBOSE=1`이면 명령도 출력). 라우트(누가)와 실행 상태(어디까지, `state.json`)는 분리됩니다. 자세한 내용: `references/routing-policy.md`.

### 라우트 재사용

작업 스레드마다 `MODEL_EFFORT_ROUTER_SESSION=<key>`(또는 `router.py --session <key>`)를 지정하면 첫 작업만 분류해 저장하고, 같은 워크스페이스의 후속 작업은 분류기 호출 없이 그 라우트를 재사용합니다. 워크스페이스 변경, 4시간 경과, 실행 중 재계획/실패, 새 작업의 작업 종류 변경·범위 확대·새 리스크 근거가 있으면 다시 분류합니다. `--no-reuse`는 강제로 새로 분류합니다.

라우트 JSON은 스키마 v7를 출력합니다. 이전 점수 필드 대신 `facts`, `matched_rules`, `unresolved_facts`, `questions`, `evidence`가 사용되며, 레벨 옆에 `risk_tier`(`standard` / `elevated` / `critical`)가 기록됩니다. 또한 `execution_strategy: "direct"`와 `orchestration_eligible`을 분리하여 기록합니다. 오케스트레이션 적격성(`orchestration_eligible`)은 Codex 오케스트레이션 인계 후보일 뿐이며 실행 요청이 아닙니다. `scripts/astra_adapter.py`는 변경되지 않은 오케스트레이션 어댑터로, 호출자가 직접 호출하는 로컬 격리 워커 경계입니다(제공된 라우트 및 매니페스트 다이제스트 검증, 시도별 워커 입력 복사본 재검증, 시도 후 검증된 원본 아티팩트 보존). 직접 v2-v7 라우트 파일 재생 시에는 이 어댑터를 호출하지 않습니다.

`delegability`(위임 가능성)는 난이도 규칙과 독립적입니다.
- `0`: 공유 상태, 순서 의존성, 위험 작업 또는 강하게 결합된 작업
- `1`: 분석은 분리 가능하나 종속성이나 소유권이 결합된 작업
- `2`: 명시적 파일/아티팩트 소유권과 독립 검증 결과를 갖는 독립적 하위 작업

L5 난이도에 `delegability: 2`를 만족하는 안전한 단일 Codex 라우트(critical 티어 제외)만 오케스트레이션 대상이 될 수 있습니다.

### 리스크 정책 (Risk Policy)

리스크 정책은 프롬프트가 아닌 **코드**에 정의되어 있습니다. LLM은 팩트만 분류하고, 규칙은 확인된 고위험 작업의 최소 기준만 보장합니다. "security"라는 키워드만으로는 레벨이 올라가지 않으며, `unknown`은 확인된 위험이 아니라 정보 부족입니다.
- **레벨**은 `L1`~`L5`뿐입니다. **보안, 인증, 권한, 결제** 변경 플래그는 **elevated 티어**(L5 함의)를 강제하고 Autobahn scope guard를 적용합니다.
- **데이터 마이그레이션, 퍼블릭 API 변경** 플래그: 최소 **L4 바닥선** 강제
- **보안 검토(Review-only) 작업**: 플래그 대신 팩트에 의해 바닥선이 결정됩니다.
  - `reviews_security_sensitive_code`가 감지되면 최소 **L4**
  - 치명적인 보안 영역(`security_domain`: payment, crypto, permissions, pii)의 경우 작업 유형과 무관하게 최소 **L5**. bare auth는 L5 바닥선이 없습니다. 확인된 auth 변경은 elevated 티어에, auth 검토는 L4에 도달합니다.
- **`elevated` 티어** (L5): 보안/결제 로직 변경, 신뢰 경계가 바뀌는 치명적 보안 영역, 서비스 간 간헐적 장애, 결과가 열려 있는 서비스 간 새 구조 설계. 계획/판단 단계의 effort를 Codex(Sol)와 Claude Code(Opus)에서는 `xhigh`로 올리고, effort 설정이 없는 Antigravity는 해당 단계를 Claude Opus Thinking으로 교체합니다.
- **`critical` 티어** (L5): `irreversible_or_ledger_or_crypto` = yes(비가역 운영 데이터, 원장 정확성, 신규 암호 설계) 또는 `--critical` 플래그. 같은 단계를 `max`로 올립니다(Antigravity: Claude Opus Thinking). 명시적 yes에서만 발동하며 `unknown`은 발동하지 않습니다.
- 2단계 라우트에서 구현 단계는 매트릭스 프로필을 그대로 유지하고, 계획/리뷰 단계만 상향됩니다. 티어 프로필은 `config/model-map.json`의 `tiers`에 있습니다.
- **결제(payment)**는 금전적 결과로 판단합니다: 돈의 이동, 청구 금액 결정(가격·할인·세금), 승인·매입·취소·환불, 원장·정산 정확성, 금전적 의무 발생. billing/order 모듈에 있을 뿐인 코드나 결제 데이터를 캐싱·조회만 하는 작업은 결제가 아닙니다.
- **권한(permissions)**은 접근 경계를 포함합니다: 테넌트 격리, 고객별 데이터 격리, 고객별 데이터를 담는 캐시 키·네임스페이스.

### Antigravity 모델 자동 탐지

Antigravity 플랫폼의 경우, 계정에 활성화된 모델을 감지하여 명령어를 출력할 수 있습니다.

```bash
python3 scripts/router.py --platform antigravity --detect-antigravity-models --format command "간헐적인 멀티서비스 장애의 근본 원인 분석"
```

`--level`(`L1`~`L5`) 옵션은 분류된 레벨에 대한 최소 하한선으로 동작합니다. `--level` 또는 `--critical` 옵션을 명시적인 `--task-type`과 함께 지정하면 두 축이 모두 고정되므로 사전 분류를 건너뛰고 지정된 레벨을 그대로 사용하며, `--critical`은 L5와 critical 티어로 고정합니다. `--level critical`, `L6`, `L7`은 더 이상 유효하지 않습니다. 폴백 발생 시에는 항상 stderr로 안내됩니다.

---

## 2단계 라우트 (Two-stage routes)

`trivial_edit` Fast Path를 통과한 경우를 제외한 모든 코드 변경(`implementation`, `local_refactoring`, `architectural_refactoring`)은 성공 여부에 따라 체인 형태로 실행되며, 계획·리뷰 판정 모델은 `max(level, L2)`의 플랫폼 행에서 가져옵니다. 예외: 파생된 계획자의 모델과 effort가 구현 모델과 같으면 계획 단계를 넣지 않고 단일 stage로 남습니다(Codex/Claude Code의 L2 `architectural_refactoring`, 그리고 Antigravity의 모든 L2 코드 변경). 이 행들은 review 판정 모델이 구현 모델과 같으므로, reviewer 분리(Phase 3)가 들어오기 전까지 review는 자기 검토(self-review)입니다. `trivial_edit`만 계획과 리뷰를 건너뜁니다.
1. 계획 모델(Codex `sol`, Claude Code `opus`, Antigravity Pro)이 임시 실행 디렉토리에 구조화된 계획 JSON을 작성합니다.
2. 구현 모델(`luna`/`terra` 또는 `sonnet`)이 계획서와 저장소를 읽고 계획의 검증 명령과 함께 구현을 진행합니다. 구현 모델은 새로운 설계 결정을 내리지 않으며, 계획 밖의 문제를 발견하면 멈추고 계획 모델을 위한 에스컬레이션 근거를 반환합니다.

임시 실행 디렉토리는 성공 시 자동 삭제되며, 실패 시에는 분석을 위해 보존됩니다 (`--keep-plan` 옵션으로 강제 보존 가능).

```bash
python3 scripts/router.py --platform codex --task-type architectural_refactoring --level L5 "모듈 경계 재분리" --format command
```

---

## 실행 역할과 파이프라인

계획·설계·검증·리뷰에는 강한 모델을, 구현·수정·테스트에는 저렴한 모델을 씁니다. 모델과 effort는 역할 + 난이도 + 리스크로 결정됩니다. 같은 L4라도 설계/리뷰/검증이면 Sol/Opus, 구현이면 Terra high / Sonnet high로 매핑됩니다. 역할은 기존 task_type에 대응합니다: 설계 = `design`, 리뷰 = `review`, 구현 = `implementation`, `local_refactoring`, `architectural_refactoring`(Fast Path가 아닌 코드 변경에서 `design` 행이 계획하고 `review` 행이 리뷰). 분류 자체는 저렴한 모델이 계속 담당합니다.

```text
요청 -> 분류(저렴) -> 계획 (Fast Path가 아닌 코드 변경, max(level, L2)의 design 행 판단 모델: Sol / Opus)
     -> 구현 (라우트의 구현 모델: Luna / Terra / Haiku / Sonnet)
          새로운 설계 문제 발견? 중단 -> 근거 반환 -> 재계획
     -> 결정적 테스트 (런처, 모델 호출 없음)
     -> Fast Path가 아닌 코드 변경: Sol / Opus 검증+리뷰 1회
          (High, elevated 티어 XHigh, critical 티어 Max)
     -> FAIL: 라우트의 구현 모델이 수정 -> 테스트 -> 다시 리뷰, 다음 실패는 1회 재계획
```

아직 구현되지 않은 계획: 계획된 각 단계와 리뷰 FAIL을 다시 분류해 더 싼/더 강한 수정 모델을 고르는 난이도별 모델 라우팅.

- **계획 난이도와 구현 난이도는 별개입니다.** 전체적으로 어려운 작업(예: 라우터의 보안 hard floor 재설계)은 Sol/Opus가 설계하고, 구현은 매트릭스가 그 레벨에 고른 더 저렴한 모델이 맡습니다(계획된 각 단계를 다시 분류하는 것은 계획 단계). 계획자가 직접 구현할 필요는 없습니다(계획자=구현자인 행 제외).
- **테스트 실행**(pytest, lint, formatter, typecheck, build)은 런처가 모델 호출 없이 직접 수행하고, "요구사항을 만족하는가?"라는 최종 검증은 Sol/Opus 리뷰가 합니다.
- **리뷰는 1회로 합칩니다.** 단계마다 Sol/Opus를 호출하지 않습니다. 단계 1..N을 묶어 테스트를 돌린 뒤, 검증과 코드 리뷰를 합친 Sol/Opus 호출을 한 번만 합니다. 전달 내용은 원 요구사항, 승인된 계획, git diff, 테스트 결과, 핵심 코드뿐이며 세션 전체는 보내지 않습니다.
- **리뷰 FAIL 시** 리뷰어는 직접 고치지 않습니다. 라우트의 구현 모델이 수정하고 다시 리뷰를 받습니다(난이도별 수정 모델은 계획 단계).
- **에스컬레이션은 근거 기반**입니다. 구현 모델이 계획 밖의 문제를 발견하면 멈추고 근거(범위 확대, 아키텍처 변경, 퍼블릭 API 변경, DB 마이그레이션, 보안 경계 변경, 계획과 코드 구조 불일치)를 반환합니다. "어렵다", "확신이 없다"만으로는 유효한 사유가 아닙니다.
- **후속 질문은 저장된 라우트를 재사용**합니다. 작업 유형이 바뀌거나(예: INSPECT -> MODIFY), 범위가 크게 늘거나, 새로운 위험 증거가 나오거나, 승인된 설계를 구현할 수 없다는 사실이 드러날 때만 다시 분류합니다.
- **Effort 상한**: Luna는 Low/Medium/High(Luna High로 부족하면 Luna XHigh가 아니라 Terra로), Terra는 Medium/High, Sol은 High/XHigh/Max. Claude Code는 Haiku(단순), Sonnet(일반~복잡 구현), Opus(계획/설계/검증/리뷰). Luna High와 Sonnet Low는 L2 세분화로만 라우팅됩니다: 단순 구현이지만 기존 코드 이해가 필요하면(`requires_code_understanding` = yes) Luna High / Sonnet Low, 아니면 L2는 Luna Medium / Haiku 그대로입니다.
- **토큰 절약**: Sol/Opus는 판단에만 사용, 코딩은 위임, 검증+리뷰는 상위 모델 1회 호출로 통합, 같은 범위는 재분류하지 않음, 큰 출력을 다시 보내지 않음(요구사항+계획+diff+테스트 결과+핵심 코드만), 단순한 불확실성이 아니라 새로운 증거가 있을 때만 재분류.

전체 규칙과 매트릭스는 [references/routing-policy.md](references/routing-policy.md)를 참고하세요.

---

## 번들 구조 (Bundle layout)

```text
plugins/
  codex-model-effort-router/
  claude-model-effort-router/
  antigravity-model-effort-router/
config/model-map.json
scripts/router.py
scripts/sync_bundle.py
```

---

## 설치 (Install)

현재 사용자 환경에 세 가지 플러그인을 모두 설치합니다.

```bash
python3 scripts/install_plugins.py all --scope user
```

Claude Code 프로젝트 로컬 설치는 `--scope project`를 사용하고, 설치 명령을 미리 확인하려면 `--dry-run`을 사용하세요.

### Codex 라우트 우선 훅 (SessionStart hook)

Codex 플러그인에는 가벼운 `SessionStart` 정책 훅이 포함되어 있습니다. 이 훅은 새로운 실질적 코딩 작업을 시작하기 전에 작업을 먼저 라우팅하도록 안내하지만, 분류기나 워커를 임의로 실행하거나 프롬프트를 거부하지 않습니다. Codex는 설치된 훅 정의에 대해 별도의 신뢰 승인을 요구합니다. 새로운 프로세스에서 확실하게 라우팅을 적용하려면 다음을 실행하세요.

```bash
plugins/codex-model-effort-router/bin/codex-route -- "<작업 내용>"
```

---

## 모델 매핑 커스터마이징

`config/model-map.json`을 수정한 뒤 `python3 scripts/sync_bundle.py`를 실행하여 변경 사항을 각 플러그인 복사본에 동기화합니다.
- **Codex 섹션**: `task_type × level` 매트릭스로 구성되며, 단일 단계 행은 `model` + `effort`를 정의하고 2단계 행은 `stages` 목록을 정의합니다.
- **Antigravity 섹션**: 계정 및 릴리스 채널에 따라 `agy models` 출력이 다를 수 있으므로 순서가 지정된 정규식을 사용합니다.
- 에이전트 TOML 파일에는 특정 모델이 고정되어 있지 않으며, 일반 라우트 실행 시 항상 이 매핑 설정을 기반으로 런타임에 모델과 effort를 결정합니다.

---

## 검증 (Validate)

```bash
python3 scripts/validate_bundle.py
python3 -m unittest discover -s tests -v
```
