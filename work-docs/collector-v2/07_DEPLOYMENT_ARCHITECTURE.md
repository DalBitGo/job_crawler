# Converter 배포 아키텍처

> **작성일**: 2026-02-09
> **목적**: Cloud Run Job과 Cloud Run Service 배포 방식 이해 및 DAG 연동 가이드

---

## 1. 개요

Converter는 두 가지 방식으로 배포되어 있습니다:

| 배포 방식 | 서비스명 예시 | 용도 |
|----------|-------------|------|
| **Cloud Run Job** | `job-convert-4-2` | 배치 처리, 대량 파일 |
| **Cloud Run Service** | `convert-excel-4-0` | HTTP API, 단일 파일 |

```
┌────────────────────────────────────────────────────────────┐
│                      Airflow DAG                           │
│              (run_gcs_file_converters 호출)                 │
└───────────────────────────┬────────────────────────────────┘
                            │
             ┌──────────────┴──────────────┐
             │      force_job 파라미터?     │
             └──────────────┬──────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
    force_job=True                      force_job=False
          │                                   │
          ▼                                   ▼
┌─────────────────────┐           ┌─────────────────────┐
│   Cloud Run Job     │           │  Cloud Run Service  │
│  (job-convert-4-2)  │           │ (convert-excel-4-0) │
│                     │           │                     │
│  - 배치 처리         │           │  - HTTP API         │
│  - TASK_COUNT 병렬   │           │  - Auto-scale       │
└─────────────────────┘           └─────────────────────┘
```

---

## 2. Cloud Run Job 방식

### 2.1 동작 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│  Airflow: convert_gcs_files_with_job()                              │
│                                                                     │
│  1. 변환할 items를 GCS에 분할 저장 (split_convert_items)             │
│     → gs://hyperlounge-{customer}/convert_job/{source}/{ingestion}/ │
│  2. Cloud Run Job 실행 (TASK_COUNT = 파일 수)                        │
│  3. 폴링하며 완료 대기 (check_run_job_execution_tasks_state)         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼ TASK_COUNT개 컨테이너 동시 시작
┌──────────────────────────────────────────────────────────────────────┐
│  Cloud Run Job (각 Task = 독립 컨테이너)                              │
│                                                                      │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐          │
│  │ Task 0         │  │ Task 1         │  │ Task 2         │ ...      │
│  │ TASK_INDEX=0   │  │ TASK_INDEX=1   │  │ TASK_INDEX=2   │          │
│  │                │  │                │  │                │          │
│  │ items[0] 처리   │  │ items[1] 처리   │  │ items[2] 처리   │          │
│  └────────────────┘  └────────────────┘  └────────────────┘          │
│                                                                      │
│  ※ 컨버터 코드 직접 실행 (Cloud Function 호출 안함!)                  │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 핵심 코드

**Entry Point** (`collector/deploy/converter_job/main.py`):
```python
# Cloud Run Job 환경변수로 Task 식별
TASK_INDEX = int(os.getenv("CLOUD_RUN_TASK_INDEX", 0))
TASK_COUNT = int(os.getenv("CLOUD_RUN_TASK_COUNT", 1))

# GCS에서 분할된 items 로드
items = get_from_gcs(bucket_name, items_path, is_json=True)

# 자기 Task에 해당하는 items만 처리
convert_gcs_files_with_task(
    convert_params=items[TASK_INDEX],  # ← TASK_INDEX로 선택
    job_params={
        "job_id": RUN_EXECUTION,
        "task_index": TASK_INDEX,
        "items_path": items_path
    }
)
```

