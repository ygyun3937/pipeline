"""
CLI 기반 RAG 쿼리 테스트 스크립트.
API 서버 없이 직접 파이프라인을 호출하여 질문에 답변을 받는다.

사용법:
    uv run python scripts/query_cli.py "로그인 오류의 원인은?"
    uv run python scripts/query_cli.py --search-only "데이터베이스 연결 오류"
    uv run python scripts/query_cli.py --interactive
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI로 RAG 파이프라인에 질문합니다.",
    )
    parser.add_argument(
        "question",
        type=str,
        nargs="?",
        help="질문 텍스트",
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="LLM 호출 없이 검색 결과만 표시",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="검색 결과 수",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="대화형 모드 (종료: 'exit' 또는 Ctrl+C)",
    )
    return parser.parse_args()


def run_query(pipeline, question: str, search_only: bool, top_k: int | None) -> None:
    """단일 질문을 처리하고 결과를 출력한다."""
    if search_only:
        print(f"\n[검색] '{question}'")
        results = pipeline.search_only(query=question, top_k=top_k)

        if results.is_empty:
            print("  관련 문서를 찾을 수 없습니다.")
            return

        print(f"  {len(results.results)}개 결과:\n")
        for r in results.results:
            print(f"  [{r.rank}] {r.source} (유사도: {r.score:.3f})")
            print(f"      {r.page_content[:200]}...")
            print()
    else:
        print(f"\n[질문] {question}")
        print("  답변 생성 중...\n")

        result = asyncio.run(pipeline.query(question=question, top_k=top_k))

        print(f"[답변]")
        print(result.answer)
        print(f"\n  --- (컨텍스트: {len(result.context_used.results)}개 문서 참조, "
              f"토큰: {result.input_tokens}+{result.output_tokens})")


def main() -> int:
    args = parse_args()

    if not args.question and not args.interactive:
        print("질문을 입력하거나 --interactive 옵션을 사용하세요.")
        print("도움말: uv run python scripts/query_cli.py --help")
        return 1

    try:
        from src.config import get_settings
        from src.logger import setup_logging
        from src.pipeline import IssuePipeline

        settings = get_settings()
        setup_logging(log_level="WARNING")  # CLI에서는 경고 이상만 출력

        print("[Issue Pipeline] 초기화 중...")
        pipeline = IssuePipeline.from_settings(settings)

        stats = pipeline.get_index_stats()
        print(f"  인덱스: {stats['total_chunks']}개 청크 로드됨")

        if args.interactive:
            print("\n대화형 모드 시작 (종료: 'exit' 또는 Ctrl+C)\n")
            while True:
                try:
                    question = input("질문> ").strip()
                    if question.lower() in ("exit", "quit", "종료"):
                        break
                    if not question:
                        continue
                    run_query(pipeline, question, args.search_only, args.top_k)
                except KeyboardInterrupt:
                    print("\n종료합니다.")
                    break
        else:
            run_query(pipeline, args.question, args.search_only, args.top_k)

        return 0

    except Exception as exc:
        print(f"\n[오류] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
