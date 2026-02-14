# LLM Convert API 방식 변경 (HTTP API → Cloud Run Job)

## 변경 일자
2025-11-07

## 변경 이유
- 기존 HTTP API 방식(`pre-convert-agent`)에서 Cloud Run Job 방식(`claude-agent-sdk-batch-job`)으로 전환
- 배치 처리에 더 적합한 Cloud Run Job 아키텍처 사용
- 비용 효율적 (실행 시에만 과금, 유휴 시간 비용 없음)

---

## 변경된 파일

### 1. `/airflow-dags/dags/dependencies/task_functions.py`

**함수**: `TaskFunctions.llm_convert_batch()`

**변경 전 (HTTP API 방식)**:
```python
def llm_convert_batch(params, **context):
    """
    1. conversion-targets API 호출
    2. 각 target에 대해 convert API를 병렬 호출
    """
    pre_convert_api_url = "https://pre-convert-agent-848582894134.asia-northeast3.run.app"

    # GET /api/v1/conversion-targets
    targets = fetch_targets(customer_code)

    # POST /api/v1/convert (병렬 실행)
    for target in targets:
        convert_single_target(target)
```

**변경 후 (Cloud Run Job 방식)**:
```python
def llm_convert_batch(params, **context):
    """
    Cloud Run Job을 실행하여 LLM 변환을 배치로 처리
    """
    from google.cloud import run_v2

    # Cloud Run Job 실행
    client = run_v2.JobsClient()
    job_path = f"projects/{project_id}/locations/{job_region}/jobs/{job_name}"

    # 환경 변수로 파라미터 전달
    env_vars = [
        run_v2.EnvVar(name="TENANT_CODE", value=customer_code),
        run_v2.EnvVar(name="BSDA", value=bsda),
        # FILE_ID, PROMPT_ID (optional)
    ]

    # Job 실행 및 완료 대기
    operation = client.run_job(request=execution_request)
    execution = operation.result(timeout=3600)
```

**주요 변경 사항**:
- HTTP 요청 대신 Google Cloud Run Job API 사용
- `google.cloud.run_v2.JobsClient` 사용
- 환경 변수로 파라미터 전달
- Job 완료까지 동기 대기 (최대 1시간 타임아웃)

---

### 2. `/airflow-dags/image/requirements.txt`

**추가된 의존성**:
```diff
+ google-cloud-run
```

Cloud Run Jobs API를 사용하기 위해 필요한 패키지 추가

---

## Cloud Run Job 정보

### Job 세부 정보
- **Job 이름**: `claude-agent-sdk-batch-job`
- **Project ID**: `hyperlounge-dev`
- **Region**: `asia-northeast1`
- **Image**: `asia-northeast1-docker.pkg.dev/hyperlounge-dev/cloud-run-source-deploy/claude-agent-sdk-batch-job:v1-*`

### Vertex AI 설정
- **Vertex AI Project**: `hyperlounge-ai`
- **Model**: `claude-sonnet-4-5@20250929`
- **Region**: `global`

### 환경 변수 (Job 실행 시 전달)
| 변수명 | 필수 여부 | 설명 | 예시 |
|--------|----------|------|------|
| `TENANT_CODE` | 필수 | 테넌트 코드 (customer_code) | `c8cd3500`, `cf526000` |
| `BSDA` | 필수 | 기준일시 (14자리 ingestion_id) | `20251107140000` |
| `FILE_ID` | 선택 | 특정 파일만 처리 | `WEEKLY_PROFIT_AND_LOSS` |
| `PROMPT_ID` | 선택 | 특정 프롬프트만 사용 | `weekly_summary` |

---

## 영향받는 DAG

### 1. 엘앤케이웰니스 (`c8cd3500.py`)
- **Customer Code**: `c8cd3500`
- **Customer Name**: `trinityspa`
- **Schedule**: 23:00 (KST)
- **LLM Transform 활성화**:
  - `shared_drive` (source_id: `sbb4e91e`)
  - `email` (LLM convert 결과물 처리)

