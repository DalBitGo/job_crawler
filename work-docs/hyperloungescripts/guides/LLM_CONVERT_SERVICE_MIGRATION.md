# LLM Convert Service 마이그레이션 가이드

## 📋 개요

LLM 변환 시스템을 Cloud Run Job 방식에서 Cloud Run Service 방식으로 마이그레이션

- **날짜**: 2025-11-17
- **대상 고객**: 엘앤케이웰니스 (c8cd3500), 에이텍 (cf526000)
- **작업자**: Junhyun Park

---

## 🔄 아키텍처 변경

### Before: Cloud Run Job 방식

```
[Airflow Task]
  ↓ Cloud Run Job 실행 요청
  ↓ run_v2.JobsClient().run_job()
  ↓ operation.result(timeout=3600) - 완료까지 대기
  ↓ succeeded_count 확인
  ✅ Task 완료
```

**특징:**
- 비동기 Job 실행 → 완료까지 대기 (동기화)
- 환경 변수로 파라미터 전달
- Firestore에서 설정 로드
- 최대 1시간 타임아웃

### After: Cloud Run Service 방식

```
[Airflow Task]
  ↓ HTTP POST /api/v1/conversions
  ↓ requests.post(url, json=payload, timeout=3600)
  ↓ 변환 + 검증 + GCS 업로드 + BigQuery insert
  ↓ {"status": "success", "bigquery_uploaded": true}
  ✅ Task 완료
```

**특징:**
- HTTP API 동기 호출
- JSON Body로 파라미터 전달
- PostgreSQL에서 설정 로드
- Gemini AI 검증 추가
- BigQuery 자동 업로드
- 최대 1시간 타임아웃

---

## ⚠️ 주요 이슈 및 해결

### 1. Fallback 비동기 실행 문제

#### 문제점
```
[llm_convert task]
  검증 실패 → Fallback Job 트리거 (백그라운드)
  즉시 응답: {"status": "validation_failed"}
  ✅ 2초 만에 완료

[fileid_mapping_hai task] ← 바로 실행!
  ❌ *_HAI.xlsx 파일 없음
  ❌ 실패

[Fallback Job] ← 백그라운드 실행 중
  30분 후 파일 생성 (이미 늦음)
```

#### 현재 해결 방안
- `status == "success"` 경우만 통과
- `status != "success"` 시 AirflowFailException 발생
- **향후 개선**: Cloud Run Service에서 Fallback을 동기적으로 처리

### 2. 파이프라인 타이밍 의존성

#### 에이텍 파이프라인
```python
crawler → fileid_mapping → llm_convert → fileid_mapping_hai → filter → converter → tag
```

#### 엘앤케이웰니스 파이프라인
```python
# shared_drive
crawler → fileid_mapping → llm_convert
fileid_mapping → filter → converter → tag (병렬)

# email
llm_convert → crawler → fileid_mapping → fileid_mapping_hai → filter → converter → tag
```

**중요:**
- `fileid_mapping_hai`는 `*_HAI.xlsx` 파일이 GCS에 존재해야 함
- `llm_convert` 완료 시점에 파일이 이미 업로드되어 있어야 함

---

## 📝 수정된 파일

### 1. task_functions.py

**위치**: `airflow-dags/dags/dependencies/task_functions.py:1318-1442`

**주요 변경사항:**

```python
# Before: Cloud Run Job
from google.cloud import run_v2
client = run_v2.JobsClient()
operation = client.run_job(request=execution_request)
execution = operation.result(timeout=3600)

# After: Cloud Run Service
import requests
import google.auth
response = requests.post(
    f"{service_url}/api/v1/conversions",
    json=payload,
    headers={"Authorization": f"Bearer {id_token}"},
    timeout=3600
)
```

**API 엔드포인트:**
```
POST /api/v1/conversions
Content-Type: application/json
Authorization: Bearer {ID_TOKEN}
```

**요청 Payload:**
```json
{
  "tenant_code": "c8cd3500",
  "bsda": "20251030",
  "file_id": "TRINITI_ICHON",     // optional
  "prompt_id": "OPERATION_RATE"    // optional
}
```

**응답 처리:**
```python
if result.get("status") == "success":
    # 정상 처리
    return result
else:
    # validation_failed, error 등
    raise AirflowFailException(...)
```

### 2. c8cd3500.py (엘앤케이웰니스)

**라인**: 52

```python
# Before
"llm_converter_service_url": "https://llm-converter-xlsx-to-xlsx-848582894134.asia-northeast3.run.app"

# After
"llm_converter_service_url": "https://hyperlounge-python-converter-l27zak4z4q-du.a.run.app"
```

### 3. cf526000.py (에이텍)

**라인**: 52

```python
# Before
"llm_converter_service_url": "https://llm-converter-xlsx-to-xlsx-848582894134.asia-northeast3.run.app"

# After
"llm_converter_service_url": "https://hyperlounge-python-converter-l27zak4z4q-du.a.run.app"
```

---

## 🔑 핵심 포인트

### 1. 동기적 완료 대기

**검증 성공 케이스:**
```
요청 (10:00)
  ↓
  ⏳ 변환 수행 (10분 소요)
  ↓
응답 (10:10) ← 모든 작업 완료
  - GCS에 *_HAI.xlsx 업로드 완료
  - BigQuery에 데이터 insert 완료
```

