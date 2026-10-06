# Model Effort Router

English version: [README.md](README.md)

MER는 개발 요청을 **역할 + 노력 수준**으로 분류하고, 해당 조합을 호스트 모델에 매핑하며, 외부 worker 요청을 실행할 수 있습니다. Main은 대화 컨텍스트를 유지하고, 필요한 단계를 결정하며, 호스트 네이티브 Subagent를 호출하는 일을 계속 담당합니다. MER는 현재 Codex 턴을 변경하지 않습니다. Worker 실행은 검증 기반 노력 수준 승격을 선택할 수 있습니다.

## 라우팅 계약

분류기는 `role`과 `effort`를 반환하며, `confidence`와 `reason_code`는 선택 사항입니다. 역할은 `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, `analysis`입니다. 앞의 네 역할은 실행 모델을 사용하고, 나머지는 추론 모델을 사용합니다. 노력 수준은 `low`, `medium`, `high`, `xhigh`입니다. 독립적인 위험 감지는 안전 민감 검토/설계 요청을 최소 `high`까지 올릴 수 있지만, 역할이나 모델 레인은 변경하지 않습니다.

기본값은 Codex 실행 모델 `gpt-6-luna`, 추론 모델 `gpt-6.1-sol`이며, Claude 실행 모델 `claude-sonnet-5-5`, 추론 모델 `claude-opus-5-5`입니다. 각 호스트/레인에는 설정 가능한 primary, fallback, 지원 effort가 있습니다. MER는 stderr에서 실행 fallback을 추론하지 않으며, worker가 시작되었을 수 있는 경우 재시도하지 않습니다. 명시적인 사전 실행 불가 신호가 있을 때만 fallback을 허용합니다. 분류기 provider는 설정된 다음 분류기로 넘어갈 수 있습니다. 모두 실패하면 CLI 라우팅은 오류를 반환하고, hook은 fail open으로 동작하여 사용자 요청을 막지 않습니다.

## 사용법

```sh
python3 <plugin>/bin/mer route --host codex --json 'Review the authentication changes'
python3 <plugin>/bin/mer route --host codex --role implementation --effort high --json 'Implement the approved design'
python3 <plugin>/bin/mer run --host codex --role test --effort medium 'Run and fix the focused tests'
```

`mer route`는 분류/매핑만 수행합니다. 기본적으로 `mer run`은 worker 요청을 정확히 하나 실행합니다. 추론 역할은 읽기 전용으로 실행됩니다. Antigravity는 분류하고 조언을 제공할 수 있지만, Subagent 격리가 검증되지 않았으므로 worker 실행은 지원되지 않습니다. `mer chat`은 제거되었으므로, route 결과를 사용해 Main이 선택된 Subagent를 호출하도록 요청하십시오. 명시적인 `--role`과 `--effort`는 자동 hook 적합성 판단을 우회하며, 반드시 함께 제공해야 합니다.

실행 후 MER는 worker 전후의 저장소 변경 경로를 비교합니다. 변경이 감지되면 텍스트 출력에는 `door`(`one-way`는 데이터 마이그레이션, 데이터 손실 또는 결제 위험인 경우이고, 그 외에는 `two-way`)와 예상 `blast_radius`(`local` 또는 `broad`), 변경 파일 수 및 최상위 디렉터리 수가 표시됩니다. JSON에는 결과 `risk_flags`와 함께 동일한 값이 `change` 아래에 포함됩니다. Blast radius는 경로 기반 추정치이므로 실제 변경 내용을 검토해 영향을 판단하십시오.

### Low-first worker 실행

```sh
python3 <plugin>/bin/mer run --host codex --role fix --effort low --low-first \
  --verify 'python3 -m unittest discover -s tests' --json 'Fix the approved bug'