**파이프라인 흐름**:
```
shared_drive: crawler → fileid_mapping → llm_convert_batch (분기)
                              ↓
                         filter → converter → tag

email: llm_convert_batch 완료 → fileid_mapping_hai → filter → converter → tag
```

### 2. 에이텍 (`cf526000.py`)
- **Customer Code**: `cf526000`
- **Customer Name**: `atec`
- **Schedule**: 21:00 (KST)
- **LLM Transform 활성화**:
  - `shared_drive` (source_id: `se19a4e4`)

**파이프라인 흐름**:
```
shared_drive: crawler → fileid_mapping → llm_convert_batch → fileid_mapping_hai → filter → converter → tag
```

---

## DAG CONFIG 설정

### 기본 설정 (자동 적용)
```python
CONFIG = {
    'customer_code': 'c8cd3500',  # 또는 'cf526000'
    'project_id': 'hyperlounge-dev',
    # ... 기타 설정
}
```

### 선택적 설정 (필요 시 추가)
```python
CONFIG = {
    # ... 기존 설정

    # Cloud Run Job 설정 (기본값이 있으므로 생략 가능)
    'llm_job_name': 'claude-agent-sdk-batch-job',  # default
    'llm_job_region': 'asia-northeast1',  # default

    # 특정 파일/프롬프트만 처리 (선택사항)
    'file_id': 'SPECIFIC_FILE_ID',  # 없으면 전체 파일 처리
    'prompt_id': 'SPECIFIC_PROMPT_ID',  # 없으면 모든 프롬프트 사용
}
```

---

## 배포 절차

### 1. Airflow Composer 이미지 업데이트
```bash
cd airflow-dags

# 새 requirements.txt 반영을 위한 이미지 재빌드 필요
# Composer 환경에 Python 패키지 설치
gcloud composer environments update [COMPOSER_ENV_NAME] \
  --location [LOCATION] \
  --update-pypi-packages-from-file image/requirements.txt
```

### 2. DAG 파일 배포
```bash
# DAG 파일 배포 (기존 방식과 동일)
./deploy_dags.sh
```

### 3. 테스트 실행
```bash
# Airflow UI에서 수동으로 DAG 실행
# 또는 gcloud 명령어로 트리거

# 1. 엘앤케이웰니스 테스트
gcloud composer environments run [COMPOSER_ENV_NAME] \
  --location [LOCATION] \
  dags trigger -- c8cd3500-20240517-1

# 2. 에이텍 테스트
gcloud composer environments run [COMPOSER_ENV_NAME] \
  --location [LOCATION] \
  dags trigger -- cf526000-20250926-1
```

---

## 모니터링 및 로그 확인

### Airflow Task 로그
```bash
# Airflow UI에서 확인
# Task: llm-convert-batch-shared_drive
```

### Cloud Run Job 실행 로그
```bash
# Job 실행 목록 확인
gcloud run jobs executions list \
  --job=claude-agent-sdk-batch-job \
  --region=asia-northeast1 \
  --limit=10

# 특정 실행의 로그 확인
gcloud logging read "resource.type=cloud_run_job \
  AND resource.labels.job_name=claude-agent-sdk-batch-job" \
  --limit=100 \
  --format=json
```

### Job 실행 상태 확인
```bash
# Job 상세 정보
gcloud run jobs describe claude-agent-sdk-batch-job \
  --region=asia-northeast1
```

---

## 트러블슈팅

### 문제 1: `google.cloud.run_v2` import 에러
**증상**: `ModuleNotFoundError: No module named 'google.cloud.run_v2'`

**원인**: `google-cloud-run` 패키지가 Composer 환경에 설치되지 않음

**해결**:
```bash
gcloud composer environments update [COMPOSER_ENV_NAME] \
  --location [LOCATION] \
  --update-pypi-package google-cloud-run
```

---

### 문제 2: Cloud Run Job 실행 권한 오류
**증상**: `Permission denied` 또는 `403 Forbidden`

