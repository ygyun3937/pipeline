"""
장비 제어 데모 스크립트

실행 전 준비:
  터미널 1: uv run python scripts/start_server.py --reload
  터미널 2: uv run python -m src.agent.main          # Mock 에이전트 (포트 8081)
  터미널 3: SIMULATE_ANOMALY=true AGENT_DEVICE_ID=MOCK-02 AGENT_PORT=8082 \
            uv run python -m src.agent.main           # 이상감지 시뮬레이터

실행:
  uv run python scripts/demo_equipment.py
"""

from __future__ import annotations

import time

import httpx

BASE = "http://localhost:8000/api/v1/equipment"


def _req(method: str, path: str, **kwargs) -> dict:
    url = f"{BASE}{path}"
    resp = httpx.request(method, url, **kwargs)
    try:
        data = resp.json()
    except Exception:
        data = {}
    status = "✓" if resp.is_success else "✗"
    print(f"  {status} {method} {path} → {resp.status_code}")
    if not resp.is_success:
        print(f"    detail: {data.get('detail', data)}")
    return data


def register_devices() -> None:
    print("\n[1] 장비 등록")
    _req("POST", "/devices", json={
        "id": "MOCK-01",
        "name": "Mock 충방전기 A",
        "ip_address": "127.0.0.1",
        "port": 8081,
        "device_type": "charger",
    })
    _req("POST", "/devices", json={
        "id": "MOCK-02",
        "name": "Mock 충방전기 B (이상감지용)",
        "ip_address": "127.0.0.1",
        "port": 8082,
        "device_type": "charger",
    })


def create_sequences() -> list[str]:
    print("\n[2] 시퀀스 생성")
    ids = []

    seq1 = _req("POST", "/sequences", json={
        "name": "CC 충전 테스트",
        "steps": [
            {"device_id": "MOCK-01", "command_type": "charge", "params": {"current": 1.0}, "timeout_seconds": 30},
            {"device_id": "MOCK-01", "command_type": "measure", "params": {}, "timeout_seconds": 10},
        ],
    })
    if "id" in seq1:
        ids.append(seq1["id"])
        print(f"    ID: {seq1['id']}")

    seq2 = _req("POST", "/sequences", json={
        "name": "방전 후 측정",
        "steps": [
            {"device_id": "MOCK-01", "command_type": "discharge", "params": {"current": 1.0}, "timeout_seconds": 30},
            {"device_id": "MOCK-01", "command_type": "measure", "params": {}, "timeout_seconds": 10},
            {"device_id": "MOCK-01", "command_type": "reset", "params": {}, "timeout_seconds": 10},
        ],
    })
    if "id" in seq2:
        ids.append(seq2["id"])
        print(f"    ID: {seq2['id']}")

    return ids


def request_execute(seq_ids: list[str]) -> None:
    print("\n[3] 실행 요청 (→ 승인 대기 상태로 전환)")
    for sid in seq_ids:
        data = _req("POST", f"/sequences/{sid}/execute")
        print(f"    {sid[:8]}… → {data.get('status')}")


def show_pending_approval() -> list[str]:
    print("\n[4] 승인 대기 목록 확인")
    seqs = httpx.get(f"{BASE}/sequences").json()
    pending = [s for s in seqs if s["status"] == "pending_approval"]
    for s in pending:
        print(f"    {s['id'][:8]}… [{s['name']}] → {s['status']}")
    return [s["id"] for s in pending]


def approve_all(pending_ids: list[str]) -> None:
    print("\n[5] 승인 (→ 실행 시작)")
    for sid in pending_ids:
        data = _req("POST", f"/sequences/{sid}/approve")
        print(f"    {sid[:8]}… → {data.get('status')}")


def simulate_anomaly() -> None:
    print("\n[6] 이상 감지 시뮬레이션 (MOCK-01 온도 초과 하트비트)")
    resp = httpx.post(f"{BASE}/devices/MOCK-01/heartbeat", json={
        "device_id": "MOCK-01",
        "status": "running",
        "temperature": 52.5,   # warning: >45, critical: >55
        "voltage": 4.18,
        "current": 1.0,
    })
    print(f"  {'✓' if resp.is_success else '✗'} heartbeat → {resp.status_code}")
    print("    → 이상 로그에 기록됨. RAG 분석은 백그라운드에서 실행됩니다.")


def check_anomalies() -> None:
    print("\n[7] 이상 감지 내역 조회")
    anomalies = httpx.get(f"{BASE}/anomalies").json()
    if not anomalies:
        print("  (이상 없음)")
        return
    for a in anomalies:
        rag_preview = (a["rag_analysis"] or "")[:80]
        rag_tag = f" | RAG: {rag_preview}…" if rag_preview else " | RAG 분석 대기 중"
        print(f"  [{a['severity'].upper()}] {a['device_id']} {a['metric']}={a['value']:.2f} (임계값 {a['threshold']:.2f}){rag_tag}")


def main() -> None:
    print("=" * 60)
    print("  장비 제어 데모 — 승인 플로우 + 이상 감지")
    print("=" * 60)
    print("  대시보드: http://localhost:8000/equipment")

    # 서버 연결 확인
    try:
        httpx.get("http://localhost:8000/health", timeout=3)
    except Exception:
        print("\n[!] 서버가 실행 중이 아닙니다.")
        print("    터미널에서 먼저 실행하세요:")
        print("    uv run python scripts/start_server.py --reload")
        return

    register_devices()
    seq_ids = create_sequences()

    if not seq_ids:
        print("\n[!] 시퀀스 생성 실패. 서버 상태를 확인하세요.")
        return

    request_execute(seq_ids)

    pending = show_pending_approval()
    if pending:
        input("\n  → 대시보드(http://localhost:8000/equipment)에서 [승인] 버튼을 확인하세요.\n    Enter를 누르면 스크립트에서 자동 승인합니다...")
        approve_all(pending)
    else:
        print("  (승인 대기 항목 없음)")

    time.sleep(1)

    simulate_anomaly()
    time.sleep(1)

    check_anomalies()

    print("\n" + "=" * 60)
    print("  완료! 대시보드에서 실시간으로 확인하세요.")
    print("  http://localhost:8000/equipment")
    print("=" * 60)


if __name__ == "__main__":
    main()
