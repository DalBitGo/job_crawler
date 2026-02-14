# trans_dataform Timeout 이슈 분석

## 문제 요약

| 항목 | 내용 |
|------|------|
| 발생일 | 2026-01-08부터 지속 |
| 영향 고객 | c8cd3500 (엘앤케이웰니스), c0159c00 및 기타 고객사 |
| 증상 | trans_dataform task가 Cloud Run에서는 정상 완료되지만 Airflow는 1시간 후 timeout |
| 근본 원인 | **GCE/GKE 인스턴스 TCP idle connection timeout (기본 600초/10분)** |

## 근본 원인 발견

### Google 공식 문서
> "idle TCP connections are disconnected after 10 minutes (600 seconds)"
>
> 출처: [Google Cloud Troubleshooting](https://cloud.google.com/run/docs/troubleshooting)

GKE 노드 (Composer 워커가 실행되는 곳)의 기본 TCP idle timeout이 **600초 (10분)**입니다.

### 핵심 증거

| 날짜 | Cloud Run 소요시간 | Airflow 결과 |
|------|-------------------|-------------|
| 1월 7일 | 595초 (9분 55초) | **SUCCESS** |
| 1월 8일 | 607초 (10분 7초) | timeout |
| 1월 9일 | 656초 (10분 56초) | timeout |
| 1월 10일 | 657초 (10분 57초) | timeout |
| 1월 12일 | 649초 (10분 49초) | timeout |
| 1월 13일 | 728초 (12분 8초) | timeout |
| 1월 14일 | 713초 (11분 53초) | timeout |

**정확히 600초(10분) 경계에서 성공/실패가 갈림!**

## 상세 분석

### 정상 케이스 (1월 7일 - 595초)

```
22:16:22 - Airflow → Cloud Run 요청 전송
22:26:17 - Cloud Run 응답 수신 (595초, 10분 미만)
22:26:20 - task SUCCESS ✅
```

### 문제 케이스 (1월 8일 이후 - 600초 초과)

```
22:01:24 - Airflow → Cloud Run 요청 전송
22:11:24 - [10분 경과] TCP 연결 끊김! ← 여기가 문제
22:11:31 - Cloud Run 처리 완료 (607초, 로그에서 확인됨)
          ↳ Cloud Run은 응답을 보내려 하지만 연결이 이미 끊김
23:01:24 - Airflow timeout! (1시간 후)
```

### 왜 응답을 못 받나?

```
┌─────────────────┐     ┌───────────────────┐     ┌─────────────┐
│    Airflow      │────▶│  GKE Node (TCP)   │────▶│  Cloud Run  │
│   (Composer)    │     │  timeout=600s     │     │             │
└─────────────────┘     └───────────────────┘     └─────────────┘
        │                        │                       │
        │  1. HTTP POST 요청     │                       │
        │───────────────────────▶│──────────────────────▶│
        │                        │                       │
        │                        │    2. dataform 실행   │
        │  [10분 동안 데이터 흐름 없음 = idle 상태]       │
        │                        │                       │
        │         3. TCP 연결 끊김!                      │
        │        X═══════════════X                       │
        │                        │                       │
        │                        │    4. 응답 전송 시도  │
        │                        │◀──────────────────────│
        │                        │   → 연결 없음! 실패   │
        │                        │                       │
        │  5. Airflow는 응답을 영원히 기다림              │
        │  6. 1시간 후 timeout!                          │
```

## 관련 설정 확인

### GKE 노드 (Composer 워커)
```yaml
# Linux 커널 기본 TCP 설정
tcp_keepalive_time: 7200  # 2시간 (첫 keepalive까지)
# → Python requests는 기본적으로 TCP keepalive를 보내지 않음
# → 결과: 10분 idle 후 GCE가 연결 종료
```

### Airflow 측 (transform_handler.py:139)
```python
response = requests.post(endpoint, json=json_dat, headers=..., timeout=3600)
# HTTP timeout 1시간 - 문제 없음
# 하지만 TCP keepalive가 없어서 10분 후 연결 끊김
```

### Cloud Run 측
```yaml
timeoutSeconds: 1800  # 30분 - 문제 없음
```

### Cloud NAT (vmnat-nat)
```yaml
# tcpEstablishedIdleTimeoutSec: 1200 (기본값 20분)
# NAT는 문제가 아님! GKE 노드 레벨에서 먼저 끊김
```

## 해결 방법

### 방법 1: TCP Keepalive 활성화 (권장)

Airflow 코드에서 TCP keepalive를 활성화:

```python
# transform_handler.py 수정
import socket
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

class KeepAliveAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        kwargs['socket_options'] = [
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
            (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),  # 60초 후 keepalive 시작
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),  # 60초 간격
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5),     # 5회 시도
        ]
        super().init_poolmanager(*args, **kwargs)

session = requests.Session()
session.mount('https://', KeepAliveAdapter())
response = session.post(endpoint, json=json_dat, headers=..., timeout=3600)
```

- **장점**: 인프라 변경 없이 코드 수정으로 해결
- **단점**: 코드 수정 및 배포 필요
- **영향 범위**: transform_handler.py만 수정

### 방법 2: Cloud Run에서 Streaming Response 사용

Cloud Run 서비스에서 처리 중 주기적으로 데이터를 보내 연결 유지:

```python
# dataform_run.py 수정 예시
from flask import Response
import subprocess

def run_dataform_streaming():
    def generate():
        process = subprocess.Popen(...)
        while process.poll() is None:
            yield ".\n"  # heartbeat
            time.sleep(30)
        yield json.dumps({"result": "success"})

    return Response(generate(), mimetype='text/plain')
```

- **장점**: 클라이언트 수정 불필요
- **단점**: Cloud Run 서비스 코드 수정 필요, 복잡도 증가

### 방법 3: 비동기 처리 패턴으로 변경

1. Airflow가 Cloud Run에 작업 요청 (즉시 반환, job_id 받음)
2. Cloud Run이 작업 완료 후 Firestore/GCS에 상태 저장
3. Airflow가 polling으로 완료 확인

- **장점**: 긴 작업에 가장 안정적, timeout 문제 완전 해결
- **단점**: 아키텍처 변경 필요, 개발 비용 높음

## 권장 조치

### 즉시 조치 (방법 1)

**transform_handler.py**에 TCP keepalive 추가:

```python
# Line 139 근처 수정
import socket

# 기존 requests 대신 session 사용
session = requests.Session()

# TCP keepalive 설정
socket_options = [
    (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
    (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60),
    (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 60),
    (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5),
]

from urllib3.util import connection
_orig_create_connection = connection.create_connection

def patched_create_connection(address, *args, **kwargs):
    sock = _orig_create_connection(address, *args, **kwargs)
    for opt in socket_options:
        sock.setsockopt(*opt)
    return sock

connection.create_connection = patched_create_connection

response = session.post(endpoint, json=json_dat, headers=token.get_header_options(), timeout=3600)
```

### 테스트
- 다음 c8cd3500 DAG 실행 시 trans_dataform task 모니터링
- 10분+ 걸려도 정상 응답 수신되는지 확인

## 영향받는 고객사

10분 이상 dataform 처리가 필요한 고객사 (로그 분석 결과):

| 고객사 | 평균 소요시간 | 상태 |
|--------|-------------|------|
| c8cd3500 (엘앤케이웰니스) | 10-12분 | timeout 발생 |
| c0159c00 | 15-16분 | timeout 발생 |
| 기타 | 10분 미만 | 정상 |

```bash
# 10분 이상 걸리는 dataform 작업 조회
gcloud logging read 'resource.labels.service_name="model-transformer-2-0" AND httpRequest.latency>"600s"' \
  --project=hyperlounge-dev \
  --limit=50 \
  --format="table(timestamp,httpRequest.latency,httpRequest.requestUrl)"
```

## 관련 파일

| 파일 | 역할 |
|------|------|
| `model_transformer/transform_handler.py` | Airflow에서 Cloud Run 호출 (수정 필요) |
| `model_transform/app/controller/dataform_run.py` | Cloud Run 서비스 코드 |
| `airflow-dags/dags/c8cd3500.py` | 고객사 DAG 설정 |

## 참고 문서

- [Google Cloud Run Troubleshooting - Idle Connection Timeout](https://cloud.google.com/run/docs/troubleshooting)
- [Tune NAT configuration](https://docs.cloud.google.com/nat/docs/tune-nat-configuration)
- Cloud NAT TCP established idle timeout 기본값: 1200초 (20분)
- GCE/GKE TCP idle connection timeout: **600초 (10분)** ← 이게 문제!
- Cloud Run request timeout: 1800초 (30분)

## 왜 NAT가 아닌가?

초기 분석에서 Cloud NAT를 의심했지만:
- NAT 기본 timeout: 1200초 (20분)
- c0159c00 케이스: 941초 (15분 41초)에 완료됐지만 timeout 발생
- **결론**: NAT보다 먼저 GKE 노드의 TCP timeout (600초)에서 연결이 끊김

---

## 관련 문서

이 이슈는 더 큰 TCP idle timeout 문제의 일부입니다:
- **[TCP_IDLE_TIMEOUT_ISSUE.md](./TCP_IDLE_TIMEOUT_ISSUE.md)** - 종합 분석 및 해결책 (권장)
- `pvcsync/INCIDENT_ANALYSIS_c0159c00.md` - 동일 원인의 pvcsync 장애

---

작성일: 2026-01-15
작성자: Claude (분석 지원)
최종 수정: 2026-01-15 (근본 원인 정정, 통합 문서 링크 추가)