**Airflow 호출** (`collector/excel/run_converter.py`):
```python
def convert_gcs_files_with_job(customer_code, source_type, ingestion_id,
                                items, job_name, task_timeout="1200s"):
    # 1. items 분할
    total_tasks_count = get_total_tasks_count(items)
    split_items = split_convert_items(items, total_tasks_count)

    # 2. GCS에 저장
    items_path = download_items(customer_code, source_type, ingestion_id, split_items)

    # 3. Job 실행
    job = run_job(
        project=PROJECT_NAME,
        job_name=job_name,
        tasks=total_tasks_count,  # ← 이게 TASK_COUNT
        env_vars=[
            {"name": "customer_code", "value": customer_code},
            {"name": "items_path", "value": items_path}
        ]
    )

    # 4. 완료 대기
    check_run_job_execution_tasks_state(...)
```

### 2.3 배포

```bash
# collector/deploy/converter_job/
./build_docker.sh -t 4-2 cloud-run-job convert

# 결과: job-convert-4-2 이미지 생성
# → Artifact Registry에 푸시됨
```

---

## 3. Cloud Run Service 방식

### 3.1 동작 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│  Airflow: convert_gcs_files_with_gcf()                              │
│                                                                     │
│  → call_gcf_converter() 호출                                         │
│  → HTTP POST로 각 파일별 요청 병렬 전송 (parallel_count 만큼)         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼ HTTP 요청 N개 동시 전송
┌──────────────────────────────────────────────────────────────────────┐
│  Cloud Run Service (auto-scaling)                                    │
│                                                                      │
│  POST /convert_excel                                                 │
│  {                                                                   │
│    "bucket_name": "hyperlounge-c8cd3500",                            │
│    "src_path": "board/s4da50eb/filter/file_id",                      │
│    "dst_dir": "ext/cvt_id",                                          │
│    "config_json": {...},                                             │
│    "cvt_id": "convert_config_id",                                    │
│    "ingestion_id": "20240101120000"                                  │
│  }                                                                   │
│                                                                      │
│  → 요청 수에 따라 인스턴스 자동 스케일 (max 1000)                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 핵심 코드

**Entry Point** (`collector/deploy/converter/main.py`):
```python
def convert_excel(request):
    request_json = request.get_json()

    bucket_name = request_json['bucket_name']
    src_path = request_json['src_path']
    dst_dir = request_json['dst_dir']
    config_json = request_json['config_json']

    # 컨버터 실행
    res_items = run_gcs_file_converter_for_cloud_function(
        bucket_name, src_path, dst_dir, config_json,
        ingestion_id=ingestion_id,
        org_file_name=org_file_name,
        cvt_id=cvt_id
    )

    return make_response(json.dumps({
        "result": "succeed",
        "convert_items": res_items['convert_items']
    }))
```

**Airflow 호출** (`collector/excel/call_gcf_entry.py`):
```python
def call_gcf_converter(post_params, gcf_url, parallel_count, history_template):
    call_cloud_function(
        param_list=post_params,
        gcf_url=gcf_url,
        connect_limit=parallel_count,  # ← 동시 요청 수
        timeout_seconds=1200,
        success_callback=lambda res, res_dat, params:
            history_template.post_history(...)
    )
```

### 3.3 배포

```bash
# collector/deploy/converter/
./deploy.sh

# deploy.sh 내부 설정:
# version=4-0
# function_name=convert-excel-4-0
# max_instance=1000
# memory=2048MB
# timeout=1200
```

---

## 4. 비교표

| 구분 | Cloud Run Job | Cloud Run Service |
|------|---------------|-------------------|
| **배포 이름** | `job-convert-4-2` | `convert-excel-4-0` |
| **호출 함수** | `convert_gcs_files_with_job()` | `convert_gcs_files_with_gcf()` |
| **병렬화 방식** | TASK_COUNT개 컨테이너 | HTTP 요청별 auto-scale |
| **인스턴스 관리** | 명시적 (파일 수 = Task 수) | 자동 (요청량 기반) |
| **비용 모델** | 실행 시간 기반 | 요청당 + 실행 시간 |
| **타임아웃** | 최대 1시간 | 최대 60분 |
| **Airflow 연동** | 폴링으로 완료 대기 | callback으로 결과 처리 |
| **적합한 케이스** | 대량 파일 배치 | 단일/소량 파일, API |