**원인**: Composer 서비스 계정에 Cloud Run Job 실행 권한 없음

**해결**:
```bash
# Composer 서비스 계정에 Cloud Run Invoker 권한 부여
gcloud projects add-iam-policy-binding hyperlounge-dev \
  --member="serviceAccount:[COMPOSER_SERVICE_ACCOUNT]" \
  --role="roles/run.invoker"

# Cloud Run Developer 권한도 필요할 수 있음
gcloud projects add-iam-policy-binding hyperlounge-dev \
  --member="serviceAccount:[COMPOSER_SERVICE_ACCOUNT]" \
  --role="roles/run.developer"
```

---

### 문제 3: Job이 1시간 후 타임아웃
**증상**: `operation.result(timeout=3600)` 에서 타임아웃 발생

**원인**: Job 실행 시간이 1시간을 초과

**해결**:
1. Job의 `timeoutSeconds` 설정 확인 (현재: 3600초)
2. 필요시 타임아웃 시간 증가:
```python
# task_functions.py 수정
execution = operation.result(timeout=7200)  # 2시간으로 증가
```

---

### 문제 4: BSDA 형식 오류
**증상**: Job 로그에 `BSDA must be 8 or 14 digits` 에러

**원인**: BSDA 값이 올바른 형식이 아님

**확인**:
```python
# task_functions.py의 ingestion_id 생성 로직 확인
ingestion_id = DAGHelper._get_ingestion_id(
    params.get('transform_schedule', ['00']),
    context,
    params.get('day_of_week', '*')
)
# 결과: 14자리 문자열 (예: "20251107140000")
```

---

## 롤백 방법

변경사항을 롤백하려면:

### 1. `task_functions.py` 되돌리기
```bash
cd airflow-dags/dags/dependencies
git checkout HEAD~1 task_functions.py
```

### 2. `requirements.txt` 되돌리기
```bash
cd airflow-dags/image
git checkout HEAD~1 requirements.txt
```

### 3. 다시 배포
```bash
./deploy_dags.sh
```

---

## 참고 자료

### 프로젝트 문서
- Cloud Run Job README: `/mnt/c/Users/박준현/Desktop/hyperlounge-ontology/llm-convert/claude-agent-sdk-convert-batch/README_BATCH_JOB.md`
- Ontology 프로젝트 가이드: `/mnt/c/Users/박준현/Desktop/hyperlounge-ontology/CLAUDE.md`

### Google Cloud 문서
- [Cloud Run Jobs Documentation](https://cloud.google.com/run/docs/create-jobs)
- [Cloud Run Jobs API](https://cloud.google.com/python/docs/reference/run/latest)

### Job 배포 정보
- **Cloudbuild Config**: `llm-convert/claude-agent-sdk-convert-batch/cloudbuild.yaml`
- **Job 배포 명령어**:
```bash
cd /mnt/c/Users/박준현/Desktop/hyperlounge-ontology/llm-convert/claude-agent-sdk-convert-batch
gcloud builds submit . --config=cloudbuild.yaml --region=asia-northeast3 --project=hyperlounge-dev
```

---

## 체크리스트

배포 전 확인사항:

- [ ] `task_functions.py` 변경사항 확인
- [ ] `requirements.txt`에 `google-cloud-run` 추가 확인
- [ ] Cloud Run Job이 배포되어 있는지 확인
- [ ] Composer 서비스 계정 권한 확인
- [ ] DAG 파일 (`c8cd3500.py`, `cf526000.py`) 검토
- [ ] 테스트 계획 수립

배포 후 확인사항:

- [ ] Airflow Task 정상 실행 확인
- [ ] Cloud Run Job 실행 로그 확인
- [ ] 변환된 파일이 GCS에 정상 업로드되었는지 확인
- [ ] 후속 태스크 (filter, converter, tag) 정상 실행 확인
- [ ] BigQuery에 데이터 적재 확인

---

## 작성자
- Claude Code
- 2025-11-07
