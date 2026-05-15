"""
구조화된 로깅 설정 모듈.
파이프라인 전체에서 일관된 로그 포맷을 제공한다.
"""

import logging
import sys
from functools import lru_cache


def _configure_handler(log_format: str) -> logging.Handler:
    """로그 핸들러와 포맷터를 구성한다."""
    handler = logging.StreamHandler(sys.stdout)

    if log_format == "json":
        # 간단한 JSON 형태의 로그 포맷
        fmt = (
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"name": "%(name)s", "message": "%(message)s"}'
        )
    else:
        # 사람이 읽기 쉬운 텍스트 포맷
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    return handler


def setup_logging(log_level: str = "INFO", log_format: str = "text") -> None:
    """
    애플리케이션 루트 로거를 설정한다.
    이 함수는 애플리케이션 시작 시 한 번만 호출해야 한다.
    """
    handler = _configure_handler(log_format)

    # 루트 로거 초기화
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 기존 핸들러 제거 후 새 핸들러 추가 (중복 방지)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # 외부 라이브러리 노이즈 억제
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


@lru_cache(maxsize=None)
def get_logger(name: str) -> logging.Logger:
    """
    모듈별 로거를 반환한다.
    동일한 name에 대해 항상 같은 인스턴스를 반환한다 (캐싱).
    """
    return logging.getLogger(name)