---

## 5. DAG에서 호출 방법

### 5.1 run_gcs_file_converters() 사용

```python
from collector.excel.run_converter import run_gcs_file_converters

# Cloud Run Job 사용 (권장 - 대량 파일)
run_gcs_file_converters(
    customer_code="c8cd3500",
    source_type="board",
    ingestion_id="20240101120000",
    api_svr_url=API_SERVER_URL,
    force_job=True,              # ← Cloud Run Job 사용
    job_name="job-convert-4-2",  # ← Job 이름 (None이면 Firestore에서 조회)
    task_timeout="1200s"
)

# Cloud Run Service 사용
run_gcs_file_converters(
    customer_code="c8cd3500",
    source_type="board",
    ingestion_id="20240101120000",
    api_svr_url=API_SERVER_URL,
    force_job=False,             # ← Cloud Run Service 사용
    gcf_url="https://...",       # ← Service URL (None이면 Firestore에서 조회)
    parallel_cnt=10              # ← 동시 요청 수
)
```

### 5.2 버전 정보 조회

Job 이름이나 Service URL은 Firestore의 version 문서에서 조회됩니다:

```python
# collector/excel/run_converter.py
def get_convert_gcf_url(api_svr_url, customer_code, gcf_type):
    versions_info = get_versions_info(customer_code, api_svr_url)

    if gcf_type == "service":
        return versions_info[0].get("gcf_convert_url")
    elif gcf_type == "job":
        return versions_info[0].get("convert_job_name")
```

Firestore 문서 예시:
```json
{
  "customer_code": "c8cd3500",
  "gcf_convert_url": "https://convert-excel-4-0-xxx.run.app",
  "convert_job_name": "job-convert-4-2"
}
```

---

## 6. 병렬성 예시

### 파일 10개 변환 시

**Cloud Run Job:**
```
TASK_COUNT=10으로 Job 실행
    │
    ├── Container 0: items[0] 처리 ──→ 완료
    ├── Container 1: items[1] 처리 ──→ 완료
    ├── Container 2: items[2] 처리 ──→ 완료
    │   ...
    └── Container 9: items[9] 처리 ──→ 완료

→ 10개 컨테이너 동시 실행, 가장 느린 것 기준으로 종료
```

**Cloud Run Service (parallel_count=5):**
```
요청 5개 동시 전송
    │
    ├── [1,2,3,4,5] 완료 대기
    │
    └── 완료되면 다음 5개 [6,7,8,9,10] 전송

→ 5개씩 나눠서 처리 (parallel_count 제한)
```

---

## 7. 관련 파일 경로

```
collector/
├── excel/
│   ├── run_converter.py              # Airflow 연동 함수들
│   └── call_gcf_entry.py             # Cloud Function 호출
│
└── deploy/
    ├── converter/                     # Cloud Run Service
    │   ├── main.py                   # Entry point
    │   ├── deploy.sh                 # 배포 스크립트
    │   └── requirements.txt
    │
    └── converter_job/                 # Cloud Run Job
        ├── main.py                   # Entry point
        ├── build_docker.sh           # Docker 빌드
        ├── Dockerfile
        └── requirements.txt
```

---

## 8. 주의사항

### 8.1 둘은 독립적

- **Cloud Run Job은 Cloud Run Service를 호출하지 않음**
- 둘 다 같은 컨버터 코드 (`GCSFileConverter`)를 직접 실행
- 호출 방식만 다름 (컨테이너 vs HTTP)

### 8.2 버전 관리

```
Cloud Run Service: version=4-0 → convert-excel-4-0
Cloud Run Job:     -t 4-2      → job-convert-4-2

※ 버전이 다를 수 있음 - 각각 독립 배포
```

### 8.3 타임아웃

- Job: `task_timeout` 파라미터로 설정 (기본 1200s)
- Service: `deploy.sh`의 `--timeout` 옵션 (기본 1200s)

---

## 9. GCS 버킷 구조

