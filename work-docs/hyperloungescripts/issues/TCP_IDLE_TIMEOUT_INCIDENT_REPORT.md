# TCP Idle Timeout 이슈 보고서

**작성일:** 2026-01-16
**작성자:** 박준현
**상태:** 수정 완료, 배포 대기

---

## 1. 문제 요약

| 항목 | 내용 |
|------|------|
| **영향 시스템** | pvcsync (c0159c00 동구바이오), trans_dataform (c8cd3500 엘앤케이웰니스) |
| **증상** | Cloud Run은 정상 완료(200 OK), Airflow는 응답 못 받고 timeout |
| **근본 원인** | GKE Node의 TCP idle timeout 600초 (10분) |

---

## 2. 근거 데이터

### trans_dataform (c8cd3500 엘앤케이웰니스)

| 날짜 | Cloud Run 소요시간 | Airflow 결과 |
|------|-------------------|-------------|
| 1월 7일 | **595초 (9분 55초)** | ✅ SUCCESS |
| 1월 8일 | **607초 (10분 7초)** | ❌ timeout |
| 1월 9일 | 656초 (10분 56초) | ❌ timeout |
| 1월 10일 | 657초 (10분 57초) | ❌ timeout |
| 1월 12일 | 649초 (10분 49초) | ❌ timeout |
| 1월 13일 | 728초 (12분 8초) | ❌ timeout |
| 1월 14일 | 713초 (11분 53초) | ❌ timeout |

**→ 정확히 600초(10분) 경계에서 성공/실패가 갈림**

### pvcsync (c0159c00 동구바이오)

| 시도 | 소요시간 | 결과 |
|------|---------|------|
| 1차 (실패) | **649초 (10분 50초)** | ❌ 응답 손실 → 10시간 대기 후 강제 종료 |
| 2차 (성공) | **306초 (5분 6초)** | ✅ 정상 응답 |

**→ 10분 초과 시 실패, 10분 미만 시 성공**

---

## 3. 문제 발생 메커니즘

### 아키텍처 구조

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Composer (GKE Cluster)                      │
│                                                                     │
│   Airflow Worker (Python)                                           │
│         │                                                           │
│         │ requests.post("Cloud Run 호출")                           │
│         ▼                                                           │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │                    GKE Node (Linux VM)                       │  │
│   │                                                              │  │
│   │   TCP 연결 생성 → 데이터 전송 → [대기 상태]                   │  │
│   │                                                              │  │
│   │   ★ 10분간 데이터 흐름 없으면 "죽은 연결"로 판단 → 끊음      │  │
│   └─────────────────────────────────────────────────────────────┘  │
│         │                                                           │
└─────────┼───────────────────────────────────────────────────────────┘
          │ 인터넷
          ▼
   Cloud Run (작업 실행 중, 10분+ 소요)
          │
          │ 작업 완료 → 응답 전송 시도
          ▼
   ❌ 연결이 이미 끊김 → 응답 전달 불가
```

### 결과
- Cloud Run 로그: `200 OK` (작업 자체는 성공)
- Airflow Worker: 응답을 영원히 기다림 → HTTP timeout (1시간) 후 실패

### Timeout 종류 비교

| 종류 | 설정 위치 | 역할 | 설정값 |
|------|----------|------|--------|
| **HTTP Timeout** | Python 코드 (`timeout=3600`) | "응답 안 오면 포기" | 1시간 |
| **TCP Idle Timeout** | GKE Node (OS 레벨) | "연결 죽었나?" 판단 | **10분** |

HTTP Timeout을 1시간으로 설정해도, TCP 레벨에서 10분 후 연결이 끊기면 소용없음.

---

## 4. Google 공식 문서 근거

> **"idle TCP connections are disconnected after 10 minutes (600 seconds)"**
>
> 출처: [Google Cloud Run Troubleshooting](https://cloud.google.com/run/docs/troubleshooting)

GCE/GKE 인스턴스의 기본 TCP idle timeout 설정입니다.

---

## 5. 왜 갑자기 발생했나?

| 시점 | 상황 |
|------|------|
| 1월 7일 이전 | dataform 처리 시간 10분 미만 → 정상 |
| 1월 8일 이후 | 데이터 증가로 처리 시간 10분 초과 → timeout 발생 |

**처리할 데이터가 늘어나면서 10분 경계를 넘기 시작**

---

## 6. 해결 방법

### TCP Keepalive 활성화

60초마다 작은 신호를 보내 연결 유지

```
기존 (문제 발생):
0분 ─────────────────────────── 10분 (끊김!) ─── 12분
    [데이터 없음 = idle 상태]

