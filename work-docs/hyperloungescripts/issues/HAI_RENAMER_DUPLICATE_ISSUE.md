# HAI Renamer 중복 히스토리 이슈

## 개요

- **발생일**: 2026-01-13 (ingestion_id: 20260113140000)
- **고객사**: c8cd3500 (엘앤케이웰니스 / Trinity Spa)
- **소스 타입**: email
- **문제**: HAI renamer 재실행 시 crawl_job_history에 중복 레코드 적재

---

## 문제 상황

### 증상
HAI renamer를 수동으로 재실행하면 `crawl_job_history` 테이블에 동일 파일에 대한 히스토리가 중복 적재됨.

### 확인된 데이터
```
file_name: (트리니티 광교점)...DAILY_VISITING_HAI_26292d8e_20260113.xlsx
file_id: f6fa5052758f

| created_at          | status  |
|---------------------|---------|
| 2026-01-14 06:46:02 | success | ← 첫 번째 실행
| 2026-01-14 07:28:51 | fail    | ← 두 번째 실행 (실패)
| 2026-01-14 07:29:15 | success | ← 세 번째 실행 (재시도)
```

모든 HAI 파일(약 25개)에서 동일하게 3개씩 중복 발생.

### 확인 쿼리
```sql
SELECT
  file_name,
  file_id,
  status,
  created_at
FROM `hyperlounge-dev.dashboard.crawl_job_history`
WHERE customer_code = "c8cd3500"
  AND source_type = "email"
  AND CAST(ingestion_id AS STRING) LIKE "2026-01-13%"
  AND file_name LIKE "%_HAI_%"
ORDER BY file_name, created_at
```

---

## 원인 분석

### 일반 파일 vs HAI 파일 처리 차이

| 구분 | 일반 파일 | HAI 파일 |
|------|----------|----------|
| 원본 위치 | `{source_type}/{source_id}/` (ingestion_id 폴더 밖) | `{source_type}/{source_id}/{ingestion_id}/` (이미 안에 있음) |
| Rename 동작 | 폴더 밖 → 안으로 이동 + 해시/날짜 추가 | 이름만 변경 (해시/날짜 추가) |
| 사용 서비스 | `file_renamer.py` (collector 내장) | `hai_renamer_service` (별도 Cloud Run) |

### 왜 HAI 파일이 이미 ingestion_id 폴더 안에 있는가?
- HAI 파일은 LLM(Claude)이 shared_drive 파일을 변환하여 생성
- 생성 시점에 이미 `email/{source_id}/{ingestion_id}/` 경로에 저장됨
- 따라서 일반 rename처럼 "폴더 이동"이 불필요하고 "이름 변경"만 필요

### 중복 발생 원인
1. **일반 file_renamer**: `init_collector`를 통해 실행되며, 실행 전 `_collect_clear()`로 기존 히스토리 삭제
2. **hai_renamer_service**: 별도 서비스로 실행되며, **히스토리 삭제 로직 없음**

```
일반 파이프라인:
init_collector._collect_clear() → file_renamer.rename() → history INSERT
  ↓
기존 히스토리 DELETE → 새 히스토리 INSERT (중복 없음)

HAI 파이프라인:
hai_renamer_service.rename() → history INSERT
  ↓
기존 히스토리 유지 → 새 히스토리 INSERT (중복 발생!)
```

---

## collect-dash에서 중복이 안 보이는 이유

collect-dash의 조회 쿼리에서 `ROW_NUMBER()`로 최신 레코드만 필터링:

```sql
WITH ranked_log AS (
    SELECT
        ...,
        ROW_NUMBER() OVER (PARTITION BY ingestion_id ORDER BY created_at DESC) AS rn
    FROM `{table_ref}`
    ...
)
SELECT * EXCEPT(rn) FROM ranked_log WHERE rn = 1
```

- `ORDER BY created_at DESC` → 최신순 정렬
- `WHERE rn = 1` → 가장 최신 1개만 반환
- 따라서 UI에서는 중복이 보이지 않음

### 하지만 문제점
- 불필요한 레코드가 BigQuery에 계속 쌓임 → 스토리지 비용 증가
- 집계 쿼리 시 중복 카운트 가능성
- 데이터 정합성 관리 어려움

---

## 해결 방안

### 방안 1: hai_renamer_service에 히스토리 삭제 로직 추가 (권장)

#### 1-1. collect-manager에 HAI 전용 히스토리 삭제 API 추가

**파일**: `/collect-manager/app/main/controller/job_history_controller.py`

