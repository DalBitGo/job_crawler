# Cloud Run Job 크롤러 아키텍처 가이드

## 목차
- [개요](#개요)
- [전체 실행 흐름](#전체-실행-흐름)
- [병렬 처리 메커니즘](#병렬-처리-메커니즘)
- [메모리 관리 원리](#메모리-관리-원리)
- [실행 흐름 비교](#실행-흐름-비교)
- [핵심 정리](#핵심-정리)

---

## 개요

Hyperlounge 수집 시스템에서 Board 크롤러는 Cloud Run Job을 통해 실행됩니다. 이 문서는 Airflow DAG에서 Cloud Run Job이 실행되고, 병렬 처리가 이루어지는 전체 메커니즘을 설명합니다.

### 주요 특징
- **확장성**: 필요에 따라 수백 개의 병렬 작업 가능
- **격리성**: 각 작업이 독립된 컨테이너에서 실행
- **효율성**: 작업 분배를 통한 빠른 처리
- **안정성**: 한 작업 실패가 다른 작업에 영향 없음

---

## 전체 실행 흐름

### 1️⃣ Airflow DAG에서 시작

**파일**: `airflow-dags/dags/c230c700.py:134-137`

```python
# board source가 활성화되면
crawler_task = TaskFactory.create_crawler_task(CONFIG, source, dag=dag)

# Task 의존성
start_collect_task >> crawler_task >> fileid_mapping_task
```

**역할**: 원익큐엔씨 DAG에서 board 크롤링 작업 정의

---

### 2️⃣ TaskFactory가 Airflow Task 생성

**파일**: `airflow-dags/dags/dependencies/task_factory.py:108-116`

```python
crawler_task = PythonOperator(
    task_id=f"crawler-{source_type}",
    python_callable=TaskFunctions.crawl_files,
    params={
        **dag_config,
        'source_type': source_type,
        'non_excel_crawl': non_excel_crawl
    }
)
```

**역할**: Python Operator를 생성하여 `TaskFunctions.crawl_files` 함수를 실행

---

### 3️⃣ crawl_files가 Cloud Run Job 호출

**파일**: `collector/cloud/file_crawler.py:122`

```python
if source_type == SOURCE_BOARD:
    crawl_actions = get_task_items(api_svr_url, customer_code, source_type,
                                   TASK_CRAWL, ingestion_id, source_id)

    if crawl_actions:
        board_crawler_with_job(customer_code, source_type, source_id, ingestion_id)
```

**역할**: Firestore에서 크롤 액션을 가져와 Cloud Run Job 실행

---

### 4️⃣ Cloud Run Job 실행 준비

**파일**: `collector/boards/main_board_crawler.py:214-256`

#### a) BSDA 리스트 생성 및 GCS 업로드

```python
bsda = datetime.strptime(ingestion_id, "%Y%m%d%H%M%S").strftime("%Y-%m-%d")
ingestion_time = ingestion_id[8:]  # "230000"

bsda_list = [{"start": bsda, "end": bsda}]
# 예: [{"start": "2025-12-02", "end": "2025-12-02"}]

bsda_list_path = upload_bsda_list(
    bsda_list,
    bucket_name="hyperlounge-collect-config",
    customer_code="c230c700",
    source_type="board",
    source_id="s26fc26d",
    job_name="crawler"
)
# 결과: "crawler/c230c700/board/s26fc26d/20251203081500"
```

#### b) 환경변수 준비

```python
env_vars = [
    {"name": "customer_code", "value": "c230c700"},
    {"name": "source_type", "value": "board"},
    {"name": "source_id", "value": "s26fc26d"},
    {"name": "bsda_list_path", "value": bsda_list_path},
    {"name": "COLLECT_ENV", "value": "airflow"},
    {"name": "ingestion_time", "value": "230000"}
]
```

#### c) Cloud Run Job 실행

```python
job = run_job(
    project="hyperlounge-dev",
    location="asia-northeast3",
    job_name="crawler",
    env_vars=env_vars,
    tasks=1,  # 생성할 컨테이너 개수
    task_timeout="36000s"  # 10시간
)
```

**역할**: Cloud Run Job API를 호출하여 작업 실행

---

### 5️⃣ Cloud Run Job Container 시작

**파일**: `collector/deploy/run_crawler_job/Dockerfile`

```dockerfile
FROM python:3.8
WORKDIR /app

COPY app .
COPY main.py .
COPY requirements.txt .
COPY install_chrome.sh /app/install_chrome.sh

# Chrome 및 의존성 설치
RUN apt-get update
RUN apt-get install -y gconf-service libasound2 libatk1.0-0 ...
RUN /app/install_chrome.sh

# Python 패키지 설치
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
```

**역할**:
- Python 3.8 환경 구성
- Chrome/ChromeDriver 설치 (셀레니움 크롤링용)
- 필요한 Python 패키지 설치
- `main.py` 실행

---

### 6️⃣ Job Container에서 main.py 실행

**파일**: `collector/deploy/run_crawler_job/main.py`

#### a) 환경변수 로드

```python
# Google Cloud Run이 자동으로 주입하는 환경변수
TASK_INDEX = int(os.getenv("CLOUD_RUN_TASK_INDEX", 0))   # 0, 1, 2, ...
TASK_ATTEMPT = int(os.getenv("CLOUD_RUN_TASK_ATTEMPT", 3))
TASK_COUNT = int(os.getenv("CLOUD_RUN_TASK_COUNT", 1))

# Airflow에서 전달한 환경변수
customer_code = os.getenv("customer_code")      # "c230c700"
source_type = os.getenv("source_type")          # "board"
source_id = os.getenv("source_id")              # "s26fc26d"
ingestion_time = os.getenv("ingestion_time")    # "230000"
bsda_list_path = os.getenv("bsda_list_path")
```

#### b) BSDA 리스트 다운로드 및 작업 범위 결정

```python
bsda_list = get_from_gcs(
    bucket_name="hyperlounge-collect-config",
    source_blob_name=bsda_list_path,
    is_json=True
)
# bsda_list = [{"start": "2025-12-02", "end": "2025-12-02"}]

# 🔑 핵심: TASK_INDEX로 자기 담당 범위만 가져옴
start_bsda = bsda_list[TASK_INDEX]["start"]  # "2025-12-02"
end_bsda = bsda_list[TASK_INDEX]["end"]      # "2025-12-02"
```

#### c) 크롤러 인스턴스 생성

```python
# ingestion_id 생성
ingestion_id = start_bsda.replace("-", "") + ingestion_time
ingestion_datetime = datetime.strptime(ingestion_id, "%Y%m%d%H%M%S")

# Firestore에서 크롤 액션 가져오기
crawl_actions = get_task_items(
    api_svr_url, customer_code, source_type,
    TASK_CRAWL, ingestion_id, source_id
)["sources"][0]["crawl_actions"]

# 크롤러 생성 (예: WonikqncBoardCrawler)
crawler = get_crawler(
    project_id, customer_code, source_id,
    sync_bucket_name, sync_path,
    ingestion_datetime, ingestion_datetime,
    crawler_name="wonikqnc"
)
```

#### d) API 로그인 및 크롤링 실행

```python
# Secret Manager에서 API Key 가져오기
crawler.get_api_key(login_by_req_info)

# 실제 크롤링 수행
crawler.target_crawling(crawl_actions)

# 에러 처리
if crawler.error_result:
    crawler.upload_error_result()
```

---

### 7️⃣ WonikqncBoardCrawler 실행

**파일**: `collector/boards/api/wonikqnc_api_crawler.py:60-146`

```python
def crawl(self, crawl_action):
    # 1. 파일명 생성
    file_name = self.generate_file_name(date_list, FOLDER_CODE, DATE_RANGE, INF_ID, PARAM1)
    # 예: "20251202_20251202-20251202_D_lq10_금일_DW_DWH_001_LABOR_COST.xlsx"

    # 2. API 요청 (재시도 로직 포함)
    max_retries = 3
    for attempt in range(max_retries):
        res = requests.post(self.base_url, json=body, headers=headers, timeout=180)
        if res.status_code == 200:
            break
        if res.status_code == 504:  # Gateway Timeout
            time.sleep(10)
            continue

    # 3. 응답 처리
    http_res = res.json()['HTTP_RESPONSE']
    data_cnt = http_res['DATA_COUNT']

    if data_cnt == 0:
        # 🆕 빈 엑셀 파일 생성 (수정 사항)
        df = DataFrame()
        excel_path = f"{self.abspath}/{file_name}"
        make_excel(df=df, excel_path=excel_path)
        ob_meta = self.get_metadata(file_name=file_name)
        self.upload(ob_meta, src_path=excel_path)
        return

    # 4. 데이터프레임 생성 및 Excel 저장
    data_list = http_res[INF_ID]
    df = self.make_df(data_list)
    excel_path = f"{self.abspath}/{file_name}"
    make_excel(df=df, excel_path=excel_path)

    # 5. GCS 업로드
    ob_meta = self.get_metadata(file_name=file_name)
    self.upload(ob_meta, src_path=excel_path)
    # 업로드 위치: gs://hyperlounge-c230c700-foldersync/board/s26fc26d/20251202230000/
```

---

### 8️⃣ Airflow로 결과 반환

```python
# main_board_crawler.py:261-264
check_run_job_execution_state(
    project=PROJECT_NAME,
    location=DEFAULT_ZONE,
    job_name="crawler",
    execution_id=execution_id
)

check_run_job_execution_tasks_state(
    project=PROJECT_NAME,
    location=DEFAULT_ZONE,
    job_name="crawler",
    execution_id=execution_id,
    retry_num=retry_num,
    sleep_time=sleep_time
)
```

**역할**:
- Job 실행 상태 폴링
- 모든 Task 완료 대기
- 성공 시 Airflow Task 성공 → 다음 Task (fileid_mapping) 실행

---

## 병렬 처리 메커니즘

### Cloud Run Job의 taskCount 설정

**파일**: `collector/common/run_job_util.py:240`

```python
body["overrides"] = {
    "taskCount": tasks,  # 예: tasks=10
    "timeout": task_timeout
}
```

**결과**: 같은 Docker 이미지로 N개의 독립된 컨테이너가 생성됨

---

### Google Cloud Run이 자동 주입하는 환경변수

| 환경변수 | 설명 | 예시 |
|---------|------|------|
| `CLOUD_RUN_TASK_INDEX` | 현재 Task의 인덱스 (0부터 시작) | 0, 1, 2, ..., 9 |
| `CLOUD_RUN_TASK_COUNT` | 전체 Task 개수 | 10 |
| `CLOUD_RUN_TASK_ATTEMPT` | 현재 재시도 횟수 | 1, 2, 3 |
| `CLOUD_RUN_JOB` | Job 이름 | crawler |
| `CLOUD_RUN_EXECUTION` | Execution ID | abc123def456 |

---

### 작업 분배 메커니즘

**파일**: `collector/deploy/run_crawler_job/main.py:68`

```python
# 각 컨테이너가 자기 담당 작업만 가져옴
start_bsda, end_bsda = bsda_list[TASK_INDEX]["start"], bsda_list[TASK_INDEX]["end"]
```

#### 예시: 30일치 데이터를 10개 Task로 분배

**Airflow에서 BSDA 리스트 준비**:
```python
bsda_list = [
    {"start": "2025-12-01", "end": "2025-12-03"},  # TASK_INDEX=0
    {"start": "2025-12-04", "end": "2025-12-06"},  # TASK_INDEX=1
    {"start": "2025-12-07", "end": "2025-12-09"},  # TASK_INDEX=2
    {"start": "2025-12-10", "end": "2025-12-12"},  # TASK_INDEX=3
    {"start": "2025-12-13", "end": "2025-12-15"},  # TASK_INDEX=4
    {"start": "2025-12-16", "end": "2025-12-18"},  # TASK_INDEX=5
    {"start": "2025-12-19", "end": "2025-12-21"},  # TASK_INDEX=6
    {"start": "2025-12-22", "end": "2025-12-24"},  # TASK_INDEX=7
    {"start": "2025-12-25", "end": "2025-12-27"},  # TASK_INDEX=8
    {"start": "2025-12-28", "end": "2025-12-30"},  # TASK_INDEX=9
]
```

**Cloud Run이 10개 컨테이너 생성**:

| 컨테이너 | TASK_INDEX | 담당 날짜 | CPU | Memory | 상태 |
|----------|------------|-----------|-----|--------|------|
| Container-0 | 0 | 12/01~12/03 | 1 | 512Mi | Running |
| Container-1 | 1 | 12/04~12/06 | 1 | 512Mi | Running |
| Container-2 | 2 | 12/07~12/09 | 1 | 512Mi | Running |
| Container-3 | 3 | 12/10~12/12 | 1 | 512Mi | Running |
| Container-4 | 4 | 12/13~12/15 | 1 | 512Mi | Running |
| Container-5 | 5 | 12/16~12/18 | 1 | 512Mi | Running |
| Container-6 | 6 | 12/19~12/21 | 1 | 512Mi | Running |
| Container-7 | 7 | 12/22~12/24 | 1 | 512Mi | Running |
| Container-8 | 8 | 12/25~12/27 | 1 | 512Mi | Running |
| Container-9 | 9 | 12/28~12/30 | 1 | 512Mi | Running |

**각 컨테이너에서 실행되는 코드**:

```python
# Container-0의 main.py
TASK_INDEX = 0  # Google이 자동 주입
bsda_list = get_from_gcs(...)  # 전체 리스트 다운로드
start_bsda = bsda_list[0]["start"]  # "2025-12-01"
end_bsda = bsda_list[0]["end"]      # "2025-12-03"
# → 12/01, 12/02, 12/03 크롤링

# Container-1의 main.py
TASK_INDEX = 1  # Google이 자동 주입
bsda_list = get_from_gcs(...)  # 동일한 GCS 파일
start_bsda = bsda_list[1]["start"]  # "2025-12-04"
end_bsda = bsda_list[1]["end"]      # "2025-12-06"
# → 12/04, 12/05, 12/06 크롤링
```

---

## 메모리 관리 원리

### 각 컨테이너는 완전히 독립

**파일**: `collector/common/run_job_util.py:70-86`

```python
"template": {
    "containers": [{
        "image": "asia-northeast3-docker.pkg.dev/hyperlounge-dev/cloud-run-job/crawler:latest",
        "resources": {
            "limits": {
                "cpu": "1",       # 각 컨테이너마다 1 vCPU
                "memory": "512Mi" # 각 컨테이너마다 512MB
            }
        }
    }]
}
```

### 리소스 격리

| 항목 | 설명 |
|------|------|
| **CPU** | 각 컨테이너마다 독립된 vCPU 할당 |
| **메모리** | 각 컨테이너마다 독립된 메모리 공간 (512Mi) |
| **디스크** | 각 컨테이너마다 임시 디스크 공간 |
| **네트워크** | 각 컨테이너가 독립적으로 API 호출 |
| **Python 프로세스** | 각 컨테이너마다 별도 Python 인터프리터 |

### 메모리 공유 여부

| 구분 | 공유 여부 | 설명 |
|------|-----------|------|
| **Docker 이미지** | ✅ 공유 (읽기 전용) | 모든 컨테이너가 같은 이미지 사용 |
| **Python 코드** | ✅ 공유 (읽기 전용) | 이미지에 포함된 코드 |
| **힙 메모리** | ❌ 독립 | 각 컨테이너마다 별도 할당 |
| **스택 메모리** | ❌ 독립 | 각 컨테이너마다 별도 할당 |
| **변수/객체** | ❌ 독립 | 각 컨테이너마다 독립 생성 |
| **GCS 데이터** | ✅ 공유 | 같은 bsda_list 파일 읽음 |

### 실행 방식

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Image (읽기 전용)                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Python 3.8, Chrome, ChromeDriver, main.py, ...     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ↓ (복제)
        ┌─────────────────┬─────────────────┬─────────────────┐
        │  Container-0    │  Container-1    │  Container-2    │
        │  INDEX=0        │  INDEX=1        │  INDEX=2        │
        ├─────────────────┼─────────────────┼─────────────────┤
        │  Python 프로세스 │  Python 프로세스 │  Python 프로세스 │
        │  독립 메모리 512M│  독립 메모리 512M│  독립 메모리 512M│
        │  CPU: 1 vCPU   │  CPU: 1 vCPU   │  CPU: 1 vCPU   │
        │  bsda[0] 처리   │  bsda[1] 처리   │  bsda[2] 처리   │
        └─────────────────┴─────────────────┴─────────────────┘
```

---

## 실행 흐름 비교

### 단일 Task (tasks=1)

```
Airflow Trigger
    ↓
bsda_list = [{"start": "2025-12-02", "end": "2025-12-02"}]
    ↓
Cloud Run Job 시작 (taskCount=1)
    ↓
┌──────────────────────────────────────────┐
│           Container-0                    │
│  ┌────────────────────────────────────┐ │
│  │ TASK_INDEX = 0                     │ │
│  │ start_bsda = "2025-12-02"         │ │
│  │ end_bsda = "2025-12-02"           │ │
│  └────────────────────────────────────┘ │
│                                          │
│  WonikqncBoardCrawler 실행               │
│  ├─ API 호출 1: LABOR_COST              │
│  ├─ API 호출 2: PRODUCTIVITY            │
│  ├─ API 호출 3: SO_AMT_CURM             │
│  └─ ...                                 │
│                                          │
│  결과: 19개 파일 생성                     │
│  GCS 업로드 완료                         │
└──────────────────────────────────────────┘
    ↓
Job 완료
    ↓
Airflow Task 성공
```

**특징**:
- 순차 처리
- 단일 컨테이너
- 실행 시간: ~10분

---

### 병렬 Task (tasks=10)

```
Airflow Trigger
    ↓
bsda_list = [
    {"start": "2025-12-01", "end": "2025-12-03"},
    {"start": "2025-12-04", "end": "2025-12-06"},
    ...
]
    ↓
Cloud Run Job 시작 (taskCount=10)
    ↓
┌──────────────┬──────────────┬──────────────┬─────┬──────────────┐
│ Container-0  │ Container-1  │ Container-2  │ ... │ Container-9  │
├──────────────┼──────────────┼──────────────┼─────┼──────────────┤
│ INDEX=0      │ INDEX=1      │ INDEX=2      │     │ INDEX=9      │
│ 12/01~03     │ 12/04~06     │ 12/07~09     │     │ 12/28~30     │
├──────────────┼──────────────┼──────────────┼─────┼──────────────┤
│ Crawler 실행  │ Crawler 실행  │ Crawler 실행  │     │ Crawler 실행  │
│ 19 files x3  │ 19 files x3  │ 19 files x3  │     │ 19 files x3  │
│ = 57 files   │ = 57 files   │ = 57 files   │     │ = 57 files   │
└──────────────┴──────────────┴──────────────┴─────┴──────────────┘
        ↓              ↓              ↓        ...        ↓
    GCS 업로드     GCS 업로드     GCS 업로드           GCS 업로드
        ↓              ↓              ↓        ...        ↓
                    모든 컨테이너 완료 대기
                            ↓
                       Job 완료
                            ↓
                    Airflow Task 성공
```

**특징**:
- 병렬 처리 (동시 실행)
- 10개 컨테이너
- 실행 시간: ~10분 (단일 Task와 유사하지만 30일치 처리)
- 총 570개 파일 생성

---

## 핵심 정리

### 아키텍처 특징

| 항목 | 설명 |
|------|------|
| **코드 공유** | ✅ 모든 컨테이너가 같은 Docker 이미지 사용 |
| **메모리 공유** | ❌ 각 컨테이너마다 독립된 메모리 공간 |
| **프로세스** | 각 컨테이너마다 별도 Python 프로세스 |
| **작업 분배** | `TASK_INDEX` 환경변수로 자동 분배 |
| **실행 방식** | 병렬 (동시에 N개 실행) |
| **격리성** | 한 컨테이너 실패해도 다른 컨테이너는 계속 실행 |
| **비용** | 컨테이너당 독립 청구 (실행 시간 × CPU/메모리) |

---

### Airflow Worker vs Cloud Run Job

| 기능 | Airflow Worker | Cloud Run Job |
|------|---------------|---------------|
| **실행 시간 제한** | 제한적 (수 시간) | 최대 24시간 |
| **리소스** | 공유 리소스 (다른 Task와 경합) | 독립 리소스 (격리) |
| **병렬 처리** | Worker 수만큼 제한 | 무제한 (taskCount 조정) |
| **복잡한 의존성** | 설치 어려움 | Dockerfile로 자유롭게 |
| **Chrome/Selenium** | Worker에 설치 복잡 | Dockerfile로 간단히 설치 |
| **확장성** | Worker 추가 필요 | taskCount만 증가 |
| **비용** | Worker 고정 비용 | 사용한 만큼 청구 |

---

### 언제 병렬화를 사용하는가?

#### ✅ 병렬화가 필요한 경우

1. **대량 데이터 수집**
   - 수백 개 파일 크롤링
   - 여러 달치 히스토리 수집

2. **시간이 오래 걸리는 작업**
   - 각 작업이 10분 이상
   - API 호출이 느린 경우

3. **RPA 크롤링**
   - 여러 계정으로 동시 로그인
   - 예: `guest_num=5`로 5개 병렬 실행

#### ❌ 병렬화가 불필요한 경우

1. **원익큐엔씨 (현재)**
   - 하루치 데이터만 크롤링 (19개 파일)
   - API 호출이 빠름 (전체 10분 이내)
   - `tasks=1`로 충분

2. **API Rate Limit이 있는 경우**
   - 병렬 요청이 제한될 수 있음
   - 순차 처리가 더 안전

---

### 병렬화 설정 예시

#### 예시 1: 1개월 히스토리 수집 (tasks=10)

```python
# Airflow DAG에서
bsda_list = []
for i in range(10):
    start = "2025-11-01" + timedelta(days=i*3)
    end = "2025-11-01" + timedelta(days=(i+1)*3-1)
    bsda_list.append({"start": start.strftime("%Y-%m-%d"),
                      "end": end.strftime("%Y-%m-%d")})

# Cloud Run Job 실행
board_crawler_with_job(..., tasks=10)
```

#### 예시 2: RPA 병렬 크롤링 (tasks=5)

```python
# c230c700.py의 RPA 설정
source_confs = [
    {
        "source": "rpa",
        "enable": True,
    }
]

# DAG에서 자동으로 guest_num만큼 Task 생성
guest_num = 5  # 5개 Guest VM
for task_num in range(guest_num):
    crawler_task = RPATasks.generate_rpa_crawler_task(
        CONFIG, source_id, source, task_num
    )
```

---

### 문제 해결 가이드

#### 문제 1: Task가 Timeout

**증상**: Job이 `task_timeout`을 초과하여 실패

**해결**:
```python
# task_timeout 증가
board_crawler_with_job(..., task_timeout="72000s")  # 20시간
```

#### 문제 2: Memory 부족

**증상**: Container가 OOM (Out of Memory)으로 실패

**해결**:
```python
# Job 생성 시 메모리 증가
create_run_job(..., memory="1Gi")  # 512Mi → 1Gi
```

#### 문제 3: 일부 Task만 실패

**증상**: 10개 중 2개 Task가 실패

**장점**: 나머지 8개는 성공적으로 완료
**해결**: 실패한 Task의 로그를 확인하여 개별 수정

```bash
# Cloud Run Job Execution 로그 확인
gcloud logging read "resource.type=cloud_run_job AND \
  resource.labels.job_name=crawler AND \
  resource.labels.location=asia-northeast3" \
  --limit 100 --format json
```

---

### 모니터링

#### Cloud Console에서 확인

```
https://console.cloud.google.com/run/jobs/executions/details/{location}/{execution_id}/tasks?project={project}
```

#### 로그 확인

```python
# main_board_crawler.py:221-222
logger.info(f"job_name={job_name}, execution_id={execution_id}, env_vars={env_vars}, "
            f"task_timeout={task_timeout}")
```

#### Task 상태 확인

```python
# run_job_util.py:399-433
def check_run_job_execution_tasks_state(...):
    tasks = list_run_job_execution_tasks(...)

    success_tasks_count = task_statuses.count(TaskCondition.SUCCEEDED)
    fail_tasks_count = task_statuses.count(TaskCondition.FAILED)

    logger.info(
        f"total_tasks_count={total_tasks_count}, "
        f"success_tasks_count={success_tasks_count}, "
        f"fail_tasks_count={fail_tasks_count}"
    )
```

---

## 참고 자료

### 주요 파일 위치

| 파일 | 역할 |
|------|------|
| `airflow-dags/dags/c230c700.py` | 원익큐엔씨 DAG 정의 |
| `airflow-dags/dags/dependencies/task_factory.py` | Task 생성 팩토리 |
| `airflow-dags/dags/dependencies/task_functions.py` | Task 실행 함수 |
| `collector/cloud/file_crawler.py` | 크롤러 진입점 |
| `collector/boards/main_board_crawler.py` | Cloud Run Job 실행 |
| `collector/common/run_job_util.py` | Cloud Run Job API 호출 |
| `collector/deploy/run_crawler_job/main.py` | Job Container 실행 코드 |
| `collector/deploy/run_crawler_job/Dockerfile` | Container 이미지 정의 |
| `collector/boards/api/wonikqnc_api_crawler.py` | 원익큐엔씨 크롤러 구현 |

### Cloud Run Job 공식 문서

- [Cloud Run Jobs Overview](https://cloud.google.com/run/docs/create-jobs)
- [Container Contract](https://cloud.google.com/run/docs/container-contract?hl=ko#jobs-env-vars)
- [REST API Reference](https://cloud.google.com/run/docs/reference/rest/v2/projects.locations.jobs)

---

## 변경 이력

| 날짜 | 작성자 | 내용 |
|------|--------|------|
| 2025-12-03 | Claude | 초안 작성 |
| 2025-12-03 | Claude | 원익큐엔씨 빈 파일 처리 추가 |

---

**문서 작성일**: 2025-12-03
**최종 수정일**: 2025-12-03
**버전**: 1.0
