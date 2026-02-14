# HAI Renamer History 중복 문제 해결 가이드

> 작성일: 2026-01-22
>
> 이 문서는 BigQuery streaming buffer 제한을 우회하여 crawl_job_history 중복 문제를 해결한 과정을 담고 있습니다.
> 개발자가 유사한 문제를 만났을 때 참고할 수 있도록 사고 과정과 의사결정을 상세히 기록합니다.

---

## 1. 문제 상황

### 1.1 증상
- c8cd3500 고객의 email 소스에서 HAI renamer 실행 시 `crawl_job_history`에 중복 레코드 발생
- 동일한 HAI 파일에 대해 여러 개의 `success` 레코드가 쌓임
- HAI renamer를 여러 번 실행하면 레코드가 계속 증가

### 1.2 영향 범위
```
crawl_job_history 테이블
├── 1차 실행: 70개 success INSERT
├── 2차 실행: 70개 success INSERT (기존 70개 유지)
├── 3차 실행: 70개 success INSERT (기존 140개 유지)
└── ... 무한 증가
```

### 1.3 왜 문제인가?
1. **데이터 정합성**: 동일 파일에 대해 여러 success 레코드 존재
2. **스토리지 낭비**: 불필요한 레코드 누적
3. **쿼리 성능**: 레코드 증가에 따른 쿼리 비용 증가

---

## 2. 원인 분석

### 2.1 일반 Renamer vs HAI Renamer 차이

| 구분 | 일반 Renamer | HAI Renamer |
|------|-------------|-------------|
| 파일명 변경 | hash + date 추가 | 원본 유지 + `_HAI` suffix |
| file_id 생성 | 매번 다른 ID | **동일한 ID 재사용** |
| 중복 가능성 | 없음 (항상 새 ID) | **있음 (같은 ID로 INSERT)** |

### 2.2 HAI Renamer 동작 흐름 (수정 전)

```
is_init=True, is_sync=True 조건에서:

1. ingestion_id 폴더 내부 탐색 (crawl/20260113140000/)
2. 이미 rename된 _HAI 파일들 발견
3. 동일한 file_name으로 다시 history INSERT
4. 기존 history 삭제 없음 → 중복 발생
```

### 2.3 핵심 문제
```python
# HAI renamer가 생성하는 file_name 예시
"[트리니티_판교점] 통합 데일리_20251231_d424178f_20260102_DAILY_VISITING_HAI.xlsx"

# 이 file_name이 crawl_job_history의 PARTITION KEY 역할
# 같은 file_name으로 여러 번 INSERT → 중복 레코드
```

---

## 3. 해결 방안 검토

### 3.1 방안 1: DELETE 후 INSERT
```python
# 1. 기존 HAI history DELETE
DELETE FROM crawl_job_history WHERE file_name LIKE '%_HAI%'

# 2. 새 HAI history INSERT
INSERT INTO crawl_job_history (file_name, status, ...) VALUES (...)
```

**문제점**: BigQuery Streaming Buffer 제한
- 최근 INSERT된 레코드는 ~90분 동안 DELETE 불가
- HAI renamer가 연속 실행되면 DELETE 실패

### 3.2 방안 2: UPSERT (UPDATE or INSERT)
```sql
MERGE INTO crawl_job_history ...
```

**문제점**: BigQuery는 Streaming Buffer 레코드에 UPDATE도 불가

### 3.3 방안 3: 중복 체크 후 INSERT Skip
```python
existing = get_hai_history(file_name)
if not existing:
    insert_history(file_name, status='success')
```

**문제점**:
- 파일이 변경되었을 때 재처리 불가
- history 초기화(reset) 기능 구현 어려움

### 3.4 방안 4: reset_history 패턴 (채택)
```python
# 1. 오래된 레코드 DELETE 시도 (90분+ 된 것만 삭제됨)
DELETE FROM crawl_job_history
WHERE file_name LIKE '%_HAI%'
AND created_at <= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 MINUTE)

# 2. 남은 레코드에 fail INSERT (논리적 삭제)
INSERT INTO crawl_job_history (file_name, status='fail', ...)

# 3. 새 success INSERT
INSERT INTO crawl_job_history (file_name, status='success', ...)
```

