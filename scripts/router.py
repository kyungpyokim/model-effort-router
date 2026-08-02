#!/usr/bin/env python3
"""Difficulty-based model and effort router for Codex, Claude Code, and Antigravity."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

FACTORS = ("scope", "ambiguity", "diagnosis", "design", "risk", "verification")


@dataclass(frozen=True)
class RouteResult:
    platform: str
    level: str
    level_name: str
    score: int
    factors: dict[str, int]
    model: str
    effort: str | None
    hard_floor: str | None
    rationale: list[str]


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def clamp_score(value: int) -> int:
    if value < 0 or value > 2:
        raise ValueError(f"factor score must be 0, 1, or 2; got {value}")
    return value


def keyword_score(task: str) -> tuple[dict[str, int], list[str]]:
    text = task.lower()
    scores = {factor: 0 for factor in FACTORS}
    reasons: list[str] = []

    def hit(patterns: Iterable[str]) -> bool:
        return any(p in text for p in patterns)

    # Scope
    if hit(("multiple modules", "multi-module", "multiple services", "cross-service", "monorepo", "entire system", "전체 시스템", "여러 모듈", "여러 서비스", "전면")):
        scores["scope"] = 2
        reasons.append("scope spans multiple modules or services")
    elif hit(("feature", "endpoint", "component", "module", "api", "기능", "컴포넌트", "모듈", "엔드포인트")):
        scores["scope"] = 1
        reasons.append("scope is a component or module")

    # Ambiguity
    if hit(("unknown", "unclear", "explore", "tradeoff", "investigate why", "not sure", "원인 불명", "모호", "탐색", "어떻게 설계", "왜 그런지")):
        scores["ambiguity"] = 2
        reasons.append("requirements or solution path are exploratory")
    elif hit(("decide", "choose", "recommend", "판단", "선택", "추천")):
        scores["ambiguity"] = 1
        reasons.append("some interpretation is required")

    # Diagnosis
    if hit(("intermittent", "race condition", "deadlock", "memory leak", "root cause", "cannot reproduce", "간헐", "재현 안", "레이스", "데드락", "메모리 누수", "근본 원인")):
        scores["diagnosis"] = 2
        reasons.append("root cause is unknown or intermittent")
    elif hit(("bug", "debug", "error", "failure", "exception", "버그", "디버그", "오류", "실패", "예외")):
        scores["diagnosis"] = 1
        reasons.append("debugging is required")

    # Design
    if hit(("architecture", "protocol", "new design", "migration strategy", "system design", "아키텍처", "프로토콜", "신규 구조", "마이그레이션 전략", "시스템 설계")):
        scores["design"] = 2
        reasons.append("new architecture or protocol decisions are required")
    elif hit(("refactor", "pattern", "redesign", "리팩터", "패턴", "재설계")):
        scores["design"] = 1
        reasons.append("an existing design pattern must be selected or adapted")

    # Risk
    if hit(("security", "authentication", "authorization", "payment", "billing", "production", "data loss", "migration", "보안", "인증", "인가", "결제", "운영", "데이터 손실", "마이그레이션")):
        scores["risk"] = 2
        reasons.append("failure can affect security, money, production, or data")
    elif hit(("deploy", "release", "user-facing", "public api", "배포", "릴리스", "사용자", "공개 api")):
        scores["risk"] = 1
        reasons.append("a user-facing regression is possible")

    # Verification
    if hit(("end-to-end", "e2e", "load test", "regression suite", "integration suite", "migration test", "회귀 테스트", "통합 테스트", "부하 테스트", "마이그레이션 테스트")):
        scores["verification"] = 2
        reasons.append("broad integration or regression validation is needed")
    elif hit(("test", "verify", "validation", "테스트", "검증")):
        scores["verification"] = 1
        reasons.append("focused tests or validation are needed")

    return scores, reasons


def level_for_score(score: int) -> str:
    if score <= 2:
        return "L1"
    if score <= 5:
        return "L2"
    if score <= 8:
        return "L3"
    if score <= 10:
        return "L4"
    return "L5"


def higher_level(a: str, b: str) -> str:
    return a if int(a[1:]) >= int(b[1:]) else b


def apply_hard_floor(task: str, config: dict, level: str) -> tuple[str, str | None]:
    text = task.lower()
    floor = None
    for candidate in ("L4", "L5"):
        for keyword in config.get("hard_floor_keywords", {}).get(candidate, []):
            if keyword.lower() in text:
                floor = candidate if floor is None else higher_level(floor, candidate)
                break
    if floor:
        return higher_level(level, floor), floor
    return level, None


def read_available_models(command: str = "agy") -> list[str]:
    proc = subprocess.run([command, "models"], text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"{command} models failed")
    models: list[str] = []
    for raw in proc.stdout.splitlines():
        line = raw.strip().lstrip("-*• ").strip()
        if line and not line.lower().startswith(("available", "models")):
            models.append(line)
    return models


def choose_antigravity_model(profile: dict, available: list[str] | None) -> str:
    if available:
        for pattern in profile.get("patterns", []):
            regex = re.compile(pattern, re.IGNORECASE)
            for model in available:
                if regex.search(model):
                    return model
    return profile["fallback"]


def route(
    task: str,
    platform: str,
    config: dict,
    explicit_factors: dict[str, int] | None = None,
    explicit_level: str | None = None,
    available_models: list[str] | None = None,
) -> RouteResult:
    if explicit_factors is None:
        factors, rationale = keyword_score(task)
    else:
        factors = {factor: clamp_score(int(explicit_factors.get(factor, 0))) for factor in FACTORS}
        rationale = ["factor scores were provided explicitly"]

    score = sum(factors.values())
    level = level_for_score(score)
    if explicit_level:
        level = higher_level(level, explicit_level.upper())
        rationale.append(f"explicit minimum level {explicit_level.upper()} applied")

    level, hard_floor = apply_hard_floor(task, config, level)
    if hard_floor:
        rationale.append(f"hard floor {hard_floor} applied")

    profile = config["platforms"][platform][level]
    if platform == "antigravity":
        model = choose_antigravity_model(profile, available_models)
        effort = None
    else:
        model = profile["model"]
        effort = profile["effort"]

    return RouteResult(
        platform=platform,
        level=level,
        level_name=config["levels"][level]["name"],
        score=score,
        factors=factors,
        model=model,
        effort=effort,
        hard_floor=hard_floor,
        rationale=rationale or ["no complexity keywords detected"],
    )


def shell_command(result: RouteResult, task: str, interactive: bool) -> list[str]:
    if result.platform == "codex":
        options = ["-m", result.model, "-c", f"model_reasoning_effort={result.effort}"]
        return ["codex", *options, task] if interactive else ["codex", "exec", *options, task]
    if result.platform == "claude-code":
        base = ["claude", "--model", result.model, "--effort", str(result.effort)]
        return base + ([task] if interactive else ["-p", task])
    base = ["agy", "--model", result.model]
    return base + (["--prompt-interactive", task] if interactive else ["--prompt", task])


def default_config_path() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "config" / "model-map.json",
        here.parent / "config" / "model-map.json",
        here.parent.parent.parent / "config" / "model-map.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/model-map.json not found")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", help="Task description to classify")
    parser.add_argument("--platform", choices=("codex", "claude-code", "antigravity"), required=True)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--level", choices=("L1", "L2", "L3", "L4", "L5", "l1", "l2", "l3", "l4", "l5"))
    for factor in FACTORS:
        parser.add_argument(f"--{factor}", type=int, choices=(0, 1, 2))
    parser.add_argument("--detect-antigravity-models", action="store_true")
    parser.add_argument("--available-models-file", type=Path)
    parser.add_argument("--format", choices=("json", "text", "command"), default="text")
    parser.add_argument("--interactive", action="store_true", help="Build an interactive-session command")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    config = load_config(args.config or default_config_path())

    supplied = {factor: getattr(args, factor) for factor in FACTORS}
    explicit_factors = None if all(v is None for v in supplied.values()) else {k: (0 if v is None else v) for k, v in supplied.items()}

    available = None
    if args.available_models_file:
        available = [line.strip() for line in args.available_models_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif args.detect_antigravity_models:
        available = read_available_models()

    result = route(
        task=args.task,
        platform=args.platform,
        config=config,
        explicit_factors=explicit_factors,
        explicit_level=args.level,
        available_models=available,
    )

    if args.format == "json":
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif args.format == "command":
        print(shlex.join(shell_command(result, args.task, args.interactive)))
    else:
        effort = result.effort if result.effort is not None else "embedded in model"
        print(f"{result.level} ({result.level_name}) | score={result.score} | model={result.model} | effort={effort}")
        print("factors: " + ", ".join(f"{k}={v}" for k, v in result.factors.items()))
        print("reason: " + "; ".join(result.rationale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
