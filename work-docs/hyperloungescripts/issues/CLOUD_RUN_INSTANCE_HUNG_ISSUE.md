# Cloud Run 인스턴스 Hung 이슈 (504 Timeout)

## 문제 요약

| 항목 | 내용 |
|------|------|
| 발생일 | 2026-01-25 ~ 2026-01-27 |
| 영향 서비스 | hyperlounge-python-converter-2-0 |
| 근본 원인 | min instances 중 1개가 Hung 상태 |
| 해결 방법 | min instances=0 설정 |

## 영향 범위

| 고객사 | DAG ID | 발생일 |
|--------|--------|--------|
| 엘앤케이웰니스 | c8cd3500 | 2026-01-27 |
| 케이드라이브 | cf526000 | 2026-01-26 |
| 에이텍 | c3737100 | 2026-01-25 |

## 증상

- DAG 실행 시 `hyperlounge-python-converter` 호출에서 간헐적 504 Gateway Timeout
- 여러 건 동시 요청 시 **정확히 1건만 실패**하는 패턴
- 실패한 요청은 15분(900초) 후 504 반환
- 재시도하면 성공하는 경우 있음

## 근본 원인

### Cloud Run 설정
```
Concurrency: 1 (인스턴스당 동시 1개 요청)
Min instances: 2 (항상 2개 대기)
Max instances: 100
Timeout: 900초 (15분)
```

### 문제 발생 메커니즘

```
┌─────────────────────────────────────────────────────────────────┐
│  Cloud Run: min instances = 2                                   │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐                          │
│  │ Instance #1  │    │ Instance #2  │                          │
│  │ (정상)       │    │ (Hung 상태)  │                          │
│  │              │    │              │                          │
│  │ 요청 → 5초   │    │ 요청 → 504   │                          │
│  │ 처리 완료 ✅  │    │ 15분 후 ❌   │                          │
│  └──────────────┘    └──────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

### 증거 (로그 분석)

모든 504 에러가 **동일한 인스턴스 ID**에서 발생:

```
504 실패 요청 (5건 전부):
  Instance ID: ...877dd572ccfe8d

성공 요청:
  Instance ID: ...e8f7a9c9969bdb (다른 인스턴스)
```

### 왜 감지되지 않았나?

- **Startup Probe만 설정**: 컨테이너 시작 시에만 체크
- **Liveness Probe 미설정**: 실행 중 상태 체크 없음
- 인스턴스가 나중에 Hung되어도 자동 감지/교체 안 됨

## 해결 방안

### 1. 즉시 조치: min instances=0 설정

```bash
gcloud run services update hyperlounge-python-converter-2-0 \
  --region=asia-northeast3 \
  --min-instances=0
```

**효과:**
- 유휴 인스턴스 자동 제거
- 문제 인스턴스 자연 교체
- 비용 절감 (대기 인스턴스 비용 없음)

**단점:**
- Cold start 발생 가능 (첫 요청 시 3~6초 지연)

### 2. 장기 해결: Liveness Probe 추가

```yaml
livenessProbe:
  httpGet:
    path: /
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 30
  failureThreshold: 3
```

**효과:**
- 비정상 인스턴스 자동 감지
- 문제 발생 시 자동 재시작

### 3. 임시 조치: 새 revision 배포

```bash
gcloud run services update hyperlounge-python-converter-2-0 \
  --region=asia-northeast3 \
  --update-labels="refresh=$(date +%s)"
```

**효과:**
- 모든 인스턴스 즉시 교체
- 일시적 해결 (재발 가능)

## 모니터링

### 504 에러 확인
```bash
gcloud logging read 'resource.labels.service_name="hyperlounge-python-converter-2-0" AND httpRequest.status=504' \
  --limit=10 --format="table(timestamp,labels.instanceId,httpRequest.status)"
```

### 인스턴스별 요청 분포 확인
```bash
gcloud logging read 'resource.labels.service_name="hyperlounge-python-converter-2-0" AND httpRequest.status=200' \
  --limit=50 --format="value(labels.instanceId)" | sort | uniq -c
```

## 관련 문서

- [TCP_IDLE_TIMEOUT_ISSUE.md](./TCP_IDLE_TIMEOUT_ISSUE.md) - TCP Keepalive 관련 이슈

## 변경 이력

| 날짜 | 내용 |
|------|------|
| 2026-01-27 | 이슈 발견 및 원인 분석 |
| 2026-01-27 | min instances=0 설정으로 해결 |

---
작성: Claude (Claude Code)
최종 수정: 2026-01-27