### 9.1 버킷 개요

각 고객사별로 `hyperlounge-{customer_code}` 버킷이 존재합니다:

```
gs://hyperlounge-c8cd3500/
│
├── board/                              # 게시판 크롤링
│   └── {source_id}/
│       └── crawl/                      # 크롤링된 파일
│           └── {file_id}               ← 실제 Excel 파일 (rename됨)
│
├── ext/                                # 변환 결과물
│   └── {cvt_meta_id}/
│       ├── {sheet}_{table}.parquet     ← CVT_TBL_DATA
│       ├── {sheet}_{table}.csv
│       └── tags.json                   ← TAG_* 결과
│
├── convert_job/                        # Job 메타데이터 (임시)
│   └── {source_type}/
│       └── {ingestion_id}/
│           └── {timestamp}             ← 작업 지시 JSON
│
├── shared_drive/                       # 공유 드라이브 수집
│   └── {source_id}/crawl/...
│
├── email/                              # 이메일 수집
│   └── {source_id}/crawl/...
│
├── rpa/                                # RPA 수집
│   └── {source_id}/crawl/...
│
└── pc/                                 # PC 수집
    └── {source_id}/crawl/...
```

**참고:** 코드에서 `filter_path`라는 변수가 있지만, 이는 실제로 `crawl/` 경로를 가리킵니다.
(collect-manager API: `filter_path = get_crawl_path_pattern()` → `{source_type}/{source_id}/crawl`)
별도의 `filter/` 폴더는 존재하지 않으며, 필터링은 메타데이터(DB/Firestore)로 관리됩니다.

### 9.2 convert_job 경로의 내용

`convert_job/` 경로에 저장되는 것은 **원본 파일이 아니라 메타데이터 JSON**입니다:

```json
[
  {  // items[0] - Task 0이 처리할 항목들
    "bucket_name": "hyperlounge-c8cd3500",
    "filter_path": "board/{SOURCE_ID}/filter/{INGESTION_ID}",
    "convert_path": "ext",
    "sources": [
      {
        "id": "s4da50eb",
        "convert_items": [
          {
            "file_id": "fb7c967e12de",        // ← 파일 ID (실제 파일 아님)
            "file_name": "원본파일명.xlsx",    // ← 원본 파일명
            "config": {...},                   // ← 변환 설정
            "filter_condition_id": "...",
            "convert_config_id": "..."
          }
        ]
      }
    ]
  },
  { ... },  // items[1] - Task 1이 처리할 항목들
  { ... }   // items[2] - Task 2이 처리할 항목들
]
```

### 9.3 파일 흐름

```
1. 크롤링 (Crawler)
   ┌─────────────────┐
   │ 원본파일.xlsx    │
   └────────┬────────┘
            │ 다운로드 + rename
            ▼
   {source_type}/{source_id}/crawl/{file_id}
   (파일명이 file_id 해시값으로 변경됨)

2. 필터링 (Filter) - 메타데이터 레벨
   ┌─────────────────────────────────────────┐
   │ 필터 조건 확인 (파일명 패턴, 날짜 등)     │
   │ → 조건 만족하는 file_id 목록 생성        │
   │ → DB/Firestore에 기록                   │
   └─────────────────────────────────────────┘
   ※ 파일 복사 없음! crawl/에 그대로 유지

3. 변환 Job 시작 (Airflow)
   ┌─────────────────────────────────────────┐
   │ "어떤 파일 변환할지" 메타데이터 생성      │
   │ - file_id 목록                          │
   │ - 각 파일의 config                       │
   └────────────────────┬────────────────────┘
                        │ JSON 저장
                        ▼
   convert_job/{source_type}/{ingestion}/{timestamp}

4. Cloud Run Job 실행
   ┌─────────────────────────────────────────┐
   │ 각 Task가 자기 메타데이터 읽음           │
   │ items[TASK_INDEX]                       │
   └────────────────────┬────────────────────┘
                        │ crawl/에서 파일 읽어서 변환
                        ▼
   crawl/{file_id} → ext/{cvt_meta_id}/

5. 결과 저장
   ┌─────────────────────────────────────────┐
   │ ext/{cvt_meta_id}/                      │
   │ ├── {sheet}_{table}.parquet             │
   │ ├── {sheet}_{table}.csv                 │
   │ └── tags.json                           │
   └─────────────────────────────────────────┘
```