```

실행 역할에서 `--low-first`는 고정된 검증 명령이 양의 0이 아닌 코드로 종료된 경우에만 low에서 시작해 medium, high 순서로 승격합니다. high가 실패하면 xhigh를 호출하기 전에 `status: approval_required`로 중지합니다. 사용자가 해당 실행에 대해 xhigh를 명시적으로 승인한 경우에만 `--approve-xhigh`를 전달하십시오. Agent는 이를 설정하기 전에 승인을 받아야 합니다. 설정된 모델은 네 가지 effort를 모두 지원해야 합니다. 각 시도는 같은 workspace에서 새 세션으로 시작하며, 변경 사항을 유지하고 원래 컨텍스트와 이전 실패를 함께 받습니다. Worker 오류, 취소, 검증 시작 실패, 신호 종료 및 timeout은 루프를 중지합니다. `--timeout`은 각 worker 시도를 제한하고, `--verify-timeout`은 각 검사를 제한합니다(기본값 300초).

승인 중지 결과에는 원래 요청과 마지막 실패가 담긴 `continuation_context`가 반환됩니다. 승인 후에는 같은 workspace에서 해당 context를 요청으로 전달하고 `--low-first --role <same-role> --effort xhigh --approve-xhigh --verify <same-command>`를 사용해 xhigh continuation만 실행하십시오. 이 사용량은 별도 실행으로 집계되므로, 전체 작업을 측정할 때 두 기록을 합치십시오. 명시적인 xhigh effort가 없으면 새 invocation은 low에서 시작합니다. 일회성 xhigh 실행에도 `--approve-xhigh`가 필요합니다.

`--verify`는 shell expansion 없이 parent process의 권한과 환경을 사용해 실행되는 명시적인 argv 명령입니다. 작업 시작 전에 의미 있는 완료 검사를 고정하십시오. argv를 수정해도 worker가 편집할 수 있는 테스트를 변조 방지 상태로 만들 수는 없습니다. 검사 출력의 마지막 2,000자는 다음 worker에 전송되고 JSON에도 반환되므로, 그 출력에 secret을 포함하지 마십시오. 영속 route log에는 시도 메타데이터, token 수, 검사 상태/소요 시간만 저장됩니다.

JSON과 route log에는 `first_pass`, `escalation_count`, 그리고 각 시도의 effort, worker 사용량 및 검증 소요 시간이 기록됩니다. `usage`는 보고된 worker token을 합산하고, `usage_missing`은 사용량이 없거나 불완전한 시도의 수를 셉니다. 분류기 사용량은 별도로 기록됩니다. 결정론적 검사는 실행 시간을 늘리지만 router model call은 추가하지 않습니다. 검사 내부의 외부 model call은 측정되지 않으므로 token 수치는 전체 검증 비용이 아닙니다.

탐색적 비교를 위해 `--retry-low`는 medium 전에 동일한 실패 피드백을 사용해 low 재시도를 한 번 추가합니다. 별도로 동일하게 초기화한 workspace에서 일반 low-first와 비교하고, 전체 chain과 사용량을 보고하십시오. 이미 수정된 workspace에서 두 arm을 모두 실행하지 마십시오.

Main은 간결한 Context Packet(`task`, `context`, `decisions`, `constraints`, `relevant_files`, `expected_result`)을 전달해야 합니다. 검토에는 `goal`, `decisions`, `constraints`, `diff`, `verification`만 전달하고, 기본적으로 다른 agent의 private reasoning이나 전체 대화를 전달하지 마십시오. Hook은 이 지침만 제공하며 네이티브 Subagent를 직접 생성하지 않습니다.

## 설정

설정은 저장소 루트의 `.model-effort-router.json` 또는 `~/.config/model-effort-router/config.json`에 JSON으로 작성합니다. 저장소 값이 사용자 값을 덮어씁니다. 기존 사용자 파일은 다시 작성하지 않습니다. 예시:

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "subscription", "fallback": "jev", "timeout_s": 10},
  "models": {
    "codex": {
      "execution": {"primary": "gpt-6-luna", "fallback": "gpt-6.1-sol", "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "gpt-6.1-sol", "fallback": "gpt-6-luna", "efforts": ["low", "medium", "high", "xhigh"]}
    }
  }
}
```

Legacy L1-L5, tier/profile, session, escalation 및 `nimble_jev` 설정은 마이그레이션 안내와 함께 거부됩니다. tier override는 `/router role=<role> effort=<effort>`로 바꾸고, 이전 Main-session 라우팅 workflow는 `mer route`와 Main이 선택한 Subagent 조합으로 바꾸십시오. `nimble_jev`는 제거되었으므로 `nimble`과 `jev` 같은 별도의 classifier fallback을 설정하십시오.

`jev.api_key`는 전역 사용자 설정(`$MER_USER_CONFIG` 또는 `~/.config/model-effort-router/config.json`, `XDG_CONFIG_HOME` 준수)에만 설정하십시오: `{"jev": {"api_key": "your-typesafe-api-key"}}`. 저장소 설정에는 이 credential을 제공할 수 없습니다. 전역 key가 없으면 `TYPESAFE_API_KEY`가 fallback으로 남아 있습니다.

## Runtime 개발

`model_effort_router/`가 공유 runtime source입니다. Plugin에는 host integration만 포함됩니다. 개발 시 `MER_CORE_PATH="$PWD"`를 사용하십시오. 다음 명령으로 설치하고 검증합니다:

```sh
python3 scripts/install_core.py
python3 scripts/install_core.py --check
MER_CORE_PATH="$PWD" python3 -m unittest discover -s tests
```
