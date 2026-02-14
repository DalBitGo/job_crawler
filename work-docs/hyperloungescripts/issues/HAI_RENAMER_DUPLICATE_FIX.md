# HAI Renamer 중복 History 문제 해결

## 문제 상황

### 증상
- c8cd3500 고객의 email 소스에서 HAI renamer 실행 시 crawl history에 중복 레코드 발생
- 동일한 파일에 대해 여러 개의 history 레코드가 생성됨

### 원인 분석
HAI renamer가 `is_init=True` AND `is_sync=True` 조건에서 실행될 때:
1. `ingestion_id` 폴더 **내부**를 탐색 (예: `crawl/20260113140000/`)
2. 이미 rename된 `_HAI` 파일들을 다시 발견
3. 기존 history를 삭제하지 않고 새 history를 추가 → 중복 발생

일반 renamer vs HAI renamer 차이:
- 일반 renamer: 파일명에 hash+date 추가 → 매번 다른 file_id 생성
- HAI renamer: 원본 파일명 유지 → 동일한 file_id 재사용

## 해결 방안

### 선택한 접근법
rename 실행 전에 기존 HAI history를 삭제하는 API 추가

### 대안 검토 (미채택)
1. status를 fail로 변경하는 방식 - reset_history에서 사용하지만 복잡함
2. collect_item DELETE API 사용 - GCS 파일까지 삭제되어 부적합

## 구현 내용

### 1. collect-manager: HAI History 삭제 API 추가

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

**파일**: `app/main/service/crawl_job_history_service.py`
```python
@staticmethod
def delete_hai_history(customer_code, source_type, source_id, ingestion_id):
    """Delete HAI file history only (file_name contains '_HAI')
    Note: This method does NOT have TIME_INTERVAL restriction unlike other delete methods,
    because HAI renamer needs to delete recently created records before re-inserting.
    """
    from google.cloud import bigquery
    from app.main.util.util import convert_ingestion_id_to_timestamp_str

    try:
        client = BigQueryClient.instance().get_client()
        delete_query = f"""
            DELETE FROM `{CRAWL_JOB_HISTORY_TABLE}`
            WHERE customer_code = @customer_code
            AND source_type = @source_type
            AND source_id = @source_id
            AND ingestion_id = @ingestion_id
            AND file_name LIKE '%_HAI%'
        """
        query_params = [
            bigquery.ScalarQueryParameter("customer_code", "STRING", customer_code),
            bigquery.ScalarQueryParameter("source_type", "STRING", source_type),
            bigquery.ScalarQueryParameter("source_id", "STRING", source_id),
            bigquery.ScalarQueryParameter("ingestion_id", "STRING",
                                          convert_ingestion_id_to_timestamp_str(ingestion_id))
        ]
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        result = client.query(delete_query, job_config=job_config).result()
        return response_ok(f"HAI history deleted successfully")
    except Exception as e:
        raise response_exc(ServerError(f"Encountered errors while deleting HAI history: {e}"))
```

**핵심 포인트**:
- `CommonJobHistoryQuery.delete_history()` 사용하지 않음 → TIME_INTERVAL 90분 제한 우회
- `file_name LIKE '%_HAI%'` 조건으로 HAI 파일만 삭제
- 일반 crawl history는 영향 없음

### 2. hai-renamer-service: rename 전 삭제 호출

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


def delete_hai_history(api_svr_url, customer_code, source_type, source_id, ingestion_id, token_generator=None):
    """
    Delete HAI file history records before re-inserting to avoid duplicates.
    This is necessary because HAI renamer may be called multiple times for the same ingestion_id.
    """
    delete_url = f"{api_svr_url}/job_history/crawl/{customer_code}/{source_type}/{source_id}/ingestion_id/{ingestion_id}/hai"
    try:
        res = delete_request(endpoint=delete_url, token_generator=token_generator)
        logger.info(f"Successfully deleted HAI history: {res}")
        return res
    except Exception as e:
        # HAI history 삭제 실패는 warning으로 처리하고 계속 진행
        # (history가 없을 수도 있으므로)
        logger.warning(f"Failed to delete HAI history (may not exist). Continuing anyway. Error: {e}")
        return None
```

**파일**: `app/logic.py`
```python
# 핵심 변경: rename 실행 전에 HAI history 삭제
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

## API 사용법

### HAI History 삭제 API
```bash
# Endpoint
DELETE /job_history/crawl/{customer_code}/{source_type}/{source_id}/ingestion_id/{ingestion_id}/hai

# 예시
curl -X DELETE "https://collect-manager-prod-l27zak4z4q-du.a.run.app/job_history/crawl/c8cd3500/email/s12bf560/ingestion_id/20260113140000/hai" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# 응답
{"message": "HAI history deleted successfully"}
```

## 주의사항

### BigQuery Streaming Buffer 제한
- BigQuery는 최근 INSERT된 레코드를 바로 DELETE할 수 없음 (수 분 ~ 90분 대기 필요)
- 이는 BigQuery 인프라 제한이며 우리 코드의 TIME_INTERVAL과는 다른 문제
- **실제 운영에서는 문제 없음**: HAI renamer는 LLM 변환 후 수 시간 뒤에 호출되므로 streaming buffer에 해당 안함

### TIME_INTERVAL vs Streaming Buffer
| 구분 | TIME_INTERVAL | Streaming Buffer |
|------|---------------|------------------|
| 원인 | 우리 코드 (query_util.py) | BigQuery 인프라 |
| 제한 시간 | 90분 | 수 분 ~ 90분 |
| 해결 | 직접 DELETE 쿼리로 우회 | 대기 필요 (우회 불가) |
| 영향 | ✅ 해결됨 | 실제 운영에서 문제 없음 |

## 배포 정보

### collect-manager-prod
- 배포 일시: 2026-01-22
- 이미지: `asia-northeast3-docker.pkg.dev/hyperlounge-dev/cloud-run-source-deploy/collect-manager-prod`

### hai-renamer-service
- 배포 일시: 2026-01-22
- 이미지: Cloud Run source deploy

## 테스트 결과

### API 테스트
| API | 결과 |
|-----|------|
| GET /company | ✅ 정상 |
| GET /source_meta/{customer_code} | ✅ 정상 |
| DELETE /job_history/crawl/.../hai | ✅ 정상 |

### 통합 테스트
- 로컬 환경에서 HAI history 삭제 후 재생성 확인
- 프로덕션 API 호출 정상 확인

## 관련 파일

### collect-manager
- `app/main/controller/job_history_controller.py` - HAI 삭제 엔드포인트
- `app/main/service/crawl_job_history_service.py` - delete_hai_history 메서드

### hai-renamer-service
- `common/utils.py` - delete_request, delete_hai_history 함수
- `app/logic.py` - process_renaming_request에서 삭제 호출

## 향후 모니터링
- c8cd3500 고객 email 소스 DAG 실행 시 중복 history 발생 여부 확인
- BigQuery `crawl_job_history` 테이블에서 `_HAI` 파일 중복 여부 모니터링