**특징:**
- 변환이 10분 걸리면 → 10분 대기
- 변환이 30분 걸리면 → 30분 대기
- 응답 받은 시점 = 모든 작업 완료

### 2. 타임아웃 처리

| 변환 시간 | 결과 |
|----------|------|
| 5초 | ✅ 5초 후 응답 |
| 10분 | ✅ 10분 후 응답 |
| 30분 | ✅ 30분 후 응답 |
| 50분 | ✅ 50분 후 응답 |
| 70분 | ❌ 타임아웃 에러 (1시간 초과) |

### 3. 인증 방식

```python
# ID Token 발급
auth_req = google.auth.transport.requests.Request()
credentials, project = google.auth.default()
credentials.refresh(auth_req)
id_token = credentials.token

# API 호출
headers = {
    "Authorization": f"Bearer {id_token}",
    "Content-Type": "application/json"
}
```

---

## 📊 비교표

| 항목 | Before (Job) | After (Service) |
|------|-------------|----------------|
| **호출 방식** | Cloud Run Job | Cloud Run Service |
| **API 형태** | gRPC (run_v2) | HTTP REST API |
| **응답 방식** | 동기 (완료 대기) | 동기 (완료 대기) |
| **파라미터** | 환경 변수 | JSON Body |
| **인증** | Service Account | ID Token |
| **설정 저장소** | Firestore | PostgreSQL |
| **검증 로직** | 없음 | Gemini AI |
| **Fallback** | 없음 | Claude (비동기) |
| **BigQuery 업로드** | Job 내부 | Service 내부 |
| **타임아웃** | 1시간 | 1시간 |

---

## 🚀 배포 절차

### 1. 파일 업로드
```bash
# GCS 버킷에 업로드
gsutil cp airflow-dags/dags/dependencies/task_functions.py \
  gs://asia-northeast3-hyperlounge-d-d2f07cbc-bucket/dags/dependencies/

gsutil cp airflow-dags/dags/c8cd3500.py \
  gs://asia-northeast3-hyperlounge-d-d2f07cbc-bucket/dags/

gsutil cp airflow-dags/dags/cf526000.py \
  gs://asia-northeast3-hyperlounge-d-d2f07cbc-bucket/dags/
```

### 2. 동기화 대기
- Composer가 GCS에서 파일 감지: **1-3분**
- DAG Import Errors가 사라지면 완료

### 3. DAG 확인
- Airflow UI에서 c8cd3500, cf526000 DAG 확인
- Import 에러 없음 확인

---

## ✅ 테스트 체크리스트

### 정상 케이스
- [ ] llm_convert task 실행
- [ ] API 호출 성공 (200 OK)
- [ ] `status == "success"` 응답
- [ ] GCS에 `*_HAI.xlsx` 파일 생성
- [ ] BigQuery 테이블에 데이터 insert
- [ ] fileid_mapping_hai task 정상 실행
- [ ] downstream task (filter, converter, tag) 정상 실행

### 실패 케이스
- [ ] 검증 실패 시 task 실패 처리
- [ ] 타임아웃 시 에러 발생
- [ ] HTTP 에러 시 task 실패

---

## 🔮 향후 개선 사항

### 1. Fallback 동기화 (우선순위: 높음)

**현재:**
```python
# Service 응답
{
  "status": "validation_failed",
  "fallback_triggered": true  // 백그라운드 실행
}
```

**개선안:**
```python
# Service 내부에서 Fallback 완료까지 대기
if gemini_validation_failed:
    result = wait_for_fallback_job_completion()
    return {"status": "success", "fallback_used": true}
```

### 2. 배치 처리 최적화

**현재:** tenant_code 기준 모든 파일 처리

**개선안:**
- 병렬 처리 옵션 추가
- 특정 file_id, prompt_id만 처리

### 3. 모니터링 강화

- Cloud Run Service 로그 연동
- 변환 성공률 대시보드
- 타임아웃 알림

---

## 📚 참고 문서

- [Hyperlounge Python Convert 운영 가이드](./운영가이드.md)
- [LLM_CONVERT_API_CALL_GUIDE.md](./LLM_CONVERT_API_CALL_GUIDE.md)
- [CONVERTER_FAILURE_MONITORING.md](./CONVERTER_FAILURE_MONITORING.md)

---

## 🆘 트러블슈팅

### 문제: ModuleNotFoundError: No module named 'dependencies.task_functions'

**원인:** GCS 동기화 지연

**해결:** 2-3분 대기 후 자동 해결

---

### 문제: API request failed with status 401

**원인:** ID Token 인증 실패

**해결:**
```python
# Service Account 권한 확인
gcloud projects get-iam-policy hyperlounge-dev \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:*airflow*"
```

---

### 문제: TimeoutError after 3600 seconds

**원인:** 변환 작업이 1시간 초과

**해결:**
1. 파일 크기/복잡도 확인
2. Cloud Run Service 타임아웃 증가 검토
3. 대용량 파일은 별도 처리 고려

---

## 📞 연락처

- **개발자**: Junhyun Park (junhyun.park@hyperlounge.ai)
- **담당팀**: Platform Team

---

**최종 수정일**: 2025-11-17
