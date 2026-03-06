"""
QA 검증 기준 로더 모듈.

YAML 형식의 검증 기준 파일을 읽어 ValidationCriteria 객체로 반환한다.
핫리로드(reload) 기능을 지원하여 API 재시작 없이 기준 변경을 반영할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ValidationCriteria:
    """파싱된 QA 검증 기준 객체."""

    reproducibility_required: bool
    measurability_required: bool
    acceptance_criteria_required: bool
    test_scope: str  # "unit" | "integration" | "e2e" | "all"
    automation_required: bool
    manual_acceptable: bool
    custom_rules: list[str]
    raw_yaml: dict[str, Any]  # full parsed dict forwarded to Claude verbatim


class ValidationCriteriaLoader:
    """
    YAML 검증 기준 파일을 로드하고 파싱하는 클래스.

    핫리로드를 지원하므로 API 재시작 없이 기준 변경 사항을 즉시 반영할 수 있다.
    """

    def __init__(self, criteria_path: str | Path) -> None:
        """
        Args:
            criteria_path: 검증 기준 YAML 파일 경로
        """
        self._path = Path(criteria_path)
        logger.info("ValidationCriteriaLoader 초기화: path=%s", self._path)

    def load(self) -> ValidationCriteria:
        """
        YAML 검증 기준 파일을 로드하고 유효성을 검사한다.

        Returns:
            ValidationCriteria 객체

        Raises:
            FileNotFoundError: 검증 기준 파일이 존재하지 않는 경우
            ValueError: 필수 키가 누락된 경우
        """
        if not self._path.exists():
            raise FileNotFoundError(f"검증 기준 파일을 찾을 수 없습니다: {self._path}")

        with open(self._path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 필수 최상위 키 검증
        required_keys = ["reproducibility", "measurability", "acceptance_criteria", "test_scope"]
        missing = [k for k in required_keys if k not in data]
        if missing:
            raise ValueError(f"검증 기준 파일에 필수 키가 없습니다: {missing}")

        repro = data["reproducibility"]
        measur = data["measurability"]
        accept = data["acceptance_criteria"]
        scope = data["test_scope"]

        criteria = ValidationCriteria(
            reproducibility_required=repro.get("required", True),
            measurability_required=measur.get("required", True),
            acceptance_criteria_required=accept.get("required", True),
            test_scope=scope.get("level", "integration"),
            automation_required=scope.get("automation_required", False),
            manual_acceptable=scope.get("manual_acceptable", True),
            custom_rules=data.get("custom_rules", []),
            raw_yaml=data,
        )

        logger.info(
            "검증 기준 로드 완료: test_scope=%s, automation_required=%s",
            criteria.test_scope,
            criteria.automation_required,
        )
        return criteria

    def reload(self) -> ValidationCriteria:
        """
        파일을 다시 읽어 ValidationCriteria를 반환한다 (핫리로드).

        API 재시작 없이 변경 사항을 즉시 반영할 때 사용한다.

        Returns:
            새로 로드된 ValidationCriteria 객체
        """
        logger.info("검증 기준 핫리로드: path=%s", self._path)
        return self.load()

    def to_yaml_text(self) -> str:
        """
        원본 YAML 파일 내용을 문자열로 반환한다.

        Claude 프롬프트에 검증 기준을 직접 삽입할 때 사용한다.

        Returns:
            YAML 파일의 원본 텍스트. 파일이 없으면 빈 문자열 반환.
        """
        if not self._path.exists():
            logger.warning("검증 기준 파일 없음, 빈 문자열 반환: path=%s", self._path)
            return ""
        return self._path.read_text(encoding="utf-8")
