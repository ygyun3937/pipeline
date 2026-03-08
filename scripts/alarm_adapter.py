"""
배터리 충방전 장비 알람 어댑터 스크립트.

장비에서 발생하는 알람을 수집하여 POST /api/v1/alarm/ingest 엔드포인트로 전달한다.

사용법:
    # 시뮬레이션 모드 (무한 반복)
    uv run python scripts/alarm_adapter.py --source simulate

    # 시뮬레이션 모드 (10개 알람 전송)
    uv run python scripts/alarm_adapter.py --source simulate --count 10

    # 파일 모드 (JSON)
    uv run python scripts/alarm_adapter.py --source file --input-file data/alarms.json

    # dry-run (API 호출 없이 로그만 출력)
    uv run python scripts/alarm_adapter.py --source simulate --count 3 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

# ---------------------------------------------------------------------------
# 배터리 알람 풀 (simulate 모드)
# ---------------------------------------------------------------------------

BATTERY_ALARM_POOL: list[dict] = [
    {"alarm_code": "OVP-001", "alarm_message": "과전압 감지", "voltage": 4.35, "test_stage": "CC_CHARGE"},
    {"alarm_code": "UVP-001", "alarm_message": "저전압 감지", "voltage": 2.45, "test_stage": "CC_DISCHARGE"},
    {"alarm_code": "OCP-001", "alarm_message": "과전류 감지", "current": 12.5, "test_stage": "CC_CHARGE"},
    {"alarm_code": "OTP-001", "alarm_message": "과온도 감지", "temperature": 62.3, "test_stage": "CC_CHARGE"},
    {"alarm_code": "CELL-BAL-001", "alarm_message": "셀 불균형 감지", "voltage": 3.95, "test_stage": "CV_CHARGE"},
    {"alarm_code": "ISOL-001", "alarm_message": "절연 저항 저하", "test_stage": "CC_DISCHARGE"},
    {"alarm_code": "SOC-ERR-001", "alarm_message": "SOC 추정 오류", "test_stage": "REST"},
    {"alarm_code": "COMM-FAIL-001", "alarm_message": "BMS 통신 장애", "unit_id": "CH-03"},
]

# AlarmPayload에서 허용하는 필드
ALARM_PAYLOAD_FIELDS = {
    "alarm_code",
    "alarm_message",
    "voltage",
    "current",
    "temperature",
    "unit_id",
    "test_stage",
    "elapsed_seconds",
}


# ---------------------------------------------------------------------------
# 알람 로드 함수
# ---------------------------------------------------------------------------


def load_alarms_from_json(content: str) -> list[dict]:
    """JSON 문자열에서 알람 목록을 파싱한다.

    지원 형식:
        - 배열: [{alarm_code, alarm_message, ...}, ...]
        - 딕셔너리: {"alarms": [{...}, ...]}
    """
    data = json.loads(content)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "alarms" in data:
            return data["alarms"]
        # 단일 알람 딕셔너리인 경우
        if "alarm_code" in data and "alarm_message" in data:
            return [data]
    raise ValueError(f"지원하지 않는 JSON 구조: {type(data)}")


def load_alarms_from_csv(content: str) -> list[dict]:
    """CSV 문자열에서 알람 목록을 파싱한다."""
    reader = csv.DictReader(StringIO(content))
    alarms = []
    for row in reader:
        alarm: dict = {}
        for field in ALARM_PAYLOAD_FIELDS:
            if field in row and row[field] not in (None, ""):
                value = row[field]
                # 숫자 타입 변환
                if field in ("voltage", "current", "temperature"):
                    try:
                        alarm[field] = float(value)
                    except (ValueError, TypeError):
                        pass
                elif field == "elapsed_seconds":
                    try:
                        alarm[field] = int(value)
                    except (ValueError, TypeError):
                        pass
                else:
                    alarm[field] = value
        alarms.append(alarm)
    return alarms


def load_alarms_from_file(file_path: str) -> list[dict]:
    """파일 경로에서 알람 목록을 로드한다. JSON 및 CSV를 지원한다."""
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_alarms_from_csv(content)
    # .json 또는 그 외 확장자는 JSON으로 시도
    return load_alarms_from_json(content)


# ---------------------------------------------------------------------------
# 시뮬레이션 알람 생성
# ---------------------------------------------------------------------------


def simulate_alarm() -> dict:
    """배터리 알람 풀에서 무작위로 알람을 선택하여 반환한다."""
    base = random.choice(BATTERY_ALARM_POOL).copy()
    # 필요한 경우 elapsed_seconds를 랜덤하게 추가
    if random.random() < 0.5:
        base["elapsed_seconds"] = random.randint(60, 7200)
    if "unit_id" not in base and random.random() < 0.4:
        base["unit_id"] = f"CH-0{random.randint(1, 8)}"
    return base


# ---------------------------------------------------------------------------
# API 전송
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def send_alarm(
    client: httpx.AsyncClient,
    api_url: str,
    payload: dict,
    dry_run: bool,
) -> None:
    """알람 페이로드를 API 서버로 전송한다."""
    alarm_code = payload.get("alarm_code", "UNKNOWN")
    alarm_message = payload.get("alarm_message", "")
    print(f"[{_now()}] 알람 전송: {alarm_code} ({alarm_message})")

    if dry_run:
        print(f"[{_now()}] [dry-run] API 호출 생략")
        return

    try:
        response = await client.post(
            f"{api_url}/api/v1/alarm/ingest",
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        severity = data.get("severity", "N/A")
        verdict = data.get("verdict", "N/A")
        print(f"[{_now()}] \u2713 QA 완료: 심각도={severity}, 판정={verdict}")
    except httpx.HTTPStatusError as exc:
        print(f"[{_now()}] \u2717 오류: HTTP {exc.response.status_code} - {exc.response.text[:200]}")
    except httpx.ConnectError:
        print(f"[{_now()}] \u2717 오류: Connection refused")
    except httpx.TimeoutException:
        print(f"[{_now()}] \u2717 오류: 요청 시간 초과")
    except Exception as exc:  # noqa: BLE001
        print(f"[{_now()}] \u2717 오류: {exc}")


# ---------------------------------------------------------------------------
# 모드별 실행 함수
# ---------------------------------------------------------------------------


async def run_file_mode(
    api_url: str,
    input_file: str,
    dry_run: bool,
) -> None:
    """파일 모드: JSON/CSV 파일에서 알람을 읽어 순서대로 전송한다."""
    try:
        alarms = load_alarms_from_file(input_file)
    except FileNotFoundError:
        print(f"[{_now()}] 오류: 파일을 찾을 수 없습니다: {input_file}")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"[{_now()}] 오류: 파일 파싱 실패: {exc}")
        return

    total = len(alarms)
    print(f"[{_now()}] 파일 모드 시작: {total}개 알람 로드 ({input_file})")

    success = 0
    failure = 0

    async with httpx.AsyncClient() as client:
        for alarm in alarms:
            try:
                await send_alarm(client, api_url, alarm, dry_run)
                success += 1
            except Exception:  # noqa: BLE001
                failure += 1

    print(f"\n[{_now()}] 완료: 성공 {success}개 / 실패 {failure}개 / 전체 {total}개")


async def run_simulate_mode(
    api_url: str,
    interval: float,
    count: int | None,
    dry_run: bool,
) -> None:
    """시뮬레이션 모드: 랜덤 알람을 생성하여 폴링 방식으로 전송한다."""
    limit_str = str(count) if count is not None else "무한"
    print(f"[{_now()}] 시뮬레이션 모드 시작: 간격={interval}초, 횟수={limit_str}")
    print("Ctrl+C로 종료할 수 있습니다.\n")

    sent = 0
    async with httpx.AsyncClient() as client:
        try:
            while True:
                if count is not None and sent >= count:
                    break
                alarm = simulate_alarm()
                await send_alarm(client, api_url, alarm, dry_run)
                sent += 1
                if count is not None and sent >= count:
                    break
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        except KeyboardInterrupt:
            pass

    print(f"\n[{_now()}] 종료: 총 {sent}개 알람 전송 완료")


# ---------------------------------------------------------------------------
# CLI 인자 파싱
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """커맨드라인 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="배터리 충방전 장비 알람을 QA API로 전달하는 어댑터",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 시뮬레이션 모드 (무한)
  uv run python scripts/alarm_adapter.py --source simulate

  # 시뮬레이션 모드 (5개, 2초 간격)
  uv run python scripts/alarm_adapter.py --source simulate --count 5 --interval 2

  # 파일 모드 (JSON)
  uv run python scripts/alarm_adapter.py --source file --input-file data/alarms.json

  # dry-run (API 호출 없음)
  uv run python scripts/alarm_adapter.py --source simulate --count 3 --dry-run
        """,
    )
    parser.add_argument(
        "--source",
        choices=["file", "simulate"],
        required=True,
        help="알람 소스 (file: JSON/CSV 파일, simulate: 랜덤 시뮬레이션)",
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="QA API 서버 기본 URL (기본값: http://localhost:8000)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="폴링 간격 초 (simulate 모드, 기본값: 5)",
    )
    parser.add_argument(
        "--input-file",
        default=None,
        help="읽을 JSON/CSV 파일 경로 (file 모드 필수)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="전송할 알람 수 제한 (simulate 모드, 기본값: 무한)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="API 호출 없이 로그만 출력",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


async def main(argv: list[str] | None = None) -> None:
    """어댑터 메인 함수."""
    args = parse_args(argv)

    if args.source == "file":
        if not args.input_file:
            print("오류: --source file 모드에서는 --input-file 옵션이 필수입니다.")
            sys.exit(1)
        await run_file_mode(
            api_url=args.api_url,
            input_file=args.input_file,
            dry_run=args.dry_run,
        )
    else:  # simulate
        await run_simulate_mode(
            api_url=args.api_url,
            interval=args.interval,
            count=args.count,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    asyncio.run(main())