### 9.4 경로별 역할 요약

| 경로 | 내용 | 생성 시점 |
|------|------|----------|
| `{source_type}/{source_id}/crawl/` | 크롤링된 원본 Excel (file_id로 rename) | Crawler |
| `convert_job/` | 작업 지시 메타데이터 JSON | Airflow (Job 시작 시) |
| `ext/` | 변환 결과물 (Parquet, CSV, JSON) | Converter |

---

## 10. 파이프라인 메타데이터 관리

### 10.1 전체 흐름과 History 테이블

파일은 복사되지 않고, **BigQuery History 테이블**로 상태를 추적합니다:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Airflow DAG                                     │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐
│   1. Crawler      │────▶│   2. Filter       │────▶│   3. Convert      │
│                   │     │                   │     │                   │
│ 파일 다운로드      │     │ 조건 체크         │     │ Excel → Parquet   │
│ + rename          │     │ (파일 복사 없음)   │     │                   │
└───────────────────┘     └───────────────────┘     └───────────────────┘
        │                         │                         │
        ▼                         ▼                         ▼
┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐
│ crawl_job_history │     │filter_job_history │     │convert_job_history│
│    (BigQuery)     │     │    (BigQuery)     │     │    (BigQuery)     │
└───────────────────┘     └───────────────────┘     └───────────────────┘
```

### 10.2 각 단계별 상세

#### 1단계: Crawler

```
┌─────────────────────────────────────────────────────────────────┐
│  Crawler 실행                                                   │
│                                                                 │
│  1. 원본 파일 다운로드 (게시판, 이메일, 공유드라이브 등)          │
│  2. 파일명을 file_id(해시)로 rename                             │
│  3. GCS에 저장: {source_type}/{source_id}/crawl/{file_id}       │
│  4. crawl_job_history에 기록                                    │
│     - file_id                                                   │
│     - file_name (원본 파일명)                                   │
│     - gcs_path                                                  │
│     - status: "success"                                         │
└─────────────────────────────────────────────────────────────────┘
```

#### 2단계: Filter

```
┌─────────────────────────────────────────────────────────────────┐
│  Filter 실행                                                    │
│                                                                 │
│  1. crawl_job_history에서 새로 수집된 파일 목록 조회             │
│  2. 각 파일에 대해 filter_condition 조건 체크                   │
│     - 파일명 패턴 (정규식)                                      │
│     - 수집 날짜                                                 │
│     - 기타 조건                                                 │
│  3. 조건 만족 시 filter_job_history에 기록                      │
│     - filter_condition_id                                       │
│     - file_id                                                   │
│     - file_name                                                 │
│     - gcs_path                                                  │
│     - status: "success"                                         │
│                                                                 │
│  ※ 파일 복사/이동 없음! 메타데이터만 기록                        │
└─────────────────────────────────────────────────────────────────┘
```

#### 3단계: Convert

```
┌─────────────────────────────────────────────────────────────────┐
│  Convert 실행                                                   │
│                                                                 │
│  1. filter_job_history에서 success 항목 조회                    │
│     → get_success_item_ids()                                    │
│     → (filter_condition_id, file_id, file_name, gcs_path) 목록  │
│                                                                 │
│  2. 각 file_id에 대해:                                          │
│     - crawl/{file_id}에서 파일 읽기                             │
│     - config에 따라 변환                                        │
│     - ext/{cvt_meta_id}/에 결과 저장                            │
│                                                                 │
│  3. convert_job_history에 기록                                  │
│     - convert_config_id                                         │
│     - file_id                                                   │
│     - status: "success" / "fail"                                │
└─────────────────────────────────────────────────────────────────┘
```

### 10.3 History 테이블 구조

| 테이블 | 주요 필드 | 용도 |
|--------|----------|------|
| `crawl_job_history` | file_id, file_name, gcs_path, status | 크롤링된 파일 추적 |
| `filter_job_history` | filter_condition_id, file_id, file_name, gcs_path, status | 필터 통과 파일 추적 |
| `convert_job_history` | convert_config_id, file_id, status, error_message | 변환 결과 추적 |

### 10.4 핵심 포인트

```
┌─────────────────────────────────────────────────────────────────┐
│  왜 파일을 복사하지 않고 메타데이터로 관리하나?                   │
│                                                                 │
│  1. 저장 공간 절약 - 파일 중복 없음                              │
│  2. 속도 향상 - 파일 복사 I/O 없음                               │
│  3. 추적 용이 - BigQuery에서 전체 히스토리 조회 가능             │
│  4. 유연성 - 같은 파일을 여러 조건으로 처리 가능                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.5 코드 레퍼런스

