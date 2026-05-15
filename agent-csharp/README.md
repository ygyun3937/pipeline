# 장비 에이전트 (C#)

Python `src/agent/main.py`와 동일한 기능을 C#/.NET 8로 구현한 Windows 장비 에이전트.
ASP.NET Core Minimal API로 REST 엔드포인트를 제공하고, 중앙 서버(Python FastAPI)와 HTTP로 통신한다.

## 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/execute` | 커맨드 실행 (charge / discharge / measure / reset) |
| POST | `/pause` | 일시 정지 |
| POST | `/resume` | 재개 |
| POST | `/estop` | 비상 정지 |
| POST | `/reset` | 상태 초기화 (idle) |
| GET  | `/status` | 현재 장비 상태 조회 |

## 빌드

```bash
cd agent-csharp
dotnet build
```

## 실행 (Mock 모드)

```bash
AGENT_DEVICE_ID=CHG-A-01 AGENT_PORT=8081 USE_MOCK=true dotnet run
```

## 실행 (실제 장비 - Modbus TCP)

```bash
AGENT_DEVICE_ID=CHG-A-01 AGENT_PORT=8081 USE_MOCK=false EQUIPMENT_HOST=192.168.1.10 dotnet run
```

## 배포 (Windows .exe 단일 파일)

```bash
dotnet publish -c Release -r win-x64 --self-contained
```

출력: `bin/Release/net8.0/win-x64/publish/AgentApp.exe`

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `AGENT_DEVICE_ID` | `MOCK-01` | 장비 고유 ID |
| `AGENT_DEVICE_NAME` | `장비 에이전트` | 장비 이름 |
| `AGENT_DEVICE_TYPE` | `charger` | 장비 유형 |
| `AGENT_PORT` | `8081` | 에이전트 수신 포트 |
| `CENTRAL_BACKEND_URL` | `http://localhost:8000` | 중앙 서버 URL |
| `EQUIPMENT_HOST` | `192.168.1.10` | Modbus TCP 장비 IP |
| `EQUIPMENT_PORT` | `502` | Modbus TCP 포트 |
| `USE_MOCK` | `true` | Mock 드라이버 사용 여부 |
