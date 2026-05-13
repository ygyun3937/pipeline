"""이슈 제출 웹 폼 라우터.

GET  /submit        — 폼 화면 렌더링
POST /submit        — 폼 제출 처리 → MD 파일 생성 → 인덱싱 → 완료 화면
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.api.dependencies import get_pipeline
from src.logger import get_logger
from src.pipeline import IssuePipeline

logger = get_logger(__name__)

router = APIRouter(prefix="/submit", tags=["submit"])

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---- ID 자동 생성 ----

def _next_issue_id(domain: str, raw_dir: Path) -> str:
    """data/raw/ 기존 파일을 스캔해 다음 이슈 ID를 생성한다."""
    year = date.today().year
    prefix_map = {"battery": "BATTERY", "software": "BUG", "incident": "INCIDENT"}
    prefix = prefix_map.get(domain, "BUG")

    pattern = re.compile(rf"^{prefix}-{year}-(\d+)", re.IGNORECASE)
    max_num = 0
    for f in raw_dir.glob(f"{prefix}-{year}-*.md"):
        m = pattern.match(f.name)
        if m:
            max_num = max(max_num, int(m.group(1)))

    return f"{prefix}-{year}-{max_num + 1:03d}"


# ---- MD 파일 생성 ----

def _render_battery_md(issue_id: str, data: dict) -> str:
    today = date.today().isoformat()
    tags = [t for t in [data["alarm_code"].lower().replace("-", ""), data["test_phase"].lower()] if t]
    tags_str = ", ".join(tags) if tags else ""
    return f"""---
id: {issue_id}
domain: battery
severity: {data["severity"]}
status: {data["status"]}
alarm_code: {data["alarm_code"]}
tags: [{tags_str}]
created_at: {today}
resolved_at: {today if data["status"] == "resolved" else ""}
---

# 이슈 보고서: {data["alarm_code"]} {data["title"]}

## 기본 정보
- **이슈 ID**: {issue_id}
- **알람 코드**: {data["alarm_code"]}
- **발생일시**: {today}
- **심각도**: {data["severity"].capitalize()}
- **테스트 단계**: {data["test_phase"]}
- **채널/유닛**: {data["channel"]}

## 증상
{data["symptom"]}

## 원인 분석
{data["cause"]}

## 조치 방법
{data["action"]}

## 재발 방지 대책
{data["prevention"] or "추후 작성 예정"}
"""


def _render_software_md(issue_id: str, data: dict) -> str:
    today = date.today().isoformat()
    domain_label = "인시던트" if data["domain"] == "incident" else "버그"
    return f"""---
id: {issue_id}
domain: {data["domain"]}
severity: {data["severity"]}
status: {data["status"]}
alarm_code: ""
tags: []
created_at: {today}
resolved_at: {today if data["status"] == "resolved" else ""}
---

# {issue_id}: {data["title"]}

## {domain_label} 기본 정보

| 항목 | 내용 |
|------|------|
| 이슈 ID | {issue_id} |
| 심각도 | {data["severity"].capitalize()} |
| 발생일 | {today} |
| 해결일 | {today if data["status"] == "resolved" else "-"} |
| 영향 범위 | {data["affected_range"] or "-"} |

## 문제 현상
{data["symptom"]}

## 원인 분석
{data["cause"]}

## 해결 방법
{data["action"]}

## 재발 방지 대책
{data["prevention"] or "추후 작성 예정"}
"""


# ---- 라우터 ----

@router.get("", response_class=HTMLResponse)
async def get_submit_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("submit.html", {"request": request, "error": None})


@router.post("", response_class=HTMLResponse)
async def post_submit_form(
    request: Request,
    pipeline: Annotated[IssuePipeline, Depends(get_pipeline)],
    domain: Annotated[str, Form()],
    severity: Annotated[str, Form()],
    title: Annotated[str, Form()],
    symptom: Annotated[str, Form()],
    cause: Annotated[str, Form()],
    action: Annotated[str, Form()],
    prevention: Annotated[str, Form()] = "",
    alarm_code: Annotated[str, Form()] = "",
    channel: Annotated[str, Form()] = "",
    test_phase: Annotated[str, Form()] = "",
    affected_range: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "resolved",
) -> HTMLResponse:
    data = {
        "domain": domain, "severity": severity, "title": title,
        "symptom": symptom, "cause": cause, "action": action,
        "prevention": prevention, "alarm_code": alarm_code,
        "channel": channel, "test_phase": test_phase,
        "affected_range": affected_range, "status": status,
    }

    raw_dir = pipeline._loader.source_dir if hasattr(pipeline, "_loader") else Path("data/raw")
    # pipeline에서 source_dir 접근
    try:
        raw_dir = pipeline._embedder._vectorstore._collection._client._settings.is_persistent and Path("data/raw")
    except Exception:
        pass
    raw_dir = Path("data/raw")

    issue_id = _next_issue_id(domain, raw_dir)
    slug = re.sub(r"[^\w가-힣]", "_", title)[:40].strip("_")
    filename = f"{issue_id}_{slug}.md"
    filepath = raw_dir / filename

    if domain == "battery":
        content = _render_battery_md(issue_id, data)
    else:
        content = _render_software_md(issue_id, data)

    filepath.write_text(content, encoding="utf-8")
    logger.info("이슈 파일 생성: %s", filename)

    # 새 파일만 추가 인덱싱
    indexed = False
    try:
        from src.ingestion.document_loader import DocumentLoader
        from src.ingestion.chunker import DocumentChunker
        loader = DocumentLoader(source_dir=raw_dir)
        docs = loader.load_file(filepath)
        chunker = DocumentChunker()
        chunks = chunker.chunk_documents(docs)
        pipeline._embedder.add_documents(chunks, mode="add")
        indexed = True
        logger.info("인덱싱 완료: %s (%d청크)", filename, len(chunks))
    except Exception as exc:
        logger.error("인덱싱 실패: %s | %s", filename, exc)

    return templates.TemplateResponse("submit_success.html", {
        "request": request,
        "issue_id": issue_id,
        "filename": filename,
        "domain": domain,
        "indexed": indexed,
    })
