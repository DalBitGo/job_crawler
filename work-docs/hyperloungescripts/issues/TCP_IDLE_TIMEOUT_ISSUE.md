# GCE/GKE TCP Idle Timeout 이슈 종합 분석

## 문제 요약

| 항목 | 내용 |
|------|------|
| 근본 원인 | **GCE/GKE 인스턴스 TCP idle connection timeout (기본 600초/10분)** |
| 영향 범위 | Composer → Cloud Run/Cloud Functions 10분 이상 호출하는 모든 작업 |
| 발견일 | 2026-01-15 (분석 완료) |

## 영향받는 시스템

| 시스템 | 고객사 | 증상 | 소요시간 |
|--------|--------|------|---------|
| trans_dataform | c8cd3500 (엘앤케이웰니스) | Airflow timeout | 10-12분 |
| trans_dataform | c0159c00 (동구바이오) | Airflow timeout | 15-16분 |
| pvcsync | c0159c00 (동구바이오) | 10시간 무한대기 후 강제종료 | 10-11분 |
| 기타 긴 작업 | 확인 필요 | timeout 가능성 | 10분 초과 시 |

---

## 근본 원인

### Google 공식 문서
> "idle TCP connections are disconnected after 10 minutes (600 seconds)"
>
> 출처: [Google Cloud Troubleshooting](https://cloud.google.com/run/docs/troubleshooting)

### 메커니즘

```
┌─────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│    Airflow      │────▶│  GKE Node (TCP)   │────▶│  Cloud Run/GCF  │
│   (Composer)    │     │  timeout=600s     │     │                 │
└─────────────────┘     └───────────────────┘     └─────────────────┘
        │                        │                        │
        │  1. HTTP POST 요청     │                        │
        │───────────────────────▶│───────────────────────▶│
        │                        │                        │
        │                        │    2. 장시간 작업 실행  │
        │  [10분 동안 데이터 흐름 없음 = idle 상태]        │
        │                        │                        │
        │         3. TCP 연결 끊김! (600초 후)            │
        │        X═══════════════X                        │
        │                        │                        │
        │                        │    4. 작업 완료, 응답  │
        │                        │◀───────────────────────│
        │                        │   → 연결 없음! 실패    │
        │                        │                        │
        │  5. Airflow는 응답을 영원히 기다림               │
        │  6. HTTP timeout 후 실패!                       │
```

### 핵심 증거

**trans_dataform (c8cd3500):**
| 날짜 | Cloud Run 소요시간 | Airflow 결과 |
|------|-------------------|-------------|
| 1월 7일 | **595초 (9분 55초)** | SUCCESS |
| 1월 8일 | **607초 (10분 7초)** | timeout |

**pvcsync (c0159c00):**
| 시도 | 소요시간 | 결과 |
|------|---------|------|
| 1차 (실패) | **649초 (10분 50초)** | 응답 손실 → 10시간 대기 |
| 2차 (성공) | **306초 (5분 6초)** | 정상 응답 |

**정확히 600초(10분) 경계에서 성공/실패가 갈림!**

---

## 왜 이런 일이 발생하나?

### Python requests의 기본 동작

```python
# 현재 코드
response = requests.post(endpoint, json=data, timeout=3600)
```

- `timeout=3600`은 HTTP 레벨 timeout (1시간)
- 하지만 TCP keepalive는 **기본적으로 비활성화**
- TCP 연결에 데이터가 흐르지 않으면 GCE가 "죽은 연결"로 판단

### Linux 커널 기본 TCP 설정

```
tcp_keepalive_time: 7200초 (2시간) - 첫 keepalive까지 대기
tcp_keepalive_intvl: 75초
tcp_keepalive_probes: 9회
```

하지만 Python requests는 이 커널 설정을 사용하지 않고, **소켓에 직접 keepalive를 설정해야 함**.

---

## 해결 방법

### 방법 1: TCP Keepalive 활성화 (권장)

**장점:** 코드 수정만으로 해결, 인프라 변경 불필요
**단점:** 여러 파일 수정 필요

#### 수정 대상 파일

| 파일 | 용도 | 수정 필요 |
|------|------|----------|
| `model_transformer/transform_handler.py` | trans_dataform 호출 | O |
| `airflow-dags/dags/dependencies/task_functions.py` | pvcsync 등 호출 | O |
| `collector/common/gcf_caller.py` | tag-prep 등 호출 | O |

#### 구현 코드

**공통 유틸리티 함수 (새 파일 또는 기존 유틸에 추가)**

```python
# airflow-dags/dags/dependencies/http_utils.py (신규)
import socket
import requests
from requests.adapters import HTTPAdapter

class TCPKeepAliveAdapter(HTTPAdapter):
    """TCP Keepalive를 활성화하는 HTTP Adapter

    GCE/GKE의 10분 TCP idle timeout 문제를 해결하기 위해
    60초 간격으로 keepalive 패킷을 전송
    """
    def init_poolmanager(self, *args, **kwargs):
        # TCP keepalive 옵션 설정
        kwargs['socket_options'] = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),      # keepalive 활성화
            (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),    # 60초 후 시작
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),   # 60초 간격
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 10),     # 10회 시도
        ]
        super().init_poolmanager(*args, **kwargs)

def create_keepalive_session():
    """TCP Keepalive가 활성화된 requests Session 생성"""
    session = requests.Session()
    adapter = TCPKeepAliveAdapter()
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

# 사용 예시
# session = create_keepalive_session()
# response = session.post(url, json=data, timeout=3600)
```

#### transform_handler.py 수정

```python
# model_transformer/transform_handler.py
# Line 139 근처 수정

# 기존 코드
# response = requests.post(endpoint, json=json_dat, headers=token.get_header_options(), timeout=3600)

# 수정된 코드
import socket
from requests.adapters import HTTPAdapter

class TCPKeepAliveAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs['socket_options'] = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 10),
        ]
        super().init_poolmanager(*args, **kwargs)

session = requests.Session()
session.mount('https://', TCPKeepAliveAdapter())
response = session.post(endpoint, json=json_dat, headers=token.get_header_options(), timeout=3600)
```

#### task_functions.py 수정

```python
# airflow-dags/dags/dependencies/task_functions.py
# Line 999, 1013 근처 (pvcsync 호출 부분)

# 기존 코드
# res = requests.post(endpoint, json=data, headers={'Authorization': 'Bearer ' + id_token})

# 수정된 코드
import socket
from requests.adapters import HTTPAdapter

class TCPKeepAliveAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs['socket_options'] = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 10),
        ]
        super().init_poolmanager(*args, **kwargs)

session = requests.Session()
session.mount('https://', TCPKeepAliveAdapter())
res = session.post(endpoint, json=data, headers={'Authorization': 'Bearer ' + id_token}, timeout=1200)
```

---

### 방법 2: Cloud Run에서 Streaming Response (대안)

**장점:** 클라이언트 코드 수정 불필요
**단점:** Cloud Run 서비스 코드 수정 필요, 복잡도 증가

```python
# Cloud Run 서비스에서 주기적 heartbeat 전송
from flask import Response
import time

def long_running_task():
    def generate():
        # 작업 시작
        process = start_long_task()

        while not process.is_done():
            yield ".\n"  # heartbeat (30초마다)
            time.sleep(30)

        # 최종 결과 반환
        yield json.dumps(process.result())

    return Response(generate(), mimetype='text/plain')
```

---

### 방법 3: 비동기 처리 패턴 (장기 해결책)

**장점:** 가장 안정적, timeout 문제 완전 해결
**단점:** 아키텍처 변경 필요, 개발 비용 높음

```
1. Airflow → Cloud Run: 작업 요청 (즉시 job_id 반환)
2. Cloud Run: 비동기로 작업 실행
3. Cloud Run: 완료 시 Firestore/GCS에 상태 저장
4. Airflow: Sensor로 완료 상태 polling
```

---

## 권장 조치 순서

### 즉시 조치 (1-2일)

1. **transform_handler.py** TCP keepalive 추가
   - 영향: trans_dataform task
   - 대상 고객: c8cd3500, c0159c00 등

2. **task_functions.py** TCP keepalive 추가
   - 영향: pvcsync task
   - 대상 고객: c0159c00 등

### 테스트 (조치 후)

```bash
# c8cd3500 trans_dataform 모니터링
gcloud logging read 'resource.labels.service_name="model-transformer-2-0" AND textPayload=~"c8cd3500"' \
  --limit=20 --format="table(timestamp,textPayload)"

# c0159c00 pvcsync 모니터링
gcloud logging read 'resource.labels.service_name="pvcsync" AND textPayload=~"c0159c00"' \
  --limit=20 --format="table(timestamp,textPayload)"
```

### 검증 기준

- 10분+ 소요되는 작업에서도 Airflow가 정상 응답 수신
- `Response status code: 200` 로그 확인
- task SUCCESS 확인

---

## 관련 문서

| 문서 | 내용 |
|------|------|
| `pvcsync/INCIDENT_ANALYSIS_c0159c00.md` | c0159c00 pvcsync 장애 분석 |
| `pvcsync/ROOT_CAUSE_ANALYSIS_c0159c00.md` | c0159c00 근본 원인 분석 |
| `TRANS_DATAFORM_TIMEOUT_ISSUE.md` | trans_dataform timeout 분석 |

## 참고 자료

- [Google Cloud Run Troubleshooting](https://cloud.google.com/run/docs/troubleshooting) - Idle Connection Timeout
- [Tune NAT configuration](https://docs.cloud.google.com/nat/docs/tune-nat-configuration) - NAT timeout 설정
- Python requests TCP keepalive: `socket.SO_KEEPALIVE`, `TCP_KEEPIDLE`, `TCP_KEEPINTVL`

---

## 변경 이력

| 날짜 | 내용 |
|------|------|
| 2025-12-02 | c0159c00 pvcsync 장애 분석 (logging import 누락으로 오진) |
| 2026-01-15 | 근본 원인 발견: GCE/GKE TCP idle timeout 600초 |
| 2026-01-15 | 문서 통합 및 해결책 정리 |

---

작성: Claude (Claude Code)
최종 수정: 2026-01-15