**장점**:
- Streaming Buffer 제한 우회
- 오래된 레코드는 실제 삭제
- 최근 레코드는 fail로 무효화
- ROW_NUMBER() 쿼리에서 최신 레코드만 사용

---

## 4. BigQuery Streaming Buffer 이해하기

### 4.1 Streaming Buffer란?
BigQuery에 `INSERT` (streaming insert)된 데이터는 일정 시간 동안 "streaming buffer"에 머뭅니다.

```
INSERT 실행
    ↓
Streaming Buffer (수 분 ~ 90분)
    ↓
Columnar Storage (영구 저장)
```

### 4.2 Streaming Buffer 제한

| 작업 | Buffer 내 레코드 | Buffer 외 레코드 |
|------|-----------------|-----------------|
| SELECT | ✅ 가능 | ✅ 가능 |
| INSERT | ✅ 가능 | ✅ 가능 |
| UPDATE | ❌ 불가 | ✅ 가능 |
| DELETE | ❌ 불가 | ✅ 가능 |

### 4.3 우리 코드의 TIME_INTERVAL

```python
# query_util.py
TIME_INTERVAL = 90  # 분

# delete_history 메서드
DELETE FROM table
WHERE created_at <= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {TIME_INTERVAL} MINUTE)
```

이 제한은 BigQuery 인프라 제한을 반영한 것입니다.

---

## 5. 최종 구현

### 5.1 collect-manager API 수정

**파일**: `app/main/service/crawl_job_history_service.py`

```python
@staticmethod
def delete_hai_history(customer_code, source_type, source_id, ingestion_id):
    """Reset HAI file history only (file_name contains '_HAI')

    This method follows the same pattern as reset_history:
    1. DELETE old records (90+ minutes old, TIME_INTERVAL restriction)
    2. Query remaining HAI records (status != fail)
    3. INSERT fail status for remaining records to invalidate them

    This approach handles both old records (actual delete) and recent records
    (fail status insertion) to avoid streaming buffer issues.
    """
    from google.cloud import bigquery
    from app.main.util.util import convert_ingestion_id_to_timestamp_str

    try:
        client = BigQueryClient.instance().get_client()

        # Step 1: DELETE old HAI records (with TIME_INTERVAL restriction)
        delete_query = f"""
            DELETE FROM `{CRAWL_JOB_HISTORY_TABLE}`
            WHERE customer_code = @customer_code
            AND source_type = @source_type
            AND source_id = @source_id
            AND ingestion_id = @ingestion_id
            AND file_name LIKE '%_HAI%'
            AND created_at <= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 MINUTE)
        """
        query_params = [
            bigquery.ScalarQueryParameter("customer_code", "STRING", customer_code),
            bigquery.ScalarQueryParameter("source_type", "STRING", source_type),
            bigquery.ScalarQueryParameter("source_id", "STRING", source_id),
            bigquery.ScalarQueryParameter("ingestion_id", "STRING",
                                          convert_ingestion_id_to_timestamp_str(ingestion_id))
        ]
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        client.query(delete_query, job_config=job_config).result()

        # Step 2: Query remaining HAI records (latest, non-fail status)
        query_job = CommonJobHistoryQuery.get_last_history_by_ingestion_id(
            customer_code=customer_code,
            source_type=source_type,
            source_id=source_id,
            ingestion_id=ingestion_id,
            table_name=CRAWL_JOB_HISTORY_TABLE,
            item_id_field_names=CrawlJobHistoryService.CRAWL_TABLE_ITEM_ID,
            filter_options=[
                CommonJobHistoryQuery.build_filter_option(
                    "status", "STRING", const.JOB_HISTORY_RESULT_FAIL, "!="
                )
            ]
        )

        # Step 3: Filter HAI files and prepare fail records
        query_items = []
        for row in query_job:
            record = dict(row)
            file_name = record.get('file_name', '')
            if '_HAI' not in file_name:
                continue  # Skip non-HAI files
            record["status"] = const.JOB_HISTORY_RESULT_FAIL
            record["created_at"] = str(datetime.datetime.now(tz=pytz.utc))
            record["ingestion_id"] = str(record["ingestion_id"])
            query_items.append(record)

        # Step 4: INSERT fail records to invalidate remaining HAI history
        if len(query_items) > 0:
            errors = client.insert_rows_json(CRAWL_JOB_HISTORY_TABLE, query_items)
            if errors:
                raise Exception(f"Encountered errors while inserting rows: {errors}")

        return response_ok(f"HAI history reset successfully. Invalidated {len(query_items)} records.")
    except Exception as e:
        raise response_exc(ServerError(f"Encountered errors while resetting HAI history: {e}"))
```

