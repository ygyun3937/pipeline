"""
배터리 알람 QA 파이프라인 데모 스크립트.

HTTP 서버 없이 파이프라인을 직접 실행하여 결과를 출력한다.

사용법:
    uv run python scripts/demo_alarm.py           # 시나리오 3개 순차 실행
    uv run python scripts/demo_alarm.py --pause   # 시나리오 사이에 Enter 대기

주의: Claude Agent SDK(LLM_BACKEND=claude)는 Claude Code 터미널 밖에서 실행해야 한다.
      Claude Code 내부 실행 시 중첩 세션 오류 발생.
"""
from __future__ import annotations

import argparse
import asyncio

from src.config import get_settings
from src.pipeline import IssuePipeline
from src.qa.test_result_parser import TestResultSet


SCENARIOS = [
    {
        "title": "시나리오 1: OVP-001 과전압 알람",
        "alarm_code": "OVP-001",
        "alarm_message": "CC 충전 중 과전압 감지",
        "voltage": 4.35,
        "unit_id": "CH-02",
        "test_stage": "CC_CHARGE",
        "elapsed_seconds": 4200,
    },
    {
        "title": "시나리오 2: OCP-001 과전류 알람",
        "alarm_code": "OCP-001",
        "alarm_message": "충전 시작 직후 과전류 감지",
        "current": 13.8,
        "unit_id": "CH-01",
        "test_stage": "CC_CHARGE",
        "elapsed_seconds": 12,
    },
    {
        "title": "시나리오 3: OTP-001 과온도 알람",
        "alarm_code": "OTP-001",
        "alarm_message": "충전 중 온도 임계값 초과",
        "temperature": 64.2,
        "unit_id": "CH-07",
        "test_stage": "CC_CHARGE",
        "elapsed_seconds": 2800,
    },
]


def _build_raw_issue(s: dict) -> str:
    lines = [f"알람 코드: {s['alarm_code']}", f"알람 메시지: {s['alarm_message']}"]
    if s.get("unit_id"):
        lines.append(f"채널/유닛: {s['unit_id']}")
    if s.get("test_stage"):
        lines.append(f"테스트 단계: {s['test_stage']}")
    if s.get("elapsed_seconds") is not None:
        lines.append(f"경과 시간: {s['elapsed_seconds']}초")
    meas = []
    if s.get("voltage") is not None:
        meas.append(f"전압 {s['voltage']}V")
    if s.get("current") is not None:
        meas.append(f"전류 {s['current']}A")
    if s.get("temperature") is not None:
        meas.append(f"온도 {s['temperature']}°C")
    if meas:
        lines.append(f"측정값: {', '.join(meas)}")
    return "\n".join(lines)


async def run_demo(pause: bool = False) -> None:
    print("=" * 60)
    print("  배터리 알람 자동 QA 파이프라인 데모")
    print("=" * 60)

    cfg = get_settings()
    print(f"  LLM 백엔드: {cfg.llm_backend}")
    pipeline = IssuePipeline.from_settings(cfg)

    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"\n{'─'*60}")
        print(f"  {scenario['title']}")
        print(f"{'─'*60}")

        raw_issue = _build_raw_issue(scenario)
        print(f"[입력]\n{raw_issue}\n")

        # Stage 1
        print("▶ Stage 1: 이슈 구체화 중...", flush=True)
        elaboration = await pipeline.qa_elaborate(raw_issue)
        print(f"  심각도 추정: {elaboration.severity_estimate}")
        print(f"  구체화 완료 ({len(elaboration.elaborated_spec)}자)\n")

        # Stage 2
        print("▶ Stage 2: 테스트 가능여부 판단 중...", flush=True)
        criteria = pipeline.get_validation_criteria()
        feasibility = await pipeline.qa_assess_feasibility(elaboration, criteria)
        print(f"  판정: {feasibility.verdict}")
        print(f"  점수: {feasibility.score}/5")
        print(f"  권장 테스트: {len(feasibility.recommended_test_cases)}개")
        for tc in feasibility.recommended_test_cases[:3]:
            print(f"    - {tc}")
        if len(feasibility.recommended_test_cases) > 3:
            print(f"    ... 외 {len(feasibility.recommended_test_cases) - 3}개")
        print()

        # Stage 3
        print("▶ Stage 3: QA 리포트 생성 중...", flush=True)
        empty_results = TestResultSet(
            source_filename="alarm_auto",
            format="unknown",
            total=0,
            passed=0,
            failed=0,
            skipped=0,
            test_cases=[],
            raw_content="",
        )
        report = await pipeline.qa_generate_report(elaboration, feasibility, empty_results)
        print(f"  리포트 저장: {report.report_path}")
        print(f"\n{'─'*40}")
        print("[리포트 요약 (앞 600자)]")
        print(report.report_markdown[:600])
        print("...")

        if pause and i < len(SCENARIOS):
            print("\n계속하려면 Enter를 누르세요...", end="", flush=True)
            input()

    print(f"\n{'='*60}")
    print("  데모 완료. 리포트 저장 위치: data/qa_reports/")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="배터리 알람 QA 파이프라인 데모")
    parser.add_argument("--pause", action="store_true", help="시나리오 사이에 Enter 대기")
    args = parser.parse_args()
    asyncio.run(run_demo(pause=args.pause))
