"""
문서 인덱싱 실행 스크립트.

사용법:
    uv run python scripts/index_documents.py
    uv run python scripts/index_documents.py --source-dir ./data/raw --recursive
    uv run python scripts/index_documents.py --help
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.logger import get_logger, setup_logging
from src.pipeline import IssuePipeline

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """커맨드라인 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="이슈 문서를 벡터 DB에 인덱싱합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 기본 경로(data/raw)의 문서 인덱싱
  uv run python scripts/index_documents.py

  # 특정 디렉토리 인덱싱
  uv run python scripts/index_documents.py --source-dir /path/to/docs

  # 하위 디렉토리 포함하여 인덱싱
  uv run python scripts/index_documents.py --recursive
        """,
    )
    parser.add_argument(
        "--source-dir",
        type=str,
        default=None,
        help="인덱싱할 문서 디렉토리 경로 (기본값: 설정파일의 raw_documents_dir)",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        default=False,
        help="하위 디렉토리의 문서도 포함하여 인덱싱",
    )
    parser.add_argument(
        "--mode",
        choices=["add", "update"],
        default="add",
        help="인덱싱 모드: add(중복 스킵) | update(기존 청크 삭제 후 재삽입) [기본값: add]",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="실제 인덱싱 없이 파일 목록만 출력",
    )
    return parser.parse_args()


def main() -> int:
    """
    문서 인덱싱 메인 함수.

    Returns:
        종료 코드 (0: 성공, 1: 실패)
    """
    args = parse_args()

    # 로깅 초기화
    settings = get_settings()
    setup_logging(log_level=settings.log_level, log_format=settings.log_format)

    source_dir = Path(args.source_dir) if args.source_dir else settings.raw_documents_path
    print(f"\n[Issue Pipeline] 문서 인덱싱 시작")
    print(f"  소스 디렉토리: {source_dir}")
    print(f"  하위 디렉토리 포함: {args.recursive}")
    print(f"  인덱싱 모드: {args.mode}")
    print()

    if args.dry_run:
        # dry-run 모드: 실제 처리 없이 파일 목록만 출력
        from src.ingestion.document_loader import SUPPORTED_EXTENSIONS
        pattern = "**/*" if args.recursive else "*"
        files = [
            f for f in source_dir.glob(pattern)
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        print(f"[Dry Run] 처리 예정 파일 ({len(files)}개):")
        for f in sorted(files):
            print(f"  - {f.name}")
        print("\n실제 인덱싱을 실행하려면 --dry-run 옵션을 제거하세요.")
        return 0

    try:
        start_time = time.time()

        # 파이프라인 초기화 및 인덱싱 실행
        pipeline = IssuePipeline.from_settings(settings)
        stats = pipeline.index_documents(
            source_dir=source_dir,
            recursive=args.recursive,
            mode=args.mode,
        )

        elapsed = time.time() - start_time

        # 결과 출력
        print("\n[인덱싱 완료]")
        print(f"  처리된 파일:  {stats['files_processed']}개")
        print(f"  실패한 파일:  {stats['files_failed']}개")
        print(f"  전체 청크:    {stats['chunks_total']}개")
        print(f"  추가된 청크:  {stats['chunks_added']}개")
        print(f"  스킵된 청크:  {stats['chunks_skipped']}개 (중복)")
        print(f"  소요 시간:    {elapsed:.1f}초")

        # 현재 인덱스 통계 출력
        index_stats = pipeline.get_index_stats()
        print(f"\n[현재 인덱스 상태]")
        print(f"  컬렉션: {index_stats['collection_name']}")
        print(f"  총 청크 수: {index_stats['total_chunks']}개")

        if stats["files_failed"] > 0:
            print(f"\n경고: {stats['files_failed']}개 파일 처리에 실패했습니다. 로그를 확인하세요.")
            return 1

        return 0

    except Exception as exc:
        print(f"\n[오류] 인덱싱 실패: {exc}")
        logger.exception("인덱싱 중 예외 발생")
        return 1


if __name__ == "__main__":
    sys.exit(main())