### 5.2 API Endpoint 추가

**파일**: `app/main/controller/job_history_controller.py`

```python
@api.route('/crawl/<customer_code>/<source_type>/<source_id>/ingestion_id/<ingestion_id>/hai')
class HaiJobHistory(Resource):
    @api.doc('delete HAI file crawl job history only')
    def delete(self, customer_code, source_type, source_id, ingestion_id):
        """Delete HAI file crawl job history only (file_name contains '_HAI')"""
        return CrawlJobHistoryService.delete_hai_history(
            customer_code=customer_code,
            source_type=source_type,
            source_id=source_id,
            ingestion_id=ingestion_id
        )
```

### 5.3 hai-renamer-service 수정

**파일**: `common/utils.py`

```python
def delete_request(endpoint, token_generator=None, **kwargs):
    headers = {}
    if token_generator:
        auth_headers = token_generator.get_header_options()
        if auth_headers: headers.update(auth_headers)

    try:
        response = requests.delete(endpoint, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to DELETE request to {endpoint}: {e}", exc_info=True)
        raise


def delete_hai_history(api_svr_url, customer_code, source_type, source_id,
                       ingestion_id, token_generator=None):
    """Delete HAI file history records before re-inserting to avoid duplicates."""
    delete_url = (f"{api_svr_url}/job_history/crawl/{customer_code}/{source_type}/"
                  f"{source_id}/ingestion_id/{ingestion_id}/hai")
    try:
        res = delete_request(endpoint=delete_url, token_generator=token_generator)
        logger.info(f"Successfully deleted HAI history: {res}")
        return res
    except Exception as e:
        # HAI history 삭제 실패는 warning으로 처리하고 계속 진행
        logger.warning(f"Failed to delete HAI history. Continuing anyway. Error: {e}")
        return None
```

**파일**: `app/logic.py`

```python
# rename 실행 전에 HAI history 삭제 (중복 방지)
delete_hai_history(
    api_svr_url=api_svr_url,
    customer_code=customer_code,
    source_type=source_type,
    source_id=source_id,
    ingestion_id=ingestion_id,
    token_generator=token_generator
)

# 핵심 로직 실행
renamer.rename(crawl_history=crawl_history)
```

---

## 6. ROW_NUMBER() 패턴의 중요성

### 6.1 모든 History 조회가 ROW_NUMBER() 사용

```sql
WITH ranked_log AS (
    SELECT *,
           ROW_NUMBER() OVER (
               PARTITION BY file_name, ingestion_id
               ORDER BY created_at DESC
           ) AS rn
    FROM crawl_job_history
    WHERE customer_code = @customer_code
      AND ingestion_id = @ingestion_id
)
SELECT * FROM ranked_log
WHERE rn = 1  -- 파일당 최신 1개만
AND status = 'success'  -- 그 중 success만
```

### 6.2 레코드 누적 시 동작

```
파일: A.xlsx
┌─────────────┬─────────┬─────┐
│ created_at  │ status  │ rn  │
├─────────────┼─────────┼─────┤
│ 06:41:30    │ success │ 1   │ ← 반환됨
│ 06:41:17    │ fail    │ 2   │
│ 06:40:27    │ success │ 3   │
│ 06:14:14    │ fail    │ 4   │
└─────────────┴─────────┴─────┘
```

