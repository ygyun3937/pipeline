---
id: INCIDENT-2024-008
domain: incident
severity: critical
status: resolved
alarm_code: ""
tags: [database, disk-full, p0, audit-log, service-outage, postgresql]
created_at: 2024-09-20
resolved_at: 2024-09-20
---

# INCIDENT-2024-008: 데이터베이스 디스크 용량 초과 장애

## 장애 개요

| 항목 | 내용 |
|------|------|
| 인시던트 ID | INCIDENT-2024-008 |
| 등급 | P0 (전체 서비스 중단) |
| 발생 시각 | 2024-09-20 02:47 KST |
| 복구 시각 | 2024-09-20 04:15 KST |
| 총 장애 시간 | 88분 |
| 담당 팀 | 인프라팀, 백엔드팀 |
| 영향 사용자 수 | 약 12,000명 (활성 세션 기준) |

## 장애 현상

2024년 9월 20일 새벽 02:47, 운영 DB 서버(db-prod-01)의 디스크 용량이 100%에 도달하여
모든 쓰기 작업이 실패하기 시작했다.

- API 서버 에러율: 0.1% → 100%로 급등
- 에러 메시지: `SQLSTATE[HY000]: General error: 28 No space left on device`
- 영향 서비스: 사용자 인증, 주문, 결제, 프로필 수정 등 모든 쓰기 작업

## 원인 분석

### 직접 원인

DB 서버 `/var/lib/postgresql/` 파티션 디스크 사용률 100% 도달.

```bash
# 장애 발생 시점 디스크 상태
$ df -h
Filesystem      Size  Used Avail Use% Mounted on
/dev/xvdb1      500G  500G     0 100% /var/lib/postgresql
```

### 근본 원인 - 감사 로그 무제한 축적

2024년 8월 1일, 보안 감사 요건 충족을 위해 모든 API 요청에 대한 감사 로그를
DB에 저장하는 기능이 추가되었다. 그러나 다음 두 가지가 누락되었다:

1. **로그 보존 정책 미설정**: 오래된 감사 로그를 삭제하는 로직이 없었다.
2. **용량 예측 오류**: 감사 로그 테이블의 증가 속도를 과소 평가했다.

```sql
-- 감사 로그 테이블 크기 분석 (장애 직후)
SELECT
    pg_size_pretty(pg_total_relation_size('audit_logs')) as table_size,
    COUNT(*) as row_count,
    MIN(created_at) as oldest_record,
    MAX(created_at) as newest_record
FROM audit_logs;

-- 결과:
-- table_size: 387 GB
-- row_count: 2,847,293,081 (28억 건!)
-- oldest_record: 2024-08-01 00:00:01
-- newest_record: 2024-09-20 02:46:59
```

50일간 약 28억 건의 감사 로그가 누적되어 387GB를 차지했다.
나머지 113GB는 실제 애플리케이션 데이터와 WAL 로그가 차지했다.

## 복구 과정

### 1단계: 긴급 공간 확보 (02:47 ~ 03:10)

1. 90일 이상 된 감사 로그 즉시 삭제
```sql
-- 2024-08-01 이전 데이터 삭제 (사실상 전체 데이터)
-- 주의: 프로덕션에서 이런 방식의 대량 삭제는 신중히 진행
DELETE FROM audit_logs
WHERE created_at < '2024-09-19 00:00:00'
LIMIT 10000000;  -- 배치로 나누어 삭제 (한 번에 하면 락 발생)
```

2. PostgreSQL VACUUM 실행으로 디스크 공간 즉시 반환
```sql
VACUUM FULL audit_logs;  -- 디스크 공간 반환 (약 20분 소요)
```

### 2단계: 서비스 복구 확인 (03:10 ~ 03:30)

```bash
$ df -h /var/lib/postgresql
Filesystem      Size  Used Avail Use% Mounted on
/dev/xvdb1      500G  113G  387G  23% /var/lib/postgresql
```

디스크 여유 공간 확보 후 API 서버 정상화 확인.

### 3단계: 근본 원인 해결 (03:30 ~ 04:15)

감사 로그 보존 정책 즉시 적용:
```sql
-- 30일 이상 된 감사 로그 자동 삭제 파티셔닝 설정
-- (실제 구현은 pg_partman 활용)
CREATE INDEX CONCURRENTLY idx_audit_logs_created_at
    ON audit_logs(created_at);

-- 매일 자정 실행되는 삭제 잡 추가 (cron)
-- 0 0 * * * psql -c "DELETE FROM audit_logs WHERE created_at < NOW() - INTERVAL '30 days'"
```

## 재발 방지 대책

### 즉시 조치 (완료)
- [x] 감사 로그 30일 보존 정책 적용
- [x] DB 디스크 사용률 70% 경보, 85% 긴급 알림 설정
- [x] 감사 로그 테이블 파티셔닝 적용 (월별)

### 단기 개선 (1개월 내)
- [ ] 감사 로그를 DB 대신 S3 + Athena 구조로 이관
- [ ] 디스크 자동 확장(Auto Scaling) 설정 검토
- [ ] 용량 계획(Capacity Planning) 문서 작성

### 장기 개선 (3개월 내)
- [ ] 전체 인프라 용량 모니터링 대시보드 구축
- [ ] 신기능 추가 시 용량 영향도 분석 프로세스 의무화
- [ ] DR(Disaster Recovery) 훈련 시나리오에 디스크 풀 케이스 추가

## 교훈

1. **새로운 데이터 저장 기능 추가 시 반드시 보존 정책을 함께 설계해야 한다.**
2. **모니터링은 "현재 상태"뿐 아니라 "추세 기반 예측"도 필요하다.**
3. **디스크 용량 경보를 70%로 설정하면 대응 시간이 충분히 확보된다.**

## 관련 링크

- 장애 전후 모니터링 그래프: [Grafana 대시보드 링크]
- 보안 감사 로그 정책 문서: `docs/security/audit-log-policy.md`
- DB 운영 가이드라인: `docs/infrastructure/database-operations.md`
