---
id: BUG-2024-001
domain: software
severity: critical
status: resolved
alarm_code: ""
tags: [login, api, 500-error, connection-pool, database]
created_at: 2024-03-15
resolved_at: 2024-03-15
---

# BUG-2024-001: 로그인 API 500 Internal Server Error

## 버그 기본 정보

| 항목 | 내용 |
|------|------|
| 이슈 ID | BUG-2024-001 |
| 심각도 | Critical |
| 발생일 | 2024-03-15 |
| 해결일 | 2024-03-15 |
| 담당자 | 김개발 |
| 영향 범위 | 전체 사용자 로그인 불가 (30분 장애) |

## 문제 현상

2024년 3월 15일 오전 09:15경부터 로그인 API `/api/v1/auth/login`에서
500 Internal Server Error가 반환되기 시작했다.

사용자 신고 로그:
```
POST /api/v1/auth/login HTTP/1.1
Response: 500 Internal Server Error
{"error": "Internal Server Error", "message": "Database connection failed"}
```

## 원인 분석

### 직접 원인
데이터베이스 연결 풀(Connection Pool) 소진으로 인해 새로운 DB 연결 시도 실패.

### 근본 원인
전날(2024-03-14) 배포된 v2.3.1 버전에서 DB 쿼리 최적화 작업 중 실수로
`connection.close()` 호출이 누락된 코드가 포함되었다.

```python
# 문제가 된 코드 (src/auth/service.py:142)
def validate_user_token(token: str) -> bool:
    connection = db_pool.get_connection()  # 연결 획득
    result = connection.execute("SELECT * FROM tokens WHERE token = ?", (token,))
    # connection.close() 가 빠짐! - 연결이 반환되지 않아 풀이 고갈됨
    return result.fetchone() is not None
```

약 6시간 후(새벽 3시) 배포된 코드가 충분한 요청을 처리하면서 풀의 최대 연결 수(50)가 모두 소진되었고,
오전 9시경 트래픽이 증가하면서 장애가 표면화되었다.

## 해결 방법

### 즉시 조치 (당일 09:35)
1. 애플리케이션 서버 재시작으로 연결 풀 초기화
2. DB 연결 풀 모니터링 대시보드 확인 후 정상화 확인

### 코드 수정 (v2.3.2 배포 - 2024-03-15 11:00)
```python
# 수정된 코드 - context manager 사용으로 자동 연결 반환 보장
def validate_user_token(token: str) -> bool:
    with db_pool.get_connection() as connection:
        result = connection.execute("SELECT * FROM tokens WHERE token = ?", (token,))
        return result.fetchone() is not None
```

## 재발 방지 대책

1. **코드 리뷰 강화**: DB 연결 관련 코드는 반드시 2인 이상 리뷰
2. **정적 분석 도구 추가**: `pylint`의 `resource-warning` 규칙 CI에 추가
3. **모니터링 알림**: DB 연결 풀 사용률 80% 초과 시 Slack 알림 설정
4. **부하 테스트**: 배포 전 연결 풀 고갈 시나리오 부하 테스트 필수화

## 관련 파일

- `src/auth/service.py` (라인 142)
- `config/database.yaml` (connection pool 설정)
- `tests/auth/test_service.py` (회귀 테스트 추가됨)

## 타임라인

| 시각 | 이벤트 |
|------|--------|
| 2024-03-14 21:00 | v2.3.1 배포 (문제 코드 포함) |
| 2024-03-15 09:15 | 최초 에러 감지 |
| 2024-03-15 09:20 | 온콜 엔지니어 알림 수신 |
| 2024-03-15 09:35 | 서버 재시작으로 임시 복구 |
| 2024-03-15 10:00 | 근본 원인 파악 |
| 2024-03-15 11:00 | v2.3.2 배포 완료 |
| 2024-03-15 11:15 | 완전 정상화 확인 |
