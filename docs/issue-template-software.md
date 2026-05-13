---
id: BUG-YYYY-NNN         # 버그: BUG-YYYY-NNN | 장애: INCIDENT-YYYY-NNN
domain: software         # software | incident
severity: critical       # critical | high | medium | low
status: resolved         # resolved | ongoing | investigating
alarm_code: ""           # 소프트웨어 이슈는 빈 문자열
tags: [태그1, 태그2, 태그3]
created_at: YYYY-MM-DD
resolved_at: YYYY-MM-DD
---

# BUG-YYYY-NNN: {버그 제목}

## 버그 기본 정보

| 항목 | 내용 |
|------|------|
| 이슈 ID | BUG-YYYY-NNN |
| 심각도 | Critical / High / Medium / Low |
| 발생일 | YYYY-MM-DD |
| 해결일 | YYYY-MM-DD |
| 영향 범위 | 영향받은 사용자/기능 범위 |

## 문제 현상

발생 상황, 에러 메시지, 재현 조건 서술.

```
에러 로그 또는 스택 트레이스
```

## 원인 분석

### 직접 원인
...

### 근본 원인
...

```python
# 문제가 된 코드 (파일경로:라인번호)
```

## 해결 방법

### 즉시 조치
1. ...

### 코드 수정
```python
# 수정된 코드
```

## 재발 방지 대책
1. ...
2. ...

## 관련 파일
- `src/...` (라인 번호)

## 타임라인

| 시각 | 이벤트 |
|------|--------|
| YYYY-MM-DD HH:MM | 최초 감지 |
| YYYY-MM-DD HH:MM | 조치 완료 |
