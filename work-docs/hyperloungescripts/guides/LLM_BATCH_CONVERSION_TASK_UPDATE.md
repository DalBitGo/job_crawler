# Airflow LLM Batch Conversion Task 업데이트

## 작업 일자
2025-11-18

## 수정 파일
- `/airflow-dags/dags/dependencies/task_functions.py`
  - `llm_convert_batch` 함수 (line 1318~1600)

## 수정 내용

### 1. 인증 방식 수정
- **문제**: Access Token 사용으로 401 Unauthorized 에러 발생
- **해결**: Google ID Token으로 변경
```python
# 변경 전
credentials.token  # Access Token

# 변경 후
google.oauth2.id_token.fetch_id_token(auth_req, service_url)  # ID Token
```

### 2. DB 직접 조회 구현
- **문제**: file_id, prompt_id 파라미터 누락으로 422 에러 발생
- **해결**: Ontology DB에서 변환 대상 직접 조회
```python
# DB 연결 정보
host: 10.67.96.7
port: 5432
dbname: ontology_dashboard
user: ontology_user

# 조회 쿼리
SELECT DISTINCT fpj.file_id, fpj.prompt_id
FROM file_prompt_junction fpj
INNER JOIN file_ontology f ON ...
WHERE fpj.tenant_code = %s
  AND fpj.is_active = true
  AND f.is_active = true
  AND f.is_deleted = false
```

### 3. 병렬 처리 구현
- ThreadPoolExecutor 사용
- 기본 5개 worker 동시 실행
- `llm_parallel_workers` 파라미터로 조절 가능

### 4. 에러 처리 개선
- **파일 미존재**: skip 처리 (task 성공)
- **실제 에러**: real_error로 카운트 (task 실패)
- 파일별 성공/실패 상세 로그 출력

```python
# 에러 분류
if "파일을 찾을 수 없습니다" in error_msg:
    file_not_found_count += 1  # skip
else:
    real_error_count += 1  # 실패

# task 실패 조건
if real_error_count > 0:
    raise AirflowFailException(...)
```

### 5. 로그 출력 형식
```
================================================================================
LLM Batch Conversion Summary:
  Total Targets: 56
  Succeeded: 56
  Failed: 0
================================================================================
  - File not found (skipped): 0
  - Real errors: 0
================================================================================
```

## 테스트 결과

| 고객사 | 코드 | 결과 | 비고 |
|--------|------|------|------|
| 에이텍 | cf526000 | 성공 | 파일 없음 → skip 처리 |
| 엘앤케이웰니스 | c8cd3500 | 성공 | 56건 요청 전송 완료 |

## 잔여 이슈 (Airflow 외부)

### LLM Converter Service 측
1. **HAI 파일 미생성**: 56개 성공 응답했으나 실제 17개만 생성
2. **BigQuery 업로드 에러**: 한글 인코딩 문제 (`Illegal input character "\352"`)
3. **에러 처리**: BigQuery 실패해도 success 반환

### Ontology DB
- 강릉점(GANGNEUNG) 미등록 → 변환 대상에서 누락

## 관련 DAG 파일
- `/airflow-dags/dags/cf526000.py` (에이텍)
- `/airflow-dags/dags/c8cd3500.py` (엘앤케이웰니스)
