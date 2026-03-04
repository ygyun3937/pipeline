"""
FastAPI API 서버 시작 스크립트.

사용법:
    uv run python scripts/start_server.py
    uv run python scripts/start_server.py --port 8080 --reload
    uv run python scripts/start_server.py --help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args() -> argparse.Namespace:
    """커맨드라인 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="Issue Pipeline API 서버를 시작합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 기본 설정으로 서버 시작 (0.0.0.0:8000)
  uv run python scripts/start_server.py

  # 개발 모드 (파일 변경 시 자동 재시작)
  uv run python scripts/start_server.py --reload

  # 커스텀 포트로 시작
  uv run python scripts/start_server.py --port 8080
        """,
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="서버 호스트 (기본값: 설정파일의 api_host)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="서버 포트 (기본값: 설정파일의 api_port)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="개발 모드: 파일 변경 시 자동 재시작 (프로덕션 사용 금지)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="워커 프로세스 수 (기본값: 1, --reload와 함께 사용 불가)",
    )
    return parser.parse_args()


def main() -> None:
    """API 서버 시작 메인 함수."""
    import uvicorn

    args = parse_args()

    from src.config import get_settings
    settings = get_settings()

    host = args.host or settings.api_host
    port = args.port or settings.api_port
    log_level = settings.api_log_level

    print(f"\n[Issue Pipeline API] 서버 시작 중...")
    print(f"  호스트:    {host}:{port}")
    print(f"  리로드:    {args.reload}")
    print(f"  워커 수:   {args.workers if not args.reload else 1}")
    print(f"  API 문서:  http://localhost:{port}/docs")
    print(f"  헬스체크:  http://localhost:{port}/health")
    print()

    uvicorn_kwargs: dict = {
        "app": "src.api.main:app",
        "host": host,
        "port": port,
        "log_level": log_level,
        "reload": args.reload,
    }

    # reload 모드에서는 workers 옵션을 사용할 수 없음
    if not args.reload and args.workers > 1:
        uvicorn_kwargs["workers"] = args.workers

    uvicorn.run(**uvicorn_kwargs)


if __name__ == "__main__":
    main()
