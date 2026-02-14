# LLM Convert Cloud Run Job 호출 가이드

## 작성일
2025-11-07

---

## 목차
1. [호출 방식 개요](#호출-방식-개요)
2. [실제 API 호출 파라미터](#실제-api-호출-파라미터)
3. [환경 변수 전달](#환경-변수-전달)
4. [동작 흐름 (타임라인)](#동작-흐름-타임라인)
5. [대기 메커니즘](#대기-메커니즘)
6. [타임아웃 처리](#타임아웃-처리)
7. [코드 상세 분석](#코드-상세-분석)

---

## 호출 방식 개요

### ❌ HTTP API 호출이 아닙니다!

**이전 방식 (더 이상 사용 안 함)**:
```python
# HTTP POST 요청
response = requests.post(
    "https://pre-convert-agent-848582894134.asia-northeast3.run.app/api/v1/convert",
    json={"tenant_code": "c8cd3500", ...}
)
```

### ✅ Google Cloud Run Jobs API 호출 (gRPC)

**현재 방식**:
```python
from google.cloud import run_v2

# Cloud Run Jobs API 클라이언트 생성
client = run_v2.JobsClient()

# Job 실행 요청
operation = client.run_job(request=execution_request)

# Job 완료까지 대기
execution = operation.result(timeout=3600)
```

---

## 실제 API 호출 파라미터

### 1. Job 경로 (Job Path)

```python
job_path = f"projects/{project_id}/locations/{job_region}/jobs/{job_name}"
```

**엘앤케이웰니스 예시**:
```
projects/hyperlounge-dev/locations/asia-northeast1/jobs/claude-agent-sdk-batch-job
```

**에이텍 예시**:
```
projects/hyperlounge-dev/locations/asia-northeast1/jobs/claude-agent-sdk-batch-job
```

> 💡 두 고객사 모두 **같은 Job**을 사용합니다. `TENANT_CODE` 환경 변수로 구분!

---

### 2. 실행 요청 객체 (RunJobRequest)

```python
execution_request = run_v2.RunJobRequest(
    name=job_path,  # Job 경로
    overrides=run_v2.RunJobRequest.Overrides(
        container_overrides=[
            run_v2.RunJobRequest.Overrides.ContainerOverride(
                env=env_vars  # 환경 변수 배열
            )
        ]
    )
)
```

---

## 환경 변수 전달

### 필수 환경 변수

| 변수명 | 값 (예시) | 설명 | 출처 |
|--------|-----------|------|------|
| `TENANT_CODE` | `c8cd3500` | 고객사 코드 | `CONFIG['customer_code']` |
| `BSDA` | `20251107140000` | 기준일시 (14자리) | `transform_schedule` + Airflow 실행 시간 |

### 선택 환경 변수

| 변수명 | 값 (예시) | 설명 | 출처 |
|--------|-----------|------|------|
| `FILE_ID` | `WEEKLY_PROFIT_AND_LOSS` | 특정 파일만 처리 | `CONFIG['file_id']` (있으면) |
| `PROMPT_ID` | `weekly_summary` | 특정 프롬프트만 사용 | `CONFIG['prompt_id']` (있으면) |

---

### 코드 예시: 환경 변수 구성

```python
# 필수 환경 변수
env_vars = [
    run_v2.EnvVar(name="TENANT_CODE", value="c8cd3500"),
    run_v2.EnvVar(name="BSDA", value="20251107140000"),
]

# 선택적 환경 변수 추가
if file_id:
    env_vars.append(run_v2.EnvVar(name="FILE_ID", value=file_id))

if prompt_id:
    env_vars.append(run_v2.EnvVar(name="PROMPT_ID", value=prompt_id))
```

---

### BSDA 자동 계산

`BSDA`는 Airflow 실행 시간을 기준으로 자동 계산됩니다:

```python
# DAGHelper._get_ingestion_id() 사용
ingestion_id = DAGHelper._get_ingestion_id(
    params.get('transform_schedule', ['00']),  # ['14'] (UTC 14시)
    context,                                    # Airflow context
    params.get('day_of_week', '*')             # "1,2,3,4,5,6,0"
)

# 결과: "20251107140000" (YYYYMMDDHHMMSS 형식)
bsda = ingestion_id
```

**예시**:
- Airflow DAG 실행 시간: 2025-11-07 14:00:00 UTC
- `transform_schedule`: `['14']`
- 계산된 BSDA: `20251107140000`

---

## 동작 흐름 (타임라인)

### 전체 프로세스

```
┌─────────────────────────────────────────────────────────────────┐
│ Airflow Task: llm-convert-batch-shared_drive                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ T+0초: Task 시작
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │ client.run_job(request)                 │ T+1초
        │   - Job 경로 전달                       │
        │   - 환경 변수 전달                      │
        └─────────────────────────────────────────┘
                              │
                              │ Cloud Run Job 컨테이너 시작
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │ operation.result(timeout=3600) 🔄       │ T+2초
        │                                         │
        │ ⚠️  Airflow Worker가 여기서 BLOCKING! │
        └─────────────────────────────────────────┘
                              │
                              │ (대기 중...)
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Cloud Run Job 실행 중...                                        │
│   1. PostgreSQL에서 conversion targets 조회                     │
│   2. GCS에서 원본 Excel 파일 다운로드                           │
│   3. Claude Vertex AI로 파일 변환                               │
│   4. 변환된 파일 GCS에 업로드                                   │
│   5. Job 완료                                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ T+1800초 (예: 30분 소요)
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │ operation.result() 반환 ✅              │
        │   - execution.succeeded_count           │
        │   - execution.failed_count              │
        │   - execution.name                      │
        └─────────────────────────────────────────┘
                              │
                              │ Airflow Worker 재개
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │ Airflow Task 완료                       │ T+1801초
        └─────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────┐
        │ 다음 Task 시작                          │
        │   - fileid_mapping_hai                  │
        │   - filter                              │
        │   - converter                           │
        │   - tag                                 │
        └─────────────────────────────────────────┘
```

---

## 대기 메커니즘

### `operation.result(timeout=3600)`의 의미

```python
# Job 실행 (비동기 작업 시작)
operation = client.run_job(request=execution_request)
# ↑ 이 시점: Cloud Run Job이 시작됨 (컨테이너 생성)
# ↑ 반환값: Operation 객체 (Long-running operation)

# Job 완료까지 대기 (동기 대기 - BLOCKING)
execution = operation.result(timeout=3600)
# ↑ 이 시점: Airflow worker가 멈춤 (다른 일 못 함)
# ↑ 최대 3600초 (1시간) 대기
# ↑ Job이 완료되면 즉시 반환 (30분에 끝나면 30분만 대기)
# ↑ 1시간 초과 시 TimeoutError 발생
```

---

### 동기 vs 비동기 비교

#### 현재 방식 (동기 대기) ✅

```python
operation = client.run_job(request)
execution = operation.result(timeout=3600)  # ← BLOCKING
# Airflow worker가 여기서 멈춤
# Job이 끝날 때까지 다른 일 못 함
```

**장점**:
- 순서 보장 (Job 완료 후 다음 task 실행)
- 코드 단순
- 에러 처리 명확

**단점**:
- Worker 리소스 낭비 (대기만 함)

---

#### 비동기 방식 (미구현)

```python
# Task 1: Job 실행만
operation = client.run_job(request)
execution_name = operation.name
# 바로 완료 (다음 task로 진행 안 함)

# Task 2: Sensor로 주기적 체크
sensor = CloudRunJobSensor(execution_name)
sensor.poke()  # 완료될 때까지 주기적으로 체크

# Task 3: 후속 작업
next_task()
```

**장점**:
- Worker가 blocking 안 됨

**단점**:
- Sensor 구현 필요
- DAG 구조 복잡해짐

---

### 왜 동기 방식을 선택했는가?

1. **배치 작업 특성**: 야간 배치 (21시, 23시)
2. **실행 빈도**: 하루 1회
3. **순서 보장 필요**: 다음 task가 변환 결과 파일에 의존
4. **단순성 우선**: 유지보수 용이
5. **리소스 여유**: Composer 환경에 worker 충분

**결론**: 배치 작업에서는 동기 방식이 합리적 ✅

---

## 타임아웃 처리

### 타임아웃 시나리오

```python
# 시나리오 1: 정상 완료 (30분 소요) ✅
T+0초:    operation.result(timeout=3600) 호출
T+1800초: Job 완료, 즉시 반환
결과:     Airflow Task SUCCESS

# 시나리오 2: 타임아웃 (1시간 10분 소요) ❌
T+0초:    operation.result(timeout=3600) 호출
T+3600초: 타임아웃! TimeoutError 발생
결과:     Airflow Task FAILED

# 시나리오 3: Job 자체 실패 ❌
T+0초:    operation.result(timeout=3600) 호출
T+1200초: Job이 에러로 종료 (20분 소요)
결과:     execution.failed_count > 0
         → AirflowFailException 발생
         → Airflow Task FAILED
```

---

### 타임아웃 값 조정

필요시 타임아웃을 늘릴 수 있습니다:

```python
# 현재: 1시간
execution = operation.result(timeout=3600)

# 변경 예시: 2시간
execution = operation.result(timeout=7200)

# 변경 예시: 30분
execution = operation.result(timeout=1800)
```

**권장 타임아웃**:
- 일반적인 경우: `3600` (1시간)
- 대량 파일 처리: `7200` (2시간)
- 소량 파일 테스트: `1800` (30분)

---

## 코드 상세 분석

### task_functions.py의 llm_convert_batch()

```python
@staticmethod
def llm_convert_batch(params, **context):
    """
    Cloud Run Job을 실행하여 LLM 변환을 배치로 처리합니다.
    """
    from google.cloud import run_v2
    import time

    # ─────────────────────────────────────────────────────────
    # 1. 파라미터 추출
    # ─────────────────────────────────────────────────────────
    customer_code = params.get("customer_code")        # CONFIG에서 자동 전달
    project_id = params.get("project_id", "hyperlounge-dev")
    job_name = params.get("llm_job_name", "claude-agent-sdk-batch-job")
    job_region = params.get("llm_job_region", "asia-northeast1")
    file_id = params.get("file_id")      # 선택사항
    prompt_id = params.get("prompt_id")  # 선택사항

    # ─────────────────────────────────────────────────────────
    # 2. BSDA 자동 계산
    # ─────────────────────────────────────────────────────────
    ingestion_id = DAGHelper._get_ingestion_id(
        params.get('transform_schedule', ['00']),
        context,
        params.get('day_of_week', '*')
    )
    bsda = ingestion_id  # 예: "20251107140000"

    # ─────────────────────────────────────────────────────────
    # 3. Cloud Run Jobs API 클라이언트 생성
    # ─────────────────────────────────────────────────────────
    client = run_v2.JobsClient()
    job_path = f"projects/{project_id}/locations/{job_region}/jobs/{job_name}"
    # 예: "projects/hyperlounge-dev/locations/asia-northeast1/jobs/claude-agent-sdk-batch-job"

    # ─────────────────────────────────────────────────────────
    # 4. 환경 변수 구성
    # ─────────────────────────────────────────────────────────
    env_vars = [
        run_v2.EnvVar(name="TENANT_CODE", value=customer_code),
        run_v2.EnvVar(name="BSDA", value=bsda),
    ]

    if file_id:
        env_vars.append(run_v2.EnvVar(name="FILE_ID", value=file_id))

    if prompt_id:
        env_vars.append(run_v2.EnvVar(name="PROMPT_ID", value=prompt_id))

    # ─────────────────────────────────────────────────────────
    # 5. 실행 요청 객체 생성
    # ─────────────────────────────────────────────────────────
    execution_request = run_v2.RunJobRequest(
        name=job_path,
        overrides=run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    env=env_vars
                )
            ]
        )
    )

    # ─────────────────────────────────────────────────────────
    # 6. Cloud Run Job 실행
    # ─────────────────────────────────────────────────────────
    logging.info(f"Executing Cloud Run Job: {job_path}")
    operation = client.run_job(request=execution_request)
    # ↑ 이 순간: Cloud Run Job 컨테이너가 시작됨
    # ↑ 반환값: Operation 객체 (비동기 작업)

    # ─────────────────────────────────────────────────────────
    # 7. Job 완료까지 대기 (BLOCKING)
    # ─────────────────────────────────────────────────────────
    logging.info(f"Job execution started. Waiting for completion...")

    execution = operation.result(timeout=3600)  # 1시간 타임아웃
    # ↑ Airflow worker가 여기서 멈춤!
    # ↑ Cloud Run Job이 완료되면 즉시 반환
    # ↑ 1시간 초과 시 TimeoutError

    execution_name = execution.name
    logging.info(f"Job execution completed: {execution_name}")

    # ─────────────────────────────────────────────────────────
    # 8. 실행 결과 확인
    # ─────────────────────────────────────────────────────────
    if execution.succeeded_count and execution.succeeded_count > 0:
        logging.info(f"✓ Job succeeded: {execution.succeeded_count} task(s) completed")

        # 실행 상세 정보 조회
        executions_client = run_v2.ExecutionsClient()
        execution_detail = executions_client.get_execution(name=execution_name)

        # 결과 객체 생성
        result = {
            "status": "success",
            "execution_name": execution_name,
            "succeeded_count": execution.succeeded_count,
            "failed_count": execution.failed_count or 0,
            "completion_time": str(execution_detail.completion_time) if hasattr(execution_detail, 'completion_time') else None
        }

        # XCom에 결과 저장 (다음 task에서 참조 가능)
        context['ti'].xcom_push(key="llm_convert_job_result", value=result)

        logging.info("=" * 80)
        logging.info(f"LLM Batch Conversion Job Summary:")
        logging.info(f"  Execution: {execution_name}")
        logging.info(f"  Succeeded: {result['succeeded_count']}")
        logging.info(f"  Failed: {result['failed_count']}")
        logging.info("=" * 80)

        return result
    else:
        # Job 실패
        error_msg = f"Job execution failed or no tasks succeeded. Failed count: {execution.failed_count}"
        logging.error(error_msg)
        raise AirflowFailException(error_msg)
```

---

## gcloud 명령어 등가 표현

Python 코드와 동일한 동작을 gcloud CLI로 실행:

```bash
# 엘앤케이웰니스 예시
gcloud run jobs execute claude-agent-sdk-batch-job \
  --region=asia-northeast1 \
  --project=hyperlounge-dev \
  --set-env-vars="TENANT_CODE=c8cd3500,BSDA=20251107140000"

# 에이텍 예시
gcloud run jobs execute claude-agent-sdk-batch-job \
  --region=asia-northeast1 \
  --project=hyperlounge-dev \
  --set-env-vars="TENANT_CODE=cf526000,BSDA=20251107120000"

# 특정 파일만 처리
gcloud run jobs execute claude-agent-sdk-batch-job \
  --region=asia-northeast1 \
  --project=hyperlounge-dev \
  --set-env-vars="TENANT_CODE=c8cd3500,BSDA=20251107140000,FILE_ID=WEEKLY_PROFIT_AND_LOSS"

# 대기 없이 실행 (비동기)
gcloud run jobs execute claude-agent-sdk-batch-job \
  --region=asia-northeast1 \
  --project=hyperlounge-dev \
  --set-env-vars="TENANT_CODE=c8cd3500,BSDA=20251107140000" \
  --async
```

---

## Cloud Run Job이 받는 환경 변수 (컨테이너 내부)

### job_main.py에서 환경 변수 읽기

```python
import os

# 필수 환경 변수
tenant_code = os.getenv("TENANT_CODE")  # "c8cd3500"
bsda = os.getenv("BSDA")                # "20251107140000"

# 선택 환경 변수
file_id = os.getenv("FILE_ID")          # None 또는 "WEEKLY_PROFIT_AND_LOSS"
prompt_id = os.getenv("PROMPT_ID")      # None 또는 "weekly_summary"

# Validation
if not tenant_code:
    logger.error("❌ TENANT_CODE environment variable is required")
    sys.exit(1)

if not bsda:
    logger.error("❌ BSDA environment variable is required")
    sys.exit(1)

# BSDA 형식 검증
if not (bsda.isdigit() and len(bsda) in [8, 14]):
    logger.error(f"❌ BSDA must be 8 or 14 digits, got: {bsda}")
    sys.exit(1)
```

---

## 실행 예시

### 엘앤케이웰니스 (c8cd3500)

**DAG 트리거**:
```bash
gcloud composer environments run composer-dev \
  --location asia-northeast3 \
  dags trigger -- c8cd3500-20240517-1
```

**Cloud Run Job 실행 (자동)**:
```
Job Path: projects/hyperlounge-dev/locations/asia-northeast1/jobs/claude-agent-sdk-batch-job

Environment Variables:
  TENANT_CODE=c8cd3500
  BSDA=20251107140000
```

**로그 예시**:
```
[2025-11-07 14:00:01] INFO - Starting Cloud Run Job for LLM batch conversion
[2025-11-07 14:00:01] INFO -   Project: hyperlounge-dev
[2025-11-07 14:00:01] INFO -   Job Name: claude-agent-sdk-batch-job
[2025-11-07 14:00:01] INFO -   Region: asia-northeast1
[2025-11-07 14:00:01] INFO -   Tenant Code: c8cd3500
[2025-11-07 14:00:01] INFO -   BSDA: 20251107140000
[2025-11-07 14:00:02] INFO - Executing Cloud Run Job: projects/hyperlounge-dev/locations/asia-northeast1/jobs/claude-agent-sdk-batch-job
[2025-11-07 14:00:02] INFO - Job execution started. Waiting for completion...
[2025-11-07 14:30:15] INFO - Job execution completed: claude-agent-sdk-batch-job-abc123
[2025-11-07 14:30:15] INFO - ✓ Job succeeded: 1 task(s) completed
[2025-11-07 14:30:15] INFO - ================================================================================
[2025-11-07 14:30:15] INFO - LLM Batch Conversion Job Summary:
[2025-11-07 14:30:15] INFO -   Execution: claude-agent-sdk-batch-job-abc123
[2025-11-07 14:30:15] INFO -   Succeeded: 1
[2025-11-07 14:30:15] INFO -   Failed: 0
[2025-11-07 14:30:15] INFO - ================================================================================
```

---

## 요약

| 항목 | 내용 |
|------|------|
| **호출 방식** | Google Cloud Run Jobs API (gRPC) |
| **API 클라이언트** | `google.cloud.run_v2.JobsClient` |
| **메서드** | `client.run_job(request)` |
| **필수 파라미터** | Job 경로 (`name`), 환경 변수 (`overrides`) |
| **환경 변수** | `TENANT_CODE`, `BSDA` (필수) + `FILE_ID`, `PROMPT_ID` (선택) |
| **대기 방식** | 동기 대기 (blocking) |
| **대기 메서드** | `operation.result(timeout=3600)` |
| **대기 대상** | Cloud Run Job 컨테이너 종료 |
| **타임아웃** | 3600초 (1시간) |
| **자동 전달 정보** | `customer_code`, `project_id`, `transform_schedule` |
| **추가 설정 불필요** | ✅ CONFIG에 이미 모든 정보 있음 |

---

## 참고 자료

- [Cloud Run Jobs API 문서](https://cloud.google.com/python/docs/reference/run/latest/google.cloud.run_v2.services.jobs.JobsClient)
- [RunJobRequest 문서](https://cloud.google.com/python/docs/reference/run/latest/google.cloud.run_v2.types.RunJobRequest)
- [Long-running operations](https://cloud.google.com/python/docs/reference/run/latest/google.api_core.operation.Operation)

---

## 작성자
- Claude Code
- 2025-11-07