수정 후 (keepalive 적용):
0분 ──♥──♥──♥──♥──♥──♥──♥──♥──♥──♥──♥──♥── 12분 (정상)
    [60초마다 keepalive 신호]
```

### 수정 코드

```python
import socket
from requests.adapters import HTTPAdapter

class TCPKeepAliveAdapter(HTTPAdapter):
    """TCP Keepalive를 활성화하는 HTTP Adapter
    GCE/GKE의 10분 TCP idle timeout 문제 해결을 위해 60초 간격으로 keepalive 전송
    """
    def init_poolmanager(self, *args, **kwargs):
        kwargs['socket_options'] = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),      # keepalive 활성화
            (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),    # 60초 후 시작
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),   # 60초 간격
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 10),     # 10회 시도
        ]
        super().init_poolmanager(*args, **kwargs)

# 사용
session = requests.Session()
session.mount('https://', TCPKeepAliveAdapter())
response = session.post(url, json=data, timeout=3600)
```

---

## 7. 수정 파일 및 배포

### 수정된 파일

| 파일 | 영향 범위 | 배포 위치 |
|------|----------|----------|
| `task_functions.py` | pvcsync 등 GCF 호출 | `dags/dependencies/` |
| `transform_handler.py` | trans_dataform | `dags/model_transformer/` |

### 배포 방법

GCS 버킷에 직접 업로드:
```
gs://asia-northeast3-prodcomp2-4-fe0f3a24-bucket/dags/dependencies/task_functions.py
gs://asia-northeast3-prodcomp2-4-fe0f3a24-bucket/dags/model_transformer/transform_handler.py
```

### 원복 방법

문제 발생 시 이전 파일로 덮어쓰기

---

## 8. 검증 계획

배포 후 다음 배치 실행 시 모니터링:

| 고객사 | Task | 예상 소요시간 |
|--------|------|--------------|
| c8cd3500 (엘앤케이웰니스) | trans_dataform | 10-12분 |
| c0159c00 (동구바이오) | pvcsync | 10-11분 |

### 성공 기준
- 10분 이상 걸려도 Airflow가 정상 응답 수신
- Task 상태: SUCCESS

### 모니터링 명령어

```bash
# trans_dataform 로그 확인
gcloud logging read 'resource.labels.service_name="model-transformer-2-0" AND textPayload=~"c8cd3500"' \
  --limit=20 --format="table(timestamp,textPayload)"

# pvcsync 로그 확인
gcloud logging read 'resource.labels.function_name="pvcsync" AND textPayload=~"c0159c00"' \
  --limit=20 --format="table(timestamp,textPayload)"
```

---

## 9. 관련 문서

| 문서 | 내용 |
|------|------|
| `TCP_IDLE_TIMEOUT_ISSUE.md` | 기술 상세 분석 |
| `TRANS_DATAFORM_TIMEOUT_ISSUE.md` | trans_dataform 분석 |
| `pvcsync/INCIDENT_ANALYSIS_c0159c00.md` | pvcsync 장애 분석 |

---

## 10. 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-01-08 | c8cd3500 trans_dataform timeout 최초 발생 |
| 2026-01-15 | 근본 원인 분석 완료 (TCP idle timeout) |
| 2026-01-16 | 코드 수정 완료, 배포 대기 |
