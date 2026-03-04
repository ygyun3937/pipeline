# BUG-2024-042: 결제 API 간헐적 타임아웃 오류

## 버그 기본 정보

| 항목 | 내용 |
|------|------|
| 이슈 ID | BUG-2024-042 |
| 심각도 | High |
| 발생일 | 2024-07-03 |
| 해결일 | 2024-07-10 |
| 담당자 | 이백엔드, 박인프라 |
| 영향 범위 | 결제 요청의 약 15% 타임아웃 (피크 타임 기준) |

## 문제 현상

결제 처리 엔드포인트 `POST /api/v1/payments`에서 피크 타임(18:00~22:00)에
간헐적으로 타임아웃이 발생하며 사용자에게 결제 실패 메시지가 표시되었다.

에러 로그 샘플:
```
2024-07-03 19:23:41 ERROR [payment.service] Payment processing timeout
  transaction_id: txn_8f3k2m9p
  elapsed_ms: 30012
  external_api: payment-gateway.example.com
  status: TIMEOUT

2024-07-03 19:45:12 ERROR [payment.service] Payment processing timeout
  transaction_id: txn_7d2j1n8q
  elapsed_ms: 30005
  external_api: payment-gateway.example.com
  status: TIMEOUT
```

## 원인 분석

### 1차 조사 (2024-07-03 ~ 2024-07-04)

초기 분석 시 외부 결제 게이트웨이의 응답 지연이 의심되었으나,
게이트웨이 측 대시보드에서는 정상 응답 시간(평균 250ms)이 확인되었다.

### 2차 조사 - 실제 원인 파악 (2024-07-05 ~ 2024-07-08)

네트워크 패킷 캡처 분석 결과, 다음 문제가 발견되었다:

**동기 HTTP 클라이언트의 스레드 블로킹**

결제 서비스가 비동기(FastAPI/asyncio) 환경에서 실행되었음에도 불구하고,
외부 결제 게이트웨이 API 호출에 동기 HTTP 클라이언트(`requests` 라이브러리)를 사용하고 있었다.

```python
# 문제가 된 코드 (src/payment/gateway_client.py:78)
import requests  # 동기 클라이언트!

async def call_payment_gateway(payload: dict) -> dict:
    # asyncio 이벤트 루프를 블로킹하는 동기 HTTP 호출
    response = requests.post(
        "https://payment-gateway.example.com/charge",
        json=payload,
        timeout=30,
    )
    return response.json()
```

피크 타임에 동시 요청이 증가할 때, 동기 `requests.post()` 호출이 asyncio 이벤트 루프를 블로킹하여
다른 모든 비동기 태스크도 함께 대기하게 되었다. 이로 인해 30초 타임아웃이 연쇄적으로 발생했다.

### 재현 조건
- 동시 결제 요청 10개 이상
- 외부 게이트웨이 응답 시간 500ms 이상 (네트워크 지연 포함 시 일반적)

## 해결 방법

### 코드 수정 - 비동기 HTTP 클라이언트로 교체

```python
# 수정된 코드 - httpx 비동기 클라이언트 사용
import httpx

# 클라이언트를 재사용하여 연결 풀링 효과 활용
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=5.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)

async def call_payment_gateway(payload: dict) -> dict:
    response = await _http_client.post(
        "https://payment-gateway.example.com/charge",
        json=payload,
    )
    response.raise_for_status()
    return response.json()
```

### 추가 개선 사항

1. **재시도 로직 추가**: 일시적 네트워크 오류에 대한 지수 백오프 재시도
2. **Circuit Breaker 도입**: 연속 실패 5회 시 자동으로 외부 API 호출 차단
3. **타임아웃 분리 설정**: 연결 타임아웃(5s)과 읽기 타임아웃(30s) 별도 관리

## 성능 개선 결과

| 지표 | 수정 전 | 수정 후 |
|------|---------|---------|
| 피크 타임 타임아웃 비율 | 15.3% | 0.02% |
| 평균 결제 처리 시간 | 2,340ms | 310ms |
| p99 결제 처리 시간 | 31,200ms | 890ms |

## 재발 방지 대책

1. **린팅 규칙 추가**: `async def` 함수 내 `requests` 사용 금지 ESLint 규칙 추가
2. **부하 테스트 강화**: 동시 요청 시나리오 포함한 성능 테스트 CI에 추가
3. **개발 가이드라인 업데이트**: "FastAPI 환경에서 반드시 비동기 HTTP 클라이언트 사용" 명시

## 관련 파일

- `src/payment/gateway_client.py`
- `src/payment/service.py`
- `tests/payment/test_gateway_client.py`
- `docs/development-guide.md` (비동기 HTTP 가이드라인 추가)