**filter_job_history 조회** (collect-manager):
```python
# app/main/service/filter_job_history_service.py

def get_success_item_ids(customer_code, source_type, source_id, ingestion_id, sub_step):
    # BigQuery에서 success 상태인 항목만 조회
    query_job = CommonJobHistoryQuery.get_minimal_last_history_by_ingestion_id(
        ...,
        filter_options=[
            CommonJobHistoryQuery.build_filter_option("status", "STRING", "success")
        ]
    )

    ids = set()
    for row in query_job:
        ids.add((row["filter_condition_id"], row["file_id"],
                 row["file_name"], row["gcs_path"]))
    return ids
```

**Converter에서 사용**:
```python
# filter_job_history에서 조회한 file_id로 crawl/ 경로 구성
src_path = f"{source_type}/{source_id}/crawl/{file_id}"

# GCS에서 파일 읽어서 변환
converter = GCSFileConverter(config_json, bucket_name, src_path, ...)
```

---

## 11. 관련 문서

| 문서 | 내용 |
|------|------|
| [01_OVERVIEW.md](./01_OVERVIEW.md) | V2 전체 개요 |
| [06_OUTPUT_FORMAT_ISSUES.md](./06_OUTPUT_FORMAT_ISSUES.md) | 출력 포맷 이슈 |
| [../../docs/OUTPUT_FILES_GUIDE.md](../../docs/OUTPUT_FILES_GUIDE.md) | 변환 결과물 5개 파일 |
| [../../docs/TAGGING_CONFIG_GUIDE.md](../../docs/TAGGING_CONFIG_GUIDE.md) | 태깅 설정 가이드 |

---

## 12. Cloud Run Job 병렬 처리 상세

### 12.1 실제 실행 예시

`gcloud run jobs executions describe` 명령으로 확인한 결과:

```
Tasks:            658     ← 총 변환할 파일 수
Parallelism:      100     ← 동시에 실행되는 최대 컨테이너 수
```

### 12.2 병렬 처리 동작 방식

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Cloud Run Job 실행 (658 Tasks, Parallelism=100)           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  배치 1: Task 0-99   ████████████████████████████  (100개 동시 시작)         │
│          ↓ 완료되는 대로 다음 Task 투입                                      │
│  배치 2: Task 100-199 ████████████████████████████                          │
│          ↓                                                                  │
│  배치 3: Task 200-299 ████████████████████████████                          │
│          ↓                                                                  │
│  ...                                                                        │
│          ↓                                                                  │
│  배치 7: Task 600-657 ██████████████████████  (58개 - 마지막 배치)           │
│                                                                             │
│  ※ 정확히 100개씩 끊어서 순차 실행이 아님                                    │
│  ※ 완료되는 Task가 생기면 대기 중인 다음 Task 즉시 시작                      │
│  ※ 항상 동시 실행 Task 수 ≤ 100 유지                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 12.3 Parallelism 값 설정