### 6.3 fail INSERT가 필요한 이유

**Q: success가 여러 개여도 rn=1만 반환하면 되는 거 아닌가?**

A: 정상 동작 시에는 맞습니다. 하지만 에러 상황을 고려해야 합니다:

```
[rename 실패 시 - fail INSERT 없는 경우]
1. delete_hai_history → 아무것도 안 함
2. rename 실패 (에러 발생)
3. 결과: 기존 success가 rn=1
4. 파일이 재처리 안 됨 ❌

[rename 실패 시 - fail INSERT 있는 경우]
1. delete_hai_history → fail INSERT
2. rename 실패 (에러 발생)
3. 결과: fail이 rn=1 → 필터링되어 반환 안 됨
4. 다음 실행 시 파일 재처리됨 ✅
```

**fail INSERT는 에러 복구를 위한 안전장치입니다.**

---

## 7. 테스트 결과

### 7.1 HAI Renamer 2회 연속 실행

```bash
# 1차 실행
curl -X POST "https://hai-renamer-service-.../rename-hai-files" \
  -d '{"ingestion_id": "20260113140000", ...}'
# → Successfully processed 1 sources: ['s12bf560']

# 2차 실행
curl -X POST "https://hai-renamer-service-.../rename-hai-files" \
  -d '{"ingestion_id": "20260113140000", ...}'
# → Successfully processed 1 sources: ['s12bf560']
```

### 7.2 BigQuery 확인

```sql
-- 전체 레코드 수
SELECT status, COUNT(*) as cnt
FROM crawl_job_history
WHERE file_name LIKE '%_HAI%'
GROUP BY status;

-- 결과: success 140개, fail 140개 (2회 × 70파일)
```

```sql
-- ROW_NUMBER 적용 시
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (...) as rn
  FROM crawl_job_history
)
SELECT status, COUNT(*) FROM ranked WHERE rn=1 GROUP BY status;

-- 결과: success 70개만 (중복 없음!)
```

---

## 8. 핵심 교훈

### 8.1 BigQuery 특성 이해
- Streaming Buffer 제한으로 최근 레코드 UPDATE/DELETE 불가
- 이를 우회하려면 "논리적 삭제" (fail INSERT) 패턴 사용

### 8.2 방어적 프로그래밍
- 정상 케이스뿐 아니라 에러 케이스도 고려
- fail INSERT는 에러 복구를 위한 안전장치

### 8.3 기존 패턴 활용
- `reset_history` 메서드가 이미 같은 패턴 사용 중
- 새 기능 개발 시 기존 코드 패턴 참고

### 8.4 테스트의 중요성
- 로컬 테스트 → 프로덕션 배포 → BigQuery 검증
- ROW_NUMBER() 적용 결과까지 확인해야 완료

---

## 9. 관련 파일

### collect-manager
- `app/main/controller/job_history_controller.py` - API endpoint
- `app/main/service/crawl_job_history_service.py` - delete_hai_history 메서드
- `app/main/util/query_util.py` - ROW_NUMBER 쿼리 패턴

### hai-renamer-service
- `common/utils.py` - delete_request, delete_hai_history 함수
- `app/logic.py` - process_renaming_request에서 삭제 호출

---

## 10. API 사용법

```bash
# HAI History 삭제 (reset_history 패턴)
curl -X DELETE \
  "https://collect-manager-prod-.../job_history/crawl/{customer_code}/{source_type}/{source_id}/ingestion_id/{ingestion_id}/hai" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# 응답 예시
{"message": "HAI history reset successfully. Invalidated 70 records."}
```

---

## 부록: 참고 문서

- [BigQuery Streaming Insert 공식 문서](https://cloud.google.com/bigquery/docs/streaming-data-into-bigquery)
- [BigQuery DML 제한사항](https://cloud.google.com/bigquery/docs/reference/standard-sql/data-manipulation-language)