```python
@api.route('/crawl/<customer_code>/<source_type>/<source_id>/ingestion_id/<ingestion_id>/hai', methods=['DELETE'])
def delete_hai_crawl_history(customer_code, source_type, source_id, ingestion_id):
    """HAI 파일 히스토리만 삭제"""
    return CrawlJobHistoryService.delete_hai_history(
        customer_code=customer_code,
        source_type=source_type,
        source_id=source_id,
        ingestion_id=ingestion_id
    )
```

**파일**: `/collect-manager/app/main/service/crawl_job_history_service.py`

```python
@staticmethod
def delete_hai_history(customer_code, source_type, source_id, ingestion_id):
    """HAI 파일 히스토리 삭제 (file_name LIKE '%_HAI_%')"""
    CommonJobHistoryQuery.delete_history(
        customer_code=customer_code,
        source_type=source_type,
        source_id=source_id,
        ingestion_id=ingestion_id,
        table_name=CRAWL_JOB_HISTORY_TABLE,
        filter_options=[
            CommonJobHistoryQuery.build_filter_option("file_name", "STRING", "%_HAI_%", "LIKE")
        ]
    )
    return response_ok("HAI history deleted successfully")
```

#### 1-2. hai_renamer_service에서 rename 전 API 호출

**파일**: `/hai_renamer_service/app/logic.py`

```python
def run_rename(customer_code, source_type, source_id, ingestion_id):
    # 1. 기존 HAI 히스토리 삭제
    delete_hai_history(customer_code, source_type, source_id, ingestion_id)

    # 2. rename 실행
    renamer = HaiFileRenamer(...)
    renamer.rename(crawl_history)
```

### 방안 2: 기존 reset_history API 활용

현재 존재하는 API:
```
DELETE /job_history/crawl/{customer_code}/{source_type}/{source_id}/ingestion_id/{ingestion_id}?file_id={file_id}
```

- `file_id` 파라미터로 특정 파일만 삭제 가능
- 하지만 HAI 파일 전체를 한 번에 삭제하려면 file_id 목록을 미리 조회해야 함
- 비효율적이므로 방안 1 권장

---

## 관련 파일 경로

### hai_renamer_service (Cloud Run)
```
/hyperloungescripts/hai_renamer_service/
├── app/
│   ├── logic.py                    # 메인 로직 (여기서 delete API 호출 필요)
│   ├── renamer/
│   │   └── hai_file_renamer.py     # HAI 파일 rename 로직
│   └── routes.py                   # API 엔드포인트
├── main.py
└── requirements.txt
```

### collect-manager (API 서버)
```
/collect-manager/app/main/
├── controller/
│   └── job_history_controller.py   # API 엔드포인트 (수정 필요)
├── service/
│   └── crawl_job_history_service.py # 서비스 로직 (수정 필요)
└── util/
    └── query_util.py               # CommonJobHistoryQuery 클래스
```

### collector (일반 rename)
```
/hyperloungescripts/collector/
├── cloud/
│   └── file_renamer.py             # 일반 파일 rename (참고용)
└── deploy/
    └── run_init_collector/
        └── init_collector.py       # _collect_clear() 메서드 (참고용)
```

### Airflow DAG
```
/hyperloungescripts/airflow-dags/dags/
├── c8cd3500.py                     # 엘앤케이웰니스 DAG
└── dependencies/
    └── task_factory.py             # create_fileid_mapping_hai_task()
```

---

## DAG 파이프라인 흐름 (c8cd3500)

```
shared_drive:
  start_collect → crawler → fileid_mapping → claude_skills_converter
                                                      ↓
email:                                         python_converter_task
  python_converter_task → crawler → fileid_mapping → fileid_mapping_hai → filter → converter → tag
                                          ↓
                                   hai_renamer_service 호출
                                   (여기서 중복 발생)
```

---

## 작업 체크리스트

- [ ] collect-manager에 HAI 히스토리 삭제 API 추가
- [ ] hai_renamer_service에서 rename 전 삭제 API 호출 추가
- [ ] 테스트: 수동 재실행 시 중복 발생 안 하는지 확인
- [ ] 기존 중복 데이터 정리 (선택사항)

---

## 참고: 기존 중복 데이터 정리 쿼리

```sql
-- 중복 레코드 확인 (최신 1개 제외)
WITH ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY customer_code, source_type, source_id, ingestion_id, file_id
      ORDER BY created_at DESC
    ) AS rn
  FROM `hyperlounge-dev.dashboard.crawl_job_history`
  WHERE customer_code = "c8cd3500"
    AND source_type = "email"
    AND file_name LIKE "%_HAI_%"
)
SELECT * FROM ranked WHERE rn > 1;

-- 삭제는 BigQuery에서 직접 DELETE 또는 새 테이블로 교체 필요
```

---

## 작성일
- 2026-01-21
- 작성자: 박준현 / Claude