**`parallelism=0`의 의미:**
- Cloud Run Job 생성 시 `--parallelism=0` = "기본값 사용"
- Cloud Run의 **기본 parallelism = 100** (리전별 quota)
- 즉, 명시적으로 설정하지 않으면 100개까지 동시 실행

**설정 코드 (`collector/cloud/run_job/create_job.sh`):**
```bash
parallelism=0   # 0 = Cloud Run 기본값 사용 (100)

gcloud beta run jobs create $job_name \
  --parallelism=$parallelism \   # 결과적으로 100으로 적용됨
  ...
```

### 12.4 Airflow 로그가 "병렬 아닌 것처럼" 보이는 이유

Airflow Task 로그에서는 **폴링 로그만** 보입니다:

```
[Airflow Task Log]
2024-01-15 14:00:00 - Starting Cloud Run Job...
2024-01-15 14:00:01 - Job execution started: job-convert-4-2-abc123
2024-01-15 14:00:30 - Polling... 100/658 completed      ← 폴링 결과만 표시
2024-01-15 14:01:00 - Polling... 250/658 completed
2024-01-15 14:01:30 - Polling... 400/658 completed
2024-01-15 14:02:00 - Polling... 600/658 completed
2024-01-15 14:02:15 - All tasks completed
```

**실제 변환 로그는 Cloud Run Console에서 확인:**
```
Cloud Console → Cloud Run → Jobs → job-convert-4-2 → Executions → Tasks

Task 0: 2024-01-15 14:00:02 - Processing file abc123.xlsx
Task 1: 2024-01-15 14:00:02 - Processing file def456.xlsx  ← 동시에!
Task 2: 2024-01-15 14:00:02 - Processing file ghi789.xlsx  ← 동시에!
...
```

### 12.5 성능 계산 예시

**658개 파일, parallelism=100, 파일당 평균 10초:**

```
직렬 처리: 658 × 10초 = 6,580초 (약 110분)
병렬 처리: (658 ÷ 100) × 10초 × 1.2 = 약 80초 (오버헤드 20% 가정)

→ 약 80배 빠름!
```

### 12.6 Parallelism 조정 방법

**필요시 parallelism 값 변경:**

```bash
# Job 업데이트
gcloud run jobs update job-convert-4-2 \
  --parallelism=50 \   # 동시 실행 수 줄이기 (리소스 제한 시)
  --region=asia-northeast3

# 또는 새 Job 생성 시
gcloud run jobs create job-convert-4-3 \
  --parallelism=200 \  # 더 높은 병렬성 (quota 허용 시)
  --image=...
```

**주의:** 리전별 Cloud Run quota 확인 필요 (기본 최대 100)

---

## 13. 요약

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           핵심 정리                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. 배포 방식: Cloud Run Job (배치) vs Cloud Run Service (HTTP)             │
│     - 둘 다 같은 GCSFileConverter 코드 실행                                  │
│     - Job은 Service를 호출하지 않음 (독립적)                                 │
│                                                                             │
│  2. 파일 저장: crawl/ 폴더에만 저장                                          │
│     - filter/ 폴더는 존재하지 않음                                           │
│     - 코드의 filter_path 변수는 실제로 crawl 경로를 가리킴                    │
│                                                                             │
│  3. 메타데이터 관리: BigQuery History 테이블                                 │
│     - crawl_job_history → filter_job_history → convert_job_history          │
│     - 파일 복사 없이 메타데이터로 상태 추적                                   │
│                                                                             │
│  4. 변환 결과: ext/{cvt_meta_id}/                                            │
│     - .parquet, .csv, tags.json                                             │
│                                                                             │
│  5. 병렬 처리: parallelism=100 (기본값)                                      │
│     - 658 Tasks → 100개씩 동시 실행                                          │
│     - Airflow 로그는 폴링만, 실제 로그는 Cloud Run Console                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```
