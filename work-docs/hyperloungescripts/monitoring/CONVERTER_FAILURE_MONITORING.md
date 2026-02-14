# Converter 실패 모니터링 설계

## 배경

### 현재 상황
- **Converter**: 엑셀 파일에서 테이블 추출하는 핵심 컴포넌트
- **Convert Config**: JSON 형태로 시트별/테이블별 추출 규칙 정의
  - 예: `c0159c00/eml_gi00_011.json`
  - 헤더 위치, 컬럼 범위, 시트명 등 정의
- **실행 기록**: `convert_job_history` 테이블 (customer_code 파티션)
  - `status`: "success" / "fail"
  - `error_message`: 에러 내용
  - `convert_config_id`: 사용한 config ID
  - `gcs_path`: 원본 파일 경로

### 요구사항
1. **아침마다 Teams로 자동 리포트** (기존 `airflow_dag_monitor` 스타일)
2. **고객사별로 한눈에 파악 가능**
3. **에러 유형 분류** (헤더 에러, 시트 에러 등)
4. **메시지 길이 제한** 고려 (Teams 메시지)
5. **(선택) LLM 분석** 추가 가능성
6. **상세 정보는 링크**로 제공

---

## Converter 로직 구조

### 핵심 흐름
```
1. Config 로드 (JSON)
   ↓
2. 엑셀 시트 읽기 (pandas)
   ↓
3. 헤더 스캔 (동적으로 헤더 위치 찾기)
   - "구분", "매출" 같은 키워드로 시작 행 탐색
   ↓
4. 데이터 추출 (cols, rows 범위)
   ↓
5. Normalization (헤더명 정규화)
   ↓
6. Type Conversion
   ↓
7. Tagging (메타데이터 태깅)
```

### 주요 실패 지점
1. **시트 매칭 실패**
   - Config의 시트명 regex와 실제 시트명 불일치
   - 예: "약효" → "약효분류"로 변경

2. **헤더 찾기 실패**
   - `header_coordinate`에 정의된 헤더명을 찾지 못함
   - 예: "구분" → "종류"로 변경
   - 예: "매출" → "매출액"으로 변경

3. **컬럼 범위 에러**
   - `cols: "A:D"` 범위가 실제 엑셀과 불일치
   - `usecols out of bounds` 에러

4. **시스템 에러**
   - Timeout (대용량 파일)
   - 메모리 부족
   - 파일 손상

---

## 에러 분류 체계

### 자동 분류 로직

```python
def classify_error(error_message: str) -> str:
    """에러 메시지를 패턴 매칭으로 분류"""
    if not error_message:
        return "Unknown"

    patterns = {
        "헤더 에러": [
            r"Header .* not found",
            r"Cannot find header",
            r"Missing column",
            r"header_coordinate",
        ],
        "시트 에러": [
            r"Sheet .* not found",
            r"Worksheet .* does not exist",
            r"No sheet named",
        ],
        "Timeout": [
            r"[Tt]imeout",
            r"exceed.*time limit",
            r"timed out",
        ],
        "메모리 부족": [
            r"[Oo]ut of [Mm]emory",
            r"MemoryError",
        ],
        "파일 손상": [
            r"corrupt",
            r"damaged",
            r"cannot.*read.*file",
        ],
        "컬럼 범위": [
            r"usecols.*out of bounds",
            r"invalid column range",
        ],
    }

    for error_type, regex_list in patterns.items():
        for regex in regex_list:
            if re.search(regex, error_message, re.IGNORECASE):
                return error_type

    return "기타"
```

### 에러 유형별 조치 가이드

| 에러 유형 | 주요 원인 | 조치 방법 |
|---------|---------|---------|
| 헤더 에러 | 엑셀 헤더명 변경 | Config JSON에서 헤더명 업데이트 |
| 시트 에러 | 시트명 변경 | Config JSON에서 시트명 패턴 수정 |
| 컬럼 범위 | 엑셀 컬럼 구조 변경 | Config JSON에서 cols 범위 조정 |
| Timeout | 파일 크기 과대 | GCF 메모리/시간 증설 또는 파일 분할 |
| 메모리 부족 | 데이터 과다 | GCF 메모리 증설 |
| 파일 손상 | 업로드 에러 | 원본 파일 재수집 |

---

## 모니터링 메시지 설계 옵션

### 옵션 A: 에러 유형별 요약 (간결)

**장점**:
- 에러 패턴 파악 용이
- 짧고 스캔 빠름
- 에러 유형별 트렌드 확인 가능

**단점**:
- 특정 고객사 빠르게 찾기 어려움
- 고객사별 상황 파악에는 부적합

**예시**:
```
📊 Converter 실패 리포트 - 2025-11-09

전체 현황: 총 1,247건 실행 / 15건 실패 (1.2%)

━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 헤더 에러 (7건)
━━━━━━━━━━━━━━━━━━━━━━━━━━
• GC녹십자 (c0159c00) - 3건
  └ erp_sa00_011: Header 'GST' not found
• 고피자 (c7005b01) - 2건
  └ pos_daily: Header '매출' not found
• 한투 (c8cd3500) - 2건

━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 시트 에러 (5건)
━━━━━━━━━━━━━━━━━━━━━━━━━━
• 매일홀딩스 (c2026600) - 3건
  └ sales_report: Sheet '일별매출' not found
• 스파젠뷰티 (caaa3b00) - 2건

━━━━━━━━━━━━━━━━━━━━━━━━━━
⏱️ Timeout (2건)
━━━━━━━━━━━━━━━━━━━━━━━━━━
• 제주맥주 (c4cd3b00) - 1건
  └ monthly_stock: 파일 크기 25MB
• 한화생명 (c1d66200) - 1건

━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 기타 (1건)
━━━━━━━━━━━━━━━━━━━━━━━━━━
• 보령제약 (c3a40f00) - 1건
  └ usecols out of bounds

🔗 상세 보기: [BigQuery 콘솔]
```

---

### 옵션 B: 고객사별 테이블 (상세)

**장점**:
- 고객사 중심 관점
- 특정 고객사 문제 빠르게 확인
- Airflow DAG Monitor와 유사한 형태

**단점**:
- 고객사 많으면 메시지 너무 길어짐
- 에러 패턴 파악 어려움
- Teams 메시지 길이 제한 초과 가능

**예시**:
```
📊 Converter 실패 리포트 - 2025-11-09
전체: 1,247건 / 실패: 15건 (1.2%)

고객사           Config ID        실패 유형    건수
─────────────────────────────────────────────
GC녹십자         erp_sa00_011     헤더에러     3
(c0159c00)       └ Header 'GST' not found

고피자           pos_daily        헤더에러     2
(c7005b01)       └ Header '매출' not found

매일홀딩스       sales_report     시트에러     3
(c2026600)       └ Sheet '일별매출' not found

제주맥주         monthly_stock    Timeout      1
(c4cd3b00)       └ 25MB file

보령제약         inventory        기타         1
(c3a40f00)       └ usecols out of bounds

🔗 상세: [BigQuery 링크]
```

---

### 옵션 C: 하이브리드 (간결 요약 + 중요 항목만 상세) ⭐ 추천

**장점**:
- 전체 상황 + 중요 항목 모두 파악 가능
- 메시지 길이 제어 가능
- 에러 패턴과 고객사별 상황 모두 확인 가능
- **반복 실패 항목만** 상세 표시로 집중도 높임

**단점**:
- 구현 복잡도 약간 높음

**예시**:
```
📊 Converter 실패 리포트 - 2025-11-09
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 성공: 1,232건 | ❌ 실패: 15건 (1.2%)

🔴 주요 실패 유형
• 헤더 에러: 7건 (GC녹십자 3, 고피자 2, 한투 2)
• 시트 에러: 5건 (매일홀딩스 3, 스파젠뷰티 2)
• Timeout: 2건 (제주맥주, 한화생명)
• 기타: 1건

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 즉시 확인 필요 (반복 실패 3회 이상)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GC녹십자 (c0159c00) - 5회 연속 실패
   └ erp_sa00_011: Header 'GST' not found
   🔗 상세: [BigQuery 링크] | 📝 Config: [GitHub 링크]

2. 매일홀딩스 (c2026600) - 3회 연속 실패
   └ sales_report: Sheet '일별매출' not found
   🔗 상세: [BigQuery 링크] | 📝 Config: [GitHub 링크]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 전체 상세 리포트
🔗 BigQuery 쿼리: [전체 실패 목록 보기]
🔗 Grafana 대시보드: [Convert Task Dashboard]
```

**핵심 아이디어**:
- 상단: 전체 통계 (숫자만)
- 중간: 에러 유형별 간단 요약
- **하단: 즉시 조치 필요한 항목만** (반복 실패 N회 이상)
- 나머지는 링크로

---

## 추천 의견: 옵션 C (하이브리드)

### 추천 이유

1. **정보 계층화**
   - 상단: 빠른 스캔 (전체 상황)
   - 중간: 에러 패턴 파악
   - 하단: 액션 아이템 (즉시 조치 필요)

2. **노이즈 제거**
   - 1-2회 실패는 일시적일 수 있음 (네트워크, 파일 업로드 중 등)
   - **반복 실패만** 상세 표시 → S/N비 높음

3. **길이 제어**
   - 평상시: 짧고 간결
   - 문제 많을 때: 반복 실패 항목만 표시
   - 전체는 링크로

4. **기존 워크플로우 유지**
   - 팀원들이 이미 익숙한 Airflow DAG Monitor와 유사한 구조
   - 학습 곡선 낮음

### 반복 실패 기준 제안

- **3회 이상 연속 실패**: 즉시 확인 필요 섹션에 표시
- **1-2회 실패**: 요약에만 포함, 상세는 링크로

### 구현 복잡도

**간단한 부분**:
- BigQuery 쿼리
- 에러 분류 (정규식)
- Teams 메시지 포맷팅

**조금 복잡한 부분**:
- 반복 실패 감지 (최근 N일간 같은 config_id 실패 카운트)
- 링크 생성 (BigQuery 콘솔, GitHub config 파일)

---

## LLM 분석 추가 (선택사항)

### 가능한 분석

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 AI 분석 요약
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• GC녹십자 (c0159c00): 최근 엑셀 파일 포맷 변경 추정
  └ 'GST' → 'GST_금액'으로 헤더명 변경된 것으로 추정
  💡 조치: config erp_sa00_011.json의 헤더명 업데이트 필요

• 매일홀딩스 (c2026600): 시트명 변경 감지
  └ '일별매출' → '일별_매출현황'으로 변경된 것으로 추정
  💡 조치: config sales_report.json의 시트명 수정 필요
```

### 한계점
- **에러 메시지만으로는 정확한 원인 파악 어려움**
- 실제 엑셀 파일을 읽어봐야 정확한 분석 가능
- LLM 비용 고려 필요

### 대안: 휴리스틱 분석
LLM 대신 간단한 규칙 기반:
```python
if "Header 'GST' not found":
    suggest = "💡 Config에서 'GST' 헤더명을 확인하고, 실제 파일의 헤더명과 일치하는지 검증 필요"
elif "Sheet '일별매출' not found":
    suggest = "💡 실제 엑셀 파일의 시트 목록을 확인하고, Config의 시트명 업데이트 필요"
```

---

## 구현 계획

### Phase 1: 기본 모니터링 (1-2일)
- [ ] BigQuery 쿼리 작성
  - 어제 실패 건 조회
  - 에러 메시지별 그룹핑
  - 고객사별 집계
- [ ] 에러 분류 로직 구현
- [ ] Teams 메시지 포맷팅 (옵션 C)
- [ ] Cloud Function 배포
- [ ] Cloud Scheduler 설정 (매일 오전 8시)

### Phase 2: 반복 실패 감지 (0.5일)
- [ ] 최근 N일간 실패 이력 조회
- [ ] 같은 config_id 실패 카운트
- [ ] 임계값 설정 (3회 이상)

### Phase 3: 링크 생성 (0.5일)
- [ ] BigQuery 콘솔 URL 자동 생성
- [ ] GitHub Config 파일 링크
- [ ] Grafana 대시보드 링크

### Phase 4: (선택) LLM 분석 (1-2일)
- [ ] 에러 메시지 → LLM 프롬프트
- [ ] 조치 제안 생성
- [ ] 비용/효과 검증

---

## BigQuery 쿼리 (초안)

### 어제 실패 건 조회 + 에러 분류
```sql
WITH error_classification AS (
  SELECT
    customer_code,
    customer_name,
    convert_config_id,
    error_message,
    COUNT(*) as fail_count,
    ARRAY_AGG(
      STRUCT(gcs_path, created_at)
      ORDER BY created_at DESC
      LIMIT 3
    ) as recent_cases,

    -- 에러 분류
    CASE
      WHEN REGEXP_CONTAINS(error_message, r"(?i)Header .* not found") THEN '헤더 에러'
      WHEN REGEXP_CONTAINS(error_message, r"(?i)Sheet .* not found") THEN '시트 에러'
      WHEN REGEXP_CONTAINS(error_message, r"(?i)timeout") THEN 'Timeout'
      WHEN REGEXP_CONTAINS(error_message, r"(?i)out of memory") THEN '메모리 부족'
      WHEN REGEXP_CONTAINS(error_message, r"(?i)usecols.*out of bounds") THEN '컬럼 범위'
      ELSE '기타'
    END as error_type

  FROM `hyperlounge-dev.dashboard.convert_job_history`
  WHERE DATE(created_at, 'Asia/Seoul') = CURRENT_DATE('Asia/Seoul') - 1
    AND status = 'fail'
  GROUP BY customer_code, customer_name, convert_config_id, error_message
)

SELECT
  error_type,
  customer_code,
  customer_name,
  convert_config_id,
  error_message,
  fail_count,
  recent_cases
FROM error_classification
ORDER BY error_type, fail_count DESC
```

### 반복 실패 감지
```sql
WITH recent_failures AS (
  SELECT
    customer_code,
    customer_name,
    convert_config_id,
    DATE(created_at, 'Asia/Seoul') as fail_date,
    COUNT(*) as daily_fail_count
  FROM `hyperlounge-dev.dashboard.convert_job_history`
  WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    AND status = 'fail'
  GROUP BY customer_code, customer_name, convert_config_id, fail_date
)

SELECT
  customer_code,
  customer_name,
  convert_config_id,
  COUNT(DISTINCT fail_date) as consecutive_fail_days,
  SUM(daily_fail_count) as total_fail_count
FROM recent_failures
GROUP BY customer_code, customer_name, convert_config_id
HAVING consecutive_fail_days >= 3  -- 3일 이상 연속 실패
ORDER BY consecutive_fail_days DESC, total_fail_count DESC
```

---

## 참고 자료

### 기존 모니터링 시스템
- `airflow_dag_monitor/main.py`: Airflow DAG 실행 상태 모니터링
- `collector/deploy/collect_history_checker/`: Collect 작업 히스토리 체크

### 관련 테이블
- `dashboard.convert_job_history`: Converter 실행 기록
- `dashboard.convert_job_history_v2`: V2 스키마

### Config 파일 위치
- `collector/c{customer_code}/{config_id}.json`
- 예: `collector/c0159c00/eml_gi00_011.json`

---

## 추가 고려사항 (2025-11-10 논의)

### 문제 1: 에러 양이 매우 많을 수 있음

**원인**:
- Converter는 **테이블 단위**로 실패 기록
- 엑셀 파일 1개 → 시트 10개 → 각 시트에 테이블 2-3개
- **하나의 파일 문제**가 **수십 건의 에러**로 증폭됨

**예시**:
```
파일: sales_2025-11-09.xlsx (시트 10개)
├─ 시트1 "일별매출" → 테이블 3개 실패 (헤더 변경)
├─ 시트2 "월별매출" → 테이블 2개 실패 (헤더 변경)
├─ ...
└─ 총 25건 실패 (실제로는 1개 파일의 1개 문제)
```

**해결 방안**:
1. **파일별 그룹핑** ⭐ 추천
   ```
   ❌ GC녹십자 - sales_2025-11-09.xlsx (25건 실패)
      └ 원인: Header 'GST' not found
      └ 영향 테이블: erp_sa00_011 외 12개
   ```
   - 같은 `gcs_path` 묶어서 1개 항목으로 표시
   - 실제 파일 수 = 실제 대응해야 할 건수

2. **에러 메시지별 그룹핑**
   ```
   ❌ Header 'GST' not found - 25건
      └ GC녹십자: 3개 파일
      └ 한투: 2개 파일
   ```
   - 같은 에러 = 같은 config 수정으로 해결 가능

3. **임계값 조정**
   - ~~건수 기준~~이 아니라 **파일 개수 기준**
   - "같은 config가 3개 파일에서 연속 실패" → 경고

---

### 문제 2: Noise - 잘못된 파일 업로드

**시나리오**:
1. **고객사가 잘못된 파일 업로드**
   - 다른 양식의 파일
   - 빈 파일
   - 손상된 파일
2. Converter는 당연히 실패
3. 근데 이건 **config 문제가 아님** (원본 파일 문제)
4. **구분이 안 됨** ← 핵심 문제!

**현재 상황**:
```sql
-- convert_job_history 테이블
status = 'fail'
error_message = 'Header 구분 not found'

Q: 이게 config 문제? 파일 문제?
A: 알 수 없음
```

**가능한 구분 방법**:

#### 옵션 1: 파일명 패턴 체크
```python
# 정상 파일명 패턴
normal_pattern = r"sales_\d{4}-\d{2}-\d{2}\.xlsx"

if not re.match(normal_pattern, filename):
    noise_type = "파일명 이상"
```
**한계**: 파일명은 맞는데 내용이 다른 경우 구분 불가

#### 옵션 2: 에러 메시지 패턴 분석 ⭐
```python
# Config 문제일 가능성 높음
config_error_patterns = [
    "Header .* not found",      # 헤더명 변경
    "Sheet .* not found",        # 시트명 변경
    "usecols out of bounds",     # 컬럼 범위 변경
]

# 파일 문제일 가능성 높음
file_error_patterns = [
    "corrupt",                   # 파일 손상
    "cannot read file",          # 읽기 불가
    "empty.*sheet",              # 빈 시트
    "no sheets found",           # 시트 없음
]

# 애매함 - 둘 다 가능
ambiguous_patterns = [
    "timeout",                   # 파일 크기? 시스템?
    "out of memory",             # 파일 크기? 시스템?
]
```
**장점**: 추가 인프라 불필요
**한계**: 100% 정확하지 않음

#### 옵션 3: 과거 성공 이력 비교 ⭐⭐
```sql
WITH recent_history AS (
  SELECT
    customer_code,
    convert_config_id,
    COUNT(CASE WHEN status = 'success' THEN 1 END) as success_count,
    COUNT(CASE WHEN status = 'fail' THEN 1 END) as fail_count
  FROM convert_job_history
  WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  GROUP BY customer_code, convert_config_id
)

-- 과거 30일간 성공한 적 있음 → Config는 정상, 파일 문제일 가능성 높음
-- 과거 30일간 한 번도 성공 안 함 → Config 문제일 가능성 높음
```
**장점**: 가장 신뢰도 높음
**단점**: 신규 고객사는 판단 불가

#### 옵션 4: 같은 날 다른 파일 성공 여부 ⭐⭐⭐ 최고
```sql
-- 같은 날, 같은 config_id로 다른 파일들은 성공했는가?
WITH todays_results AS (
  SELECT
    customer_code,
    convert_config_id,
    DATE(created_at) as date,
    COUNT(DISTINCT CASE WHEN status = 'success' THEN gcs_path END) as success_files,
    COUNT(DISTINCT CASE WHEN status = 'fail' THEN gcs_path END) as fail_files
  FROM convert_job_history
  WHERE DATE(created_at) = CURRENT_DATE() - 1
  GROUP BY customer_code, convert_config_id, date
)

-- success_files > 0 AND fail_files > 0
-- → 같은 config로 어떤 파일은 성공, 어떤 파일은 실패
-- → 실패한 파일이 문제일 가능성 높음 (Noise)

-- success_files = 0 AND fail_files > 0
-- → 모든 파일이 실패
-- → Config 문제일 가능성 높음 (진짜 에러)
```
**장점**:
- 같은 날 기준이라 신뢰도 높음
- 신규 고객사도 판단 가능
**단점**:
- 하루에 파일 1개만 오는 경우 판단 불가

#### 옵션 5: 하이브리드 (3 + 4) ⭐⭐⭐ 최종 추천
```python
def classify_failure_type(row):
    """
    실패를 '진짜 에러' vs 'Noise'로 분류
    """
    # 1. 같은 날 다른 파일 성공 여부 확인
    if row['same_day_success_files'] > 0:
        return "Noise (특정 파일 문제)"

    # 2. 과거 30일간 성공 이력 확인
    if row['past_30d_success_count'] > 0:
        return "Noise (일시적 문제)"

    # 3. 과거 이력 없음 → Config 문제 가능성 높음
    if row['past_30d_total_count'] == 0:
        return "신규 Config (검증 필요)"

    # 4. 과거에도 계속 실패
    if row['past_30d_fail_rate'] > 0.8:
        return "진짜 에러 (Config 수정 필요)"

    return "확인 필요"
```

---

### 문제 3: 실제 대응이 목표

**현재 문제**:
- 에러 100건 나와도 실제로는 파일 2-3개 문제일 수 있음
- 또는 Config 1개만 수정하면 해결될 수 있음
- **뭘 고쳐야 하는지가 명확하지 않음**

**필요한 정보**:
```
✅ 이상적인 리포트:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 즉시 조치 필요 (Config 수정)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GC녹십자 - erp_sa00_011
   ├ 실패: 연속 5일, 총 125건
   ├ 원인: Header 'GST' not found
   ├ 영향: 매일 25개 테이블 실패 중
   └ 조치: Config 헤더명 'GST' → 'GST_금액' 수정
   🔗 Config: [GitHub] | 🔗 실패 파일: [GCS]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Noise (파일 문제 - Config 수정 불필요)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 매일홀딩스 - sales_report
  └ 어제 3개 파일 중 1개만 실패 (나머지 2개 성공)
  └ 원인: 파일 손상 or 잘못된 양식
  └ 조치: 고객사에 파일 재전송 요청
```

**핵심**:
1. **"진짜 에러" vs "Noise" 구분**
2. **파일 개수 기준**으로 표시 (테이블 건수 아님)
3. **조치 방법** 명시
   - Config 수정 필요 → 어느 필드?
   - 파일 문제 → 고객사 문의
   - 시스템 문제 → 인프라 팀

---

## 개선된 설계 방향

### 1. 데이터 수집 단계

```sql
WITH base_failures AS (
  -- 어제 실패 건
  SELECT *
  FROM convert_job_history
  WHERE DATE(created_at, 'Asia/Seoul') = CURRENT_DATE('Asia/Seoul') - 1
    AND status = 'fail'
),

file_level_summary AS (
  -- 파일별 그룹핑
  SELECT
    customer_code,
    customer_name,
    convert_config_id,
    gcs_path,
    error_message,
    COUNT(*) as table_fail_count,
    MIN(created_at) as first_fail,
    MAX(created_at) as last_fail
  FROM base_failures
  GROUP BY 1,2,3,4,5
),

same_day_context AS (
  -- 같은 날 같은 config의 성공/실패 파일 개수
  SELECT
    customer_code,
    convert_config_id,
    COUNT(DISTINCT CASE WHEN status = 'success' THEN gcs_path END) as success_files,
    COUNT(DISTINCT CASE WHEN status = 'fail' THEN gcs_path END) as fail_files
  FROM convert_job_history
  WHERE DATE(created_at, 'Asia/Seoul') = CURRENT_DATE('Asia/Seoul') - 1
  GROUP BY 1,2
),

historical_context AS (
  -- 과거 30일 성공률
  SELECT
    customer_code,
    convert_config_id,
    COUNT(*) as total,
    COUNTIF(status = 'success') as success,
    COUNTIF(status = 'fail') as fail,
    SAFE_DIVIDE(COUNTIF(status = 'fail'), COUNT(*)) as fail_rate
  FROM convert_job_history
  WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  GROUP BY 1,2
)

SELECT
  f.*,
  s.success_files,
  s.fail_files,
  h.total as hist_total,
  h.success as hist_success,
  h.fail_rate as hist_fail_rate,

  -- Noise 판정
  CASE
    WHEN s.success_files > 0 THEN 'Noise - 특정 파일 문제'
    WHEN h.success > 0 AND h.fail_rate < 0.2 THEN 'Noise - 일시적 문제'
    WHEN h.total = 0 THEN '신규 Config'
    WHEN h.fail_rate > 0.8 THEN '진짜 에러 - Config 수정 필요'
    ELSE '확인 필요'
  END as failure_category

FROM file_level_summary f
LEFT JOIN same_day_context s USING (customer_code, convert_config_id)
LEFT JOIN historical_context h USING (customer_code, convert_config_id)
```

### 2. 메시지 포맷 (개선)

```
📊 Converter 실패 리포트 - 2025-11-09
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 성공: 1,232건 | ❌ 실패: 125건 (실제 파일 12개)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 즉시 조치 필요 (Config 수정) - 2개 Config
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. GC녹십자 (c0159c00) - erp_sa00_011
   ├ 연속 5일 실패 (총 125건 = 5개 파일 x 25개 테이블)
   ├ 에러: Header 'GST' not found
   ├ 과거 30일: 성공률 95% → 최근 0%
   └ 💡 조치: Config 헤더명 확인 (엑셀 포맷 변경 추정)
   🔗 [Config] | 🔗 [실패 파일] | 🔗 [BigQuery]

2. 매일홀딩스 (c2026600) - sales_report
   ├ 연속 3일 실패 (총 45건 = 3개 파일 x 15개 테이블)
   ├ 에러: Sheet '일별매출' not found
   └ 💡 조치: Config 시트명 확인
   🔗 [Config] | 🔗 [실패 파일] | 🔗 [BigQuery]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 Noise (파일 문제) - 5개 파일
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 고피자 (c7005b01): 어제 10개 파일 중 2개만 실패
  └ 💡 조치: 고객사에 파일 재전송 요청 또는 무시

• 제주맥주 (c4cd3b00): 파일 손상
  └ 💡 조치: 원본 파일 재수집

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 상세 통계
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
에러 유형별:
• 헤더 에러: 75건 (3개 파일)
• 시트 에러: 45건 (3개 파일)
• 파일 손상: 5건 (5개 파일)

🔗 [전체 리포트 보기 - BigQuery]
```

---

### 3. 구현 우선순위 재조정

#### Phase 1: 핵심 기능 (2-3일)
- [ ] 파일별 그룹핑 로직
- [ ] Noise 판정 (같은 날 성공/실패 비교)
- [ ] 과거 성공률 계산
- [ ] "진짜 에러" vs "Noise" 분류
- [ ] 기본 Teams 메시지 (간단 버전)

#### Phase 2: 정확도 향상 (1-2일)
- [ ] 에러 메시지 패턴 매칭 정교화
- [ ] 연속 실패일수 계산
- [ ] 영향도 계산 (테이블 개수, 파일 개수)
- [ ] 조치 방법 자동 제안

#### Phase 3: 링크 및 편의 기능 (1일)
- [ ] BigQuery 콘솔 링크
- [ ] GCS 파일 링크
- [ ] GitHub Config 파일 링크
- [ ] Grafana 대시보드 링크

#### Phase 4: (선택) 고급 기능 (2-3일)
- [ ] LLM 기반 원인 분석
- [ ] 자동 config diff 생성
- [ ] Slack/Teams 인터랙티브 버튼 (무시/조치완료 등)

---

## 수집 방식에 따른 차별화 (2025-11-10 추가 논의)

### 배경: 수집 방식이 다름

#### 1. **일별 수집 (RPA/Board)** - 우리가 제어
- **특징**: 매일 정해진 시간에 우리 시스템이 수집
- **파일 생성**: 규칙적 (매일)
- **연속 실패 의미**: ✅ **있음**
  - 3일 연속 실패 = Config가 잘못된 게 거의 확실
  - 즉시 조치 필요

#### 2. **NonRPA (PC/Email/shared_drive)** - 고객이 제어
- **특징**: 고객사가 파일 올릴 때 수집
- **파일 생성**: 불규칙 (월 1회, 주 1회, 랜덤)
- **연속 실패 의미**: ❌ **없음**
  - "3회 반복 실패" 같은 개념 불필요
  - **어제 실패한 것만 보여주면 됨** (단순)

### 구분 기준: `source_type`

```sql
source_type IN ('rpa', 'board') → 일별 수집 (RPA/Board)
source_type IN ('pc', 'email', 'shared_drive') → 고객사 업로드 (NonRPA)
```

### 판정 로직 분기

```python
def get_failure_category(row):
    source_type = row['source_type']

    if source_type in ['rpa', 'board']:
        # 일별 수집: 연속 일수로 판단
        if row['consecutive_fail_days'] >= 3:
            return {
                'section': 'RPA/Board 연속 실패',
                'urgency': '🔴 즉시 조치 필요',
                'description': f"연속 {row['consecutive_fail_days']}일 실패",
                'action': 'Config 수정 필요 (거의 확실)'
            }

    elif source_type in ['pc', 'email', 'shared_drive']:
        # NonRPA: 어제 실패했으면 표시
        if row['failed_yesterday']:
            return {
                'section': 'NonRPA 어제 실패',
                'urgency': '⚠️ 확인 필요',
                'description': f"어제 실패",
                'action': 'Config 확인 또는 고객사 파일 문의'
            }

    return None
```

---

## Airflow DAG 상태 연동 (2025-11-10 추가)

### 배경
Converter는 Airflow DAG 내에서 실행되므로, **DAG 상태에 따라 어느 날짜의 데이터를 조회할지 결정**해야 합니다.

### 문제 상황
```
현재 시각: 2025-11-10 08:00 (오전 8시)
어제(11-09) DAG 상태: Running (아직 실행 중)

Q: 어제(11-09) convert_job_history를 조회해야 하나?
A: ❌ 아직 완료 안 됨 → 전일(11-08) 데이터를 조회해야 함
```

### 참고 시스템
#### 1. `airflow_dag_monitor` - 업무일 기준 로직
```python
# 오전 9시 전이면 전날 기준으로
if actual_now.hour < 9:
    reference_date = actual_now - timedelta(days=1)
else:
    reference_date = actual_now

# 휴일/주말 처리
is_holiday = check_bq_holiday(reference_date)
if is_holiday:
    reference_date = get_previous_business_day(reference_date)
```

#### 2. `collect_history_checker` - DAG 상태 확인 로직
```python
# ingestion_id로 수집 배치 추적
latest_ingestion = get_latest_ingestion_id(customer_code, source_id)

# DAG 실행 상태 확인 (Airflow Metadata DB)
dag_state = check_dag_run_state(dag_id, execution_date)

if dag_state in ['running', 'failed', 'upstream_failed']:
    # 아직 완료 안 됨 → 이전 완료된 배치 사용
    target_ingestion = get_previous_completed_ingestion(customer_code, source_id)
```

---

### 구현 전략

#### Phase 1: 간단한 시간 기반 (초기 구현)
```python
def get_target_date():
    """
    모니터링 대상 날짜 결정
    - 오전 9시 전: 그저께 데이터 (어제 DAG가 아직 완료 안 됐을 가능성)
    - 오전 9시 후: 어제 데이터 (어제 DAG가 완료됐을 것으로 가정)
    """
    now = datetime.now(timezone('Asia/Seoul'))

    if now.hour < 9:
        # 오전 9시 전 → 그저께 데이터
        target_date = (now - timedelta(days=2)).date()
    else:
        # 오전 9시 후 → 어제 데이터
        target_date = (now - timedelta(days=1)).date()

    return target_date
```

**장점**:
- 구현 간단
- 대부분의 경우 작동

**단점**:
- 어제 DAG가 늦게 끝나거나 실패하면 부정확
- 정확한 DAG 상태 반영 안 함

---

#### Phase 2: DAG 상태 기반 (정확한 구현) ⭐ 추천
```python
from google.cloud import bigquery
from airflow.models import DagRun
from datetime import datetime, timedelta

def get_target_date_with_dag_check(customer_code: str):
    """
    Airflow DAG 상태를 확인하여 조회 대상 날짜 결정

    로직:
    1. 어제 날짜 계산
    2. 해당 고객사의 어제 DAG Run 상태 확인
    3. Running/Failed이면 전일 데이터 사용
    4. Success이면 어제 데이터 사용
    """
    now = datetime.now(timezone('Asia/Seoul'))
    yesterday = (now - timedelta(days=1)).date()

    # 고객사 DAG ID (예: c0159c00)
    dag_id = customer_code

    # Airflow Metadata에서 DAG Run 상태 확인
    dag_state = check_dag_run_state(dag_id, yesterday)

    if dag_state == 'success':
        # 어제 DAG 성공 → 어제 데이터 사용
        return yesterday
    elif dag_state in ['running', 'queued', 'failed', 'upstream_failed']:
        # 어제 DAG 미완료/실패 → 전일 완료 데이터 찾기
        return get_last_successful_date(dag_id, yesterday)
    else:
        # DAG Run 없음 → 기본값 (그저께)
        return (now - timedelta(days=2)).date()


def check_dag_run_state(dag_id: str, execution_date: date) -> str:
    """
    Airflow Metadata DB에서 DAG Run 상태 조회

    방법 1: Airflow API 사용 (추천)
    방법 2: Metadata DB 직접 조회
    """
    from airflow.api.client.local_client import Client

    try:
        client = Client(None, None)
        dag_runs = client.get_dag_runs(dag_id, execution_date)

        if dag_runs:
            latest_run = dag_runs[-1]
            return latest_run.state  # 'success', 'running', 'failed' 등
        else:
            return None  # DAG Run 없음
    except Exception as e:
        logger.error(f"Failed to check DAG state: {e}")
        return None


def get_last_successful_date(dag_id: str, before_date: date) -> date:
    """
    특정 날짜 이전에 성공한 마지막 DAG Run 날짜 찾기
    """
    from airflow.models import DagRun

    # before_date 이전 7일간 검색
    for i in range(1, 8):
        check_date = before_date - timedelta(days=i)
        state = check_dag_run_state(dag_id, check_date)

        if state == 'success':
            return check_date

    # 7일 안에 성공 없음 → 일단 그저께 반환
    return before_date - timedelta(days=1)
```

**쿼리 예시**:
```sql
-- 고객사별 DAG 상태에 따라 다른 날짜 조회
WITH target_dates AS (
  SELECT
    'c0159c00' as customer_code,
    -- DAG 성공: 어제, 실패/실행중: 전일 성공 날짜
    CASE
      WHEN check_dag_state('c0159c00', CURRENT_DATE() - 1) = 'success'
        THEN CURRENT_DATE() - 1
      ELSE get_last_success_date('c0159c00', CURRENT_DATE() - 1)
    END as target_date
  UNION ALL
  SELECT 'c2026600', ...
  -- 모든 고객사
)

SELECT
  f.*
FROM convert_job_history f
INNER JOIN target_dates t
  ON f.customer_code = t.customer_code
  AND DATE(f.created_at, 'Asia/Seoul') = t.target_date
WHERE f.status = 'fail'
```

---

#### Phase 3: ingestion_id 기반 (collect_history_checker 방식)
```python
def get_target_ingestion_id(customer_code: str, source_id: str):
    """
    가장 최근 완료된 ingestion_id 찾기

    collect_history_checker에서 사용하는 방식:
    1. filter_job_history에서 최신 ingestion_id 조회
    2. 해당 ingestion_id의 DAG 상태 확인
    3. 완료 안 됐으면 이전 ingestion_id 사용
    """
    bq_client = bigquery.Client()

    # 최근 7일간의 ingestion_id 조회 (내림차순)
    query = f"""
    SELECT DISTINCT
      ingestion_id,
      DATE(created_at, 'Asia/Seoul') as date,
      COUNT(*) as record_count
    FROM `{PROJECT}.dashboard.convert_job_history`
    WHERE customer_code = '{customer_code}'
      AND created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
    GROUP BY ingestion_id, date
    ORDER BY ingestion_id DESC
    LIMIT 10
    """

    results = bq_client.query(query).result()

    for row in results:
        ingestion_id = row.ingestion_id
        date = row.date

        # 해당 날짜의 DAG 상태 확인
        dag_state = check_dag_run_state(customer_code, date)

        if dag_state == 'success':
            # 완료된 배치 발견
            return ingestion_id, date

    # 완료된 배치 없음 → 가장 오래된 것 사용
    return None, None
```

**장점**:
- 가장 정확 (실제 완료된 데이터만 사용)
- DAG 재실행, 스케줄 변경 등에도 대응

**단점**:
- 복잡도 높음
- BigQuery 쿼리 추가 발생

---

### 최종 추천 구현

#### 하이브리드 접근 (Phase 1 + Phase 2)
```python
def get_monitoring_target_date(customer_code: str = None):
    """
    Converter 모니터링 대상 날짜 결정

    우선순위:
    1. 고객사별 DAG 상태 확인 (가능하면)
    2. 일반 규칙: 오전 9시 기준
    """
    now = datetime.now(timezone('Asia/Seoul'))
    yesterday = (now - timedelta(days=1)).date()

    # 특정 고객사 조회 시 DAG 상태 확인
    if customer_code:
        dag_state = check_dag_run_state(customer_code, yesterday)

        if dag_state == 'success':
            return yesterday
        elif dag_state in ['running', 'failed']:
            # 실패/실행중 → 전일 성공 데이터
            return get_last_successful_date(customer_code, yesterday)

    # 전체 모니터링 시 간단한 시간 기준
    if now.hour < 9:
        # 오전 9시 전 → 그저께 (안전하게)
        return (now - timedelta(days=2)).date()
    else:
        # 오전 9시 후 → 어제
        return yesterday


# 사용 예시
def generate_converter_report():
    """전체 고객사 리포트"""
    # 기본 대상 날짜 (시간 기반)
    default_target = get_monitoring_target_date()

    # 고객사별로 DAG 상태 확인하여 개별 날짜 결정
    customers = get_all_customers()

    all_failures = []
    for customer in customers:
        # 고객사별 최적 날짜
        target_date = get_monitoring_target_date(customer['customer_code'])

        # 해당 날짜 데이터 조회
        failures = fetch_failures_from_bq(
            customer_code=customer['customer_code'],
            target_date=target_date
        )
        all_failures.extend(failures)

    # 나머지 처리...
```

---

### 주의사항

#### 1. Airflow Metadata 접근
- **GCP Composer**: Airflow API 또는 Postgres Metadata DB 접근 필요
- **권한 설정**: Cloud Function에서 Composer 환경 접근 권한
- **대안**: BigQuery에 DAG 상태 로그 테이블 별도 관리

#### 2. 휴일/주말 처리
```python
def get_monitoring_target_date_with_holiday():
    """
    휴일/주말 고려
    - 월요일 오전: 금요일 데이터 (주말 건너뛰기)
    - 휴일 다음날: 휴일 전 영업일
    """
    now = datetime.now(timezone('Asia/Seoul'))
    target = get_monitoring_target_date()

    # BigQuery 휴일 테이블 확인
    if is_holiday(target):
        return get_previous_business_day(target)

    return target
```

#### 3. 에러 핸들링
```python
try:
    target_date = get_monitoring_target_date(customer_code)
except AirflowException as e:
    logger.warning(f"Failed to check DAG state: {e}")
    # Fallback: 시간 기반
    target_date = get_monitoring_target_date(customer_code=None)
```

---

### 메시지에 표시
```
📊 Converter 실패 리포트 - 2025-11-10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
조회 기준일: 2025-11-09 (어제)
※ 일부 고객사는 DAG 미완료로 2025-11-08 데이터 조회

전체: 1,357건 | ✅ 성공: 1,232건 | ❌ 실패: 125건
...
```

---

## Firestore 연동: env='ops' 고객사만 모니터링 (2025-11-10 추가)

### 배경
- Firestore `sources` collection에 고객사별 설정 저장
- `env` 필드로 환경 구분: `'ops'` (운영), `'dev'` (개발), `'test'` (테스트)
- **Airflow DAG는 `env='ops'`인 고객사만 실행**
- 따라서 모니터링도 운영 환경만 대상으로 해야 함

### 문제
```sql
-- ❌ 잘못된 쿼리: 모든 고객사 조회
SELECT *
FROM `hyperlounge-dev.dashboard.convert_job_history`
WHERE DATE(created_at) = '2025-11-09'
  AND status = 'fail'

-- 문제점: dev/test 환경 데이터까지 포함 → 노이즈
```

### 해결 방안

#### 1. Firestore에서 활성 고객사 조회
```python
from google.cloud import firestore

def get_active_customers():
    """
    Firestore에서 env='ops'인 운영 고객사 목록 조회

    Returns:
        list: 운영 고객사 코드 목록 ['c0159c00', 'c2026600', ...]
    """
    db = firestore.Client()

    active_customers = set()

    # sources collection에서 env='ops'인 문서만
    docs = db.collection('sources').where('env', '==', 'ops').stream()

    for doc in docs:
        data = doc.to_dict()
        customer_code = data.get('customer_code')

        if customer_code:
            active_customers.add(customer_code)

    return sorted(list(active_customers))


# 사용 예시
active_customers = get_active_customers()
print(f"운영 고객사: {len(active_customers)}개")
# 출력: 운영 고객사: 45개
# ['c0159c00', 'c2026600', 'c7005b01', ...]
```

#### 2. BigQuery 쿼리에 적용
```sql
-- ✅ 올바른 쿼리: env='ops'인 고객사만
WITH active_customers AS (
  -- Python에서 Firestore 조회 후 IN 절로 전달
  SELECT customer_code
  FROM UNNEST(@active_customer_codes) as customer_code
),

failures AS (
  SELECT
    h.*
  FROM `hyperlounge-dev.dashboard.convert_job_history` h
  INNER JOIN active_customers a
    ON h.customer_code = a.customer_code
  WHERE DATE(h.created_at, 'Asia/Seoul') = '2025-11-09'
    AND h.status = 'fail'
)

SELECT * FROM failures
ORDER BY customer_code, created_at
```

#### 3. Python에서 파라미터 바인딩
```python
from google.cloud import bigquery

def fetch_failures_from_bq(target_date: str):
    """
    env='ops' 고객사의 실패 건만 조회
    """
    # 1. Firestore에서 활성 고객사 조회
    active_customers = get_active_customers()

    if not active_customers:
        logger.warning("활성 고객사 없음 (env='ops')")
        return []

    # 2. BigQuery 쿼리 실행
    client = bigquery.Client()

    query = """
    SELECT
      customer_code,
      customer_name,
      source_type,
      source_id,
      filter_condition_id,
      target_table_name,
      gcs_src,
      ingestion_id,
      error_message,
      created_at
    FROM `hyperlounge-dev.dashboard.convert_job_history`
    WHERE customer_code IN UNNEST(@active_customers)
      AND DATE(created_at, 'Asia/Seoul') = @target_date
      AND status = 'fail'
    ORDER BY customer_code, created_at
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter(
                "active_customers",
                "STRING",
                active_customers
            ),
            bigquery.ScalarQueryParameter(
                "target_date",
                "DATE",
                target_date
            ),
        ]
    )

    results = client.query(query, job_config=job_config).result()

    failures = []
    for row in results:
        failures.append(dict(row))

    logger.info(f"활성 고객사 {len(active_customers)}개 중 실패: {len(failures)}건")
    return failures
```

### 캐싱 최적화

매번 Firestore 조회는 비효율적이므로 캐싱 적용:

```python
import time
from functools import lru_cache

# 방법 1: 메모리 캐시 (간단)
@lru_cache(maxsize=1)
def get_active_customers_cached():
    """
    Firestore 조회 결과를 메모리에 캐시
    Cloud Function 인스턴스 재사용 시 효과적
    """
    return get_active_customers()


# 방법 2: TTL 캐시 (시간 제한)
_cache = {
    'active_customers': None,
    'last_updated': 0,
    'ttl': 3600  # 1시간
}

def get_active_customers_with_ttl():
    """
    1시간마다 Firestore 재조회
    """
    now = time.time()

    if (_cache['active_customers'] is None or
        now - _cache['last_updated'] > _cache['ttl']):

        logger.info("Firestore에서 활성 고객사 재조회")
        _cache['active_customers'] = get_active_customers()
        _cache['last_updated'] = now

    return _cache['active_customers']


# 방법 3: 환경 변수 (정적)
# deploy 시점에 고정
# → 고객사 추가/제거 시 재배포 필요
# → 비추천
```

### 대안: BigQuery에 고객사 메타 테이블

Firestore 대신 BigQuery에 고객사 메타 테이블 관리:

```sql
-- dashboard.customer_metadata 테이블 생성
CREATE TABLE `hyperlounge-dev.dashboard.customer_metadata` (
  customer_code STRING NOT NULL,
  customer_name STRING,
  env STRING NOT NULL,  -- 'ops', 'dev', 'test'
  is_active BOOL DEFAULT TRUE,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- 쿼리 간소화
WITH failures AS (
  SELECT h.*
  FROM `hyperlounge-dev.dashboard.convert_job_history` h
  INNER JOIN `hyperlounge-dev.dashboard.customer_metadata` m
    ON h.customer_code = m.customer_code
  WHERE m.env = 'ops'
    AND m.is_active = TRUE
    AND DATE(h.created_at, 'Asia/Seoul') = '2025-11-09'
    AND h.status = 'fail'
)
SELECT * FROM failures;
```

**장점**:
- Firestore 의존성 제거
- 쿼리 간소화
- BigQuery 네이티브 조인으로 성능 향상

**단점**:
- 메타 테이블 동기화 필요 (Firestore → BigQuery)
- 추가 테이블 관리

### 기존 구현 참고

#### 1. `history_checker/clients/firestore_client.py` ⭐ 추천
```python
# 실제 구현된 로직 - env != 'dev'인 것만 필터링
class FirestoreClient:
    def __init__(self):
        self.db = firestore.Client()
        self.company_collection = self.db.collection("company").document("version").collection("v1.0")

    def get_crawl_actions_tree(self):
        """env != 'dev'인 소스만 조회"""
        crawl_actions_tree = {}

        customer_docs = self.company_collection.list_documents()

        for customer_doc in customer_docs:
            customer_code = customer_doc.id

            # source_metas에서 env 확인
            source_metas_ref = customer_doc.collection("source_metas")
            source_metas = {doc.id: doc.to_dict() for doc in source_metas_ref.stream()}

            for source_id, source_meta_data in source_metas.items():
                env = source_meta_data.get("env", "dev")
                source_type = source_meta_data.get("source_type", "unknown")

                # dev 환경 제외 (= ops, test 등 포함)
                if env == "dev" or source_type not in ["rpa", "board"]:
                    continue

                # 여기서 실제 데이터 처리...
```

**특징**:
- `company/version/v1.0/{customer_code}/source_metas` 구조
- `env == "dev"`를 **제외** (= ops, test 포함)
- source_type도 같이 필터링

#### 2. `customer_env_checker/clients/firestore_client.py`
```python
# 고객사별 env 분류 (ops > dev > other 우선순위)
def classify_customers_by_env(self):
    """
    고객사의 모든 source를 확인하여 env 분류
    - 하나라도 'ops'면 → ops 고객사
    - ops 없고 'dev' 있으면 → dev 고객사
    - 둘 다 없으면 → other
    """
    classified_customers = {
        "ops": [],
        "dev": [],
        "other": []
    }

    customer_docs = self.company_collection.stream()

    for customer_doc in customer_docs:
        customer_code = customer_doc.id
        final_env_status = "other"

        source_metas_ref = customer_doc.reference.collection("source_metas")
        for source_meta_doc in source_metas_ref.stream():
            source_env = source_meta_doc.to_dict().get("env", "").lower()

            if source_env == "ops":
                final_env_status = "ops"
                break  # ops 발견 시 즉시 종료
            elif source_env == "dev":
                if final_env_status != "ops":
                    final_env_status = "dev"

        classified_customers[final_env_status].append({
            "code": customer_code,
            "name": customer_data.get("name", "이름 없음")
        })

    return classified_customers
```

#### 3. `airflow_dag_monitor/clients/airflow_client.py`
```python
# Airflow API로 DAG 목록 가져오기 (Firestore 사용 안 함)
def get_all_customer_dags(self):
    """
    Airflow API에서 활성 고객사 DAG 조회
    - is_paused = False (활성 상태)
    - "Develop" 태그 없음 (운영 환경)
    """
    dags_data = self.make_request(endpoint="dags?limit=1000")

    customer_dags = []
    for dag in dags_data["dags"]:
        # 중지된 DAG 제외
        if dag.get('is_paused', True):
            continue

        # "Develop" 태그 있는 DAG 제외
        tags = dag.get("tags", [])
        is_develop_dag = any("Develop" in t.get("name", "") for t in tags)
        if is_develop_dag:
            continue

        # 고객사 이름 태그 추출
        tag_info = self.extract_from_tags(tags)
        if tag_info.get("customer_name"):
            dag['customer_name'] = tag_info['customer_name']
            customer_dags.append(dag)

    return customer_dags
```

**특징**:
- Firestore 의존성 없음
- Airflow Metadata에서 직접 조회
- DAG 태그로 환경 구분 ("Develop" 태그 유무)

---

### Converter 모니터링 적용 방안

#### 옵션 A: history_checker 방식 (Firestore) ⭐ 추천
```python
def get_active_customers_for_converter():
    """
    history_checker 로직 재사용
    env != 'dev'인 고객사만 (= ops, test 포함)
    """
    db = firestore.Client()
    company_collection = db.collection("company").document("version").collection("v1.0")

    active_customers = set()
    customer_docs = company_collection.list_documents()

    for customer_doc in customer_docs:
        customer_code = customer_doc.id

        # source_metas에서 하나라도 env != 'dev'이면 포함
        source_metas_ref = customer_doc.collection("source_metas")
        for source_meta_doc in source_metas_ref.stream():
            env = source_meta_doc.to_dict().get("env", "dev")

            if env != "dev":  # ops, test 등 포함
                active_customers.add(customer_code)
                break  # 하나만 발견해도 충분

    return sorted(list(active_customers))
```

**장점**:
- history_checker와 동일한 로직 (일관성)
- ops뿐 아니라 test 환경도 모니터링 가능

**단점**:
- test 환경까지 포함 (노이즈 가능성)

#### 옵션 B: ops만 엄격하게 필터링
```python
def get_ops_only_customers():
    """
    customer_env_checker 로직 활용
    하나라도 env='ops'인 고객사만 포함
    """
    db = firestore.Client()
    company_collection = db.collection("company").document("version").collection("v1.0")

    ops_customers = set()
    customer_docs = company_collection.list_documents()

    for customer_doc in customer_docs:
        customer_code = customer_doc.id

        source_metas_ref = customer_doc.collection("source_metas")
        for source_meta_doc in source_metas_ref.stream():
            env = source_meta_doc.to_dict().get("env", "").lower()

            if env == "ops":
                ops_customers.add(customer_code)
                break

    return sorted(list(ops_customers))
```

**장점**:
- 운영 환경만 정확하게 필터링
- 노이즈 최소화

**단점**:
- test 환경 누락 (필요시 수동 확인 필요)

#### 옵션 C: Airflow DAG 기반 (API)
```python
def get_customers_from_airflow():
    """
    airflow_dag_monitor 방식
    활성 DAG (is_paused=False, Develop 태그 없음)
    """
    from airflow_dag_monitor.clients.airflow_client import AirflowClient

    airflow_client = AirflowClient(AIRFLOW_API_URL)
    customer_dags = airflow_client.get_all_customer_dags()

    # dag_id에서 customer_code 추출 (예: c0159c00-...)
    active_customers = set()
    for dag in customer_dags:
        dag_id = dag['dag_id']
        customer_code = dag_id.split('-')[0]  # c0159c00
        active_customers.add(customer_code)

    return sorted(list(active_customers))
```

**장점**:
- Firestore 의존성 없음
- 실제 실행 중인 DAG 기준 (가장 정확)

**단점**:
- Airflow API 호출 필요 (네트워크 의존)
- Airflow 구조 변경 시 영향

---

### 최종 추천

**Phase 1 (초기)**: 옵션 A (history_checker 방식)
- `env != 'dev'` 필터링 (ops, test 포함)
- 기존 로직 재사용으로 빠른 구현
- TTL 캐싱 적용 (1시간)

**Phase 2 (안정화)**: 옵션 B (ops만)
- `env == 'ops'` 엄격 필터링
- 운영 데이터만 모니터링
- 필요시 고객사별 설정으로 test 환경 포함 옵션

**Phase 3 (최적화)**: BigQuery 메타 테이블
- Firestore → BigQuery 동기화
- 쿼리 단순화 및 성능 향상

---

## BigQuery 테이블 스키마 확인 (2025-11-10 추가)

### 실제 테이블 스키마
`hyperlounge-dev.dashboard.convert_job_history` 테이블 (파티션 테이블)

**전체 스키마:**

| 필드명 | 타입 | 모드 | 설명 |
|--------|------|------|------|
| hostname | STRING | REQUIRED | Airflow DAG가 수행된 hostname |
| run_id | STRING | REQUIRED | Airflow DAG Run Id |
| task_id | STRING | REQUIRED | Airflow Task Id |
| customer_code | STRING | REQUIRED | 고객사 코드 |
| customer_name | STRING | REQUIRED | 고객사 이름 |
| source_type | STRING | REQUIRED | 소스 타입 (rpa/board/pc/email/shared_drive) |
| source_id | STRING | REQUIRED | 소스 ID |
| filter_condition_id | STRING | REQUIRED | Filter condition document ID |
| convert_config_id | STRING | REQUIRED | Convert config ID |
| **status** | STRING | REQUIRED | ⚠️ **실패 여부: "success" or "fail"** |
| error_message | STRING | NULLABLE | 에러 메시지 |
| ingestion_id | TIMESTAMP | REQUIRED | Timestamp 형식의 ingestion ID |
| **gcs_path** | STRING | NULLABLE | ⚠️ **GCS 파일 경로** |
| created_at | TIMESTAMP | REQUIRED | 로그 작성 시간 |
| convert_item_names | RECORD (REPEATED) | REPEATED | convert result item info list |
| **env** | STRING | NULLABLE | ⚠️ **환경 구분 (ops/dev/test), 운영팀 확인용** |
| job_names | RECORD (REPEATED) | REPEATED | convert run job info list |

**중요한 차이점 (문서 v2 스키마와 실제 차이):**
- ❌ `result` → ✅ `status`
- ❌ `gcs_src` → ✅ `gcs_path`
- ❌ `target_table_name` → 실제 테이블에는 없음 (convert_item_names RECORD에 포함)
- ✅ `env` 필드 있음 → **모니터링에서 env != 'dev' 필터링 가능!**

### 개발용 쿼리 예시

#### 1. 특정 날짜 전체 실패 건 확인
```sql
-- 2025-11-07 전체 실패 건수 확인 (파일별 그룹핑)
SELECT
  customer_code,
  customer_name,
  source_type,
  COUNT(*) as fail_count,
  COUNT(DISTINCT gcs_path) as fail_file_count  -- 파일 개수
FROM
  `hyperlounge-dev.dashboard.convert_job_history`
WHERE
  DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
GROUP BY customer_code, customer_name, source_type
ORDER BY fail_count DESC
```

#### 2. 고객사별 에러 메시지 샘플 확인
```sql
-- 특정 고객사의 에러 메시지 확인
SELECT
  customer_code,
  source_type,
  convert_config_id,
  error_message,
  gcs_path,
  created_at
FROM
  `hyperlounge-dev.dashboard.convert_job_history`
WHERE
  customer_code = 'c0159c00'
  AND DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
ORDER BY created_at DESC
LIMIT 20
```

#### 3. 에러 유형별 분류 테스트
```sql
-- 에러 메시지 패턴 확인 (분류 로직 테스트용)
SELECT
  CASE
    WHEN REGEXP_CONTAINS(error_message, r"(?i)Header .* not found") THEN '헤더 에러'
    WHEN REGEXP_CONTAINS(error_message, r"(?i)Sheet .* not found") THEN '시트 에러'
    WHEN REGEXP_CONTAINS(error_message, r"(?i)timeout") THEN 'Timeout'
    WHEN REGEXP_CONTAINS(error_message, r"(?i)usecols.*out of bounds") THEN '컬럼 범위'
    ELSE '기타'
  END as error_type,
  COUNT(*) as count,
  ARRAY_AGG(DISTINCT error_message LIMIT 3) as sample_messages
FROM
  `hyperlounge-dev.dashboard.convert_job_history`
WHERE
  DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
GROUP BY error_type
ORDER BY count DESC
```

#### 4. source_type별 분포 확인 (RPA/Board vs NonRPA)
```sql
SELECT
  CASE
    WHEN source_type IN ('rpa', 'board') THEN 'RPA/Board'
    WHEN source_type IN ('pc', 'email', 'shared_drive') THEN 'NonRPA'
    ELSE 'Unknown'
  END as source_category,
  source_type,
  COUNT(*) as fail_count,
  COUNT(DISTINCT customer_code) as customer_count
FROM
  `hyperlounge-dev.dashboard.convert_job_history`
WHERE
  DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
GROUP BY source_category, source_type
ORDER BY fail_count DESC
```

#### 5. 파일별 그룹핑 (실제 모니터링 로직) ⭐ 핵심
```sql
-- 파일별로 그룹핑해서 실제 대응 건수 확인
-- 이게 실제 모니터링에서 사용할 핵심 로직!
SELECT
  customer_code,
  customer_name,
  source_type,
  gcs_path,
  COUNT(*) as table_fail_count,  -- 이 파일로 인한 테이블 실패 건수
  ARRAY_AGG(DISTINCT convert_config_id LIMIT 5) as failed_configs,
  ANY_VALUE(error_message) as sample_error
FROM
  `hyperlounge-dev.dashboard.convert_job_history`
WHERE
  DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
GROUP BY customer_code, customer_name, source_type, gcs_path
ORDER BY table_fail_count DESC
LIMIT 20
```

#### 6. env 필터링 포함 (운영 환경만)
```sql
-- env='ops' 또는 env != 'dev'인 고객사만 조회
SELECT
  customer_code,
  customer_name,
  env,
  COUNT(*) as fail_count
FROM
  `hyperlounge-dev.dashboard.convert_job_history`
WHERE
  DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
  AND env != 'dev'  -- 운영/테스트 환경만 (dev 제외)
GROUP BY customer_code, customer_name, env
ORDER BY fail_count DESC
```

### Python에서 BigQuery 호출 (토큰 생성)

```python
from google.cloud import bigquery
import google.auth

# 인증 (기본 자격증명 사용)
credentials, project = google.auth.default(
    scopes=['https://www.googleapis.com/auth/cloud-platform']
)

# BigQuery 클라이언트 생성
client = bigquery.Client(
    credentials=credentials,
    project='hyperlounge-dev'
)

# 쿼리 실행
query = """
SELECT
  customer_code,
  customer_name,
  source_type,
  COUNT(*) as fail_count
FROM
  `hyperlounge-dev.dashboard.convert_job_history`
WHERE
  DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
  AND env != 'dev'
GROUP BY customer_code, customer_name, source_type
ORDER BY fail_count DESC
"""

query_job = client.query(query)
results = query_job.result()

for row in results:
    print(f"{row.customer_code} ({row.customer_name}): {row.fail_count}건")
```

### 개발 진행 순서

1. **데이터 탐색** (BigQuery 콘솔)
   - 쿼리 5번으로 실제 파일별 실패 패턴 확인
   - 에러 메시지 샘플 확인 (쿼리 3번)
   - source_type 분포 확인 (쿼리 4번)

2. **필터링 로직 개발**
   - Firestore에서 env != 'dev' 고객사 조회 (옵션 A)
   - BigQuery 쿼리에 고객사 목록 파라미터 바인딩
   - Noise 판정 로직 (같은 날 성공률 확인)

3. **에러 분류 로직**
   - 에러 메시지 패턴 매칭 (정규식)
   - LLM fallback 구현

4. **메시지 포맷팅**
   - RPA/Board vs NonRPA 구분
   - 테이블 형식 생성
   - Teams 메시지 전송

---

## LLM 에러 분류 전략

### 목적
- `error_message`를 읽고 **에러 유형 자동 분류**
- **중요**: 모든 에러가 분류되어야 함 (누락 X)

### 접근: 규칙 기반 + LLM Fallback ⭐

#### Phase 1: 규칙 기반 (정규식) - 빠르고 확실

```python
ERROR_PATTERNS = {
    "헤더 에러": [
        r"Header .* not found",
        r"Cannot find header",
        r"Missing column",
        r"header_coordinate",
    ],
    "시트 에러": [
        r"Sheet .* not found",
        r"Worksheet .* does not exist",
        r"No sheet named",
    ],
    "컬럼 범위 에러": [
        r"usecols.*out of bounds",
        r"invalid column range",
    ],
    "Timeout": [
        r"[Tt]imeout",
        r"exceed.*time limit",
    ],
    "메모리 부족": [
        r"[Oo]ut of [Mm]emory",
        r"MemoryError",
    ],
    "파일 손상": [
        r"corrupt",
        r"damaged",
        r"cannot.*read.*file",
        r"empty.*sheet",
    ],
}

def classify_error_rule_based(error_message):
    """정규식으로 빠르게 분류 (무료, 빠름, 정확)"""
    for error_type, patterns in ERROR_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, error_message, re.IGNORECASE):
                return {
                    'type': error_type,
                    'confidence': 'high',
                    'method': 'rule'
                }
    return None  # 매칭 안 됨
```

#### Phase 2: LLM Fallback - 규칙 매칭 안 되는 것만

```python
def classify_error_llm(error_message):
    """규칙 매칭 실패 시에만 LLM 사용 (비용 절감)"""

    prompt = f"""
다음 엑셀 변환(converter) 에러 메시지를 분석하고 가장 적합한 에러 유형을 선택하세요.

에러 메시지:
{error_message}

에러 유형 목록:
1. 헤더 에러 - 엑셀 헤더명을 찾지 못함
2. 시트 에러 - 엑셀 시트명을 찾지 못함
3. 컬럼 범위 에러 - 컬럼 범위가 잘못됨
4. Timeout - 실행 시간 초과
5. 메모리 부족 - 메모리 부족
6. 파일 손상 - 파일이 손상됨
7. 기타 - 위 카테고리에 해당하지 않음

응답 형식 (JSON만):
{{
  "type": "에러 유형",
  "reason": "분류 근거 (한 줄)"
}}
"""

    response = llm_api_call(prompt)
    return {
        'type': response['type'],
        'confidence': 'medium',
        'method': 'llm',
        'reason': response['reason']
    }
```

#### Phase 3: 하이브리드 (최종)

```python
def classify_error(error_message):
    """
    1차: 규칙 기반 (빠름, 정확, 무료)
    2차: LLM (느림, 유연, 비용 발생)
    """
    # 1. 규칙 기반 시도
    rule_result = classify_error_rule_based(error_message)
    if rule_result:
        return rule_result

    # 2. LLM으로 fallback
    llm_result = classify_error_llm(error_message)

    # 3. 로깅 (나중에 규칙 추가용)
    log_unclassified_error(error_message, llm_result)

    return llm_result
```

**예상 비율**:
- 규칙 기반: 90-95% (대부분)
- LLM: 5-10% (새로운 에러 패턴)

---

### LLM 사용 최적화

#### 1. 배치 처리 (비용 절감)
```python
# 한 번에 여러 에러 분류
unclassified_errors = [...]  # 규칙 매칭 안 된 것들만

prompt = f"""
다음 {len(unclassified_errors)}개의 에러 메시지를 분류하세요.

에러 메시지들:
1. {errors[0]}
2. {errors[1]}
...

응답 형식 (JSON 배열):
[
  {{"index": 1, "type": "헤더 에러", "reason": "..."}},
  {{"index": 2, "type": "시트 에러", "reason": "..."}}
]
"""
```
**효과**: API 호출 10회 → 1회 (비용 1/10)

#### 2. 캐싱 (중복 방지)
```python
# 같은 에러 메시지는 재분류 안 함
error_cache = {}  # 또는 Redis

def classify_error_cached(error_message):
    cache_key = hashlib.md5(error_message.encode()).hexdigest()

    if cache_key in error_cache:
        return error_cache[cache_key]

    result = classify_error(error_message)
    error_cache[cache_key] = result
    return result
```

#### 3. 학습 루프 (규칙 확장)
```python
# LLM이 분류한 것을 주기적으로 검토하고 규칙에 추가
# 주 1회 정도

def review_llm_classifications():
    """
    LLM이 분류한 에러들을 보고
    패턴이 보이면 규칙에 추가
    """
    llm_classified = get_llm_classified_last_week()

    # 같은 분류가 많이 나온 것들
    for error_type, messages in llm_classified.groupby('type'):
        if len(messages) >= 5:
            print(f"\n{error_type}: {len(messages)}건")
            for msg in messages[:3]:
                print(f"  - {msg}")

            # 패턴 보이면 규칙 추가
            new_pattern = input("규칙 추가할 패턴 (정규식): ")
            if new_pattern:
                add_to_error_patterns(error_type, new_pattern)
```

**효과**:
- 초기: LLM 20% 사용
- 1달 후: LLM 5% 사용 (규칙 확장됨)
- 3달 후: LLM 1-2% 사용 (거의 모든 패턴 규칙화)

---

### 누락 방지 전략

#### 1. 기본값 설정 (Fail-safe)
```python
def classify_error(error_message):
    try:
        # 규칙 또는 LLM 시도
        result = ...
        return result
    except Exception as e:
        # 에러 나도 일단 "기타"로 분류 (누락 방지)
        logger.error(f"Classification failed: {e}")
        return {
            'type': '기타',
            'confidence': 'low',
            'method': 'fallback',
            'error': str(e),
            'original_message': error_message
        }
```

#### 2. 검증 로직
```python
# 모든 실패 건이 분류되었는지 확인
all_failures = get_failures_yesterday()
classified = [classify_error(f.error_message) for f in all_failures]

assert len(all_failures) == len(classified), "누락 발생!"
assert all(c is not None for c in classified), "None 분류 있음!"
```

#### 3. 미분류 알림
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ 분류 실패 (개발팀 확인 필요)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• 2건의 에러를 "기타"로 분류했습니다
🔗 [BigQuery에서 확인하여 규칙 추가]
```

---

## 최종 메시지 포맷 (Airflow 스타일 테이블)

### 케이스 1: 정상 (실패 없음)

```
📊 Converter 실패 리포트 - 2025-11-09
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
전체: 1,357건 | ✅ 성공: 1,357건 (100%) | ❌ 실패: 0건

🎉 실패 건이 없습니다!

🔗 상세 보기: [BigQuery] | [Grafana]
```

---

### 케이스 2: 실패 있음 (RPA/Board만)

```
📊 Converter 실패 리포트 - 2025-11-09
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
전체: 1,507건 | ✅ 성공: 1,232건 (82%) | ❌ 실패: 275건 (18%)

실패 분류:
├─ 분석 대상: 125건 (2개 고객사) → 아래 테이블
├─ 정책상 제외: 145건 (xlsb 140건, 암호화 5건)
└─ Noise: 5건 (특정 파일 문제)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 [RPA/Board] 일별 수집 연속 실패 - 2개 고객사
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
고객사        수집    헤더에러    시트에러    컬럼범위    Timeout    파일손상    기타    분류실패
              방식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GC녹십자      RPA     75건        -           -           -          -           -       -
[c0159c00]            5일연속

매일홀딩스    Board   -           45건        -           -          -           -       -
[c2026600]                        3일연속
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
소계                  75건        45건        0건         0건        0건         0건     0건
                     (60%)       (40%)       (0%)        (0%)       (0%)        (0%)    (0%)

⚠️ [NonRPA] 고객사 업로드 실패 없음

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 제외된 실패 (참고용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
정책상 제외: 145건 (조치 불필요)
• xlsb 파일: 140건 - 한투(80), 보령(35), 한화(25)
• 암호화 파일: 5건 - 제주맥주(3), 스파젠(2)

Noise: 5건 (같은 날 다른 파일 정상 처리)
• 고피자 pc: 2건 / 8건 성공
• 한투 email: 3건 / 12건 성공

분류 방법: 규칙 115건 (92%) | LLM 10건 (8%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔗 상세 정보
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 분석 대상 상세: [BigQuery - 분석 필요 실패]
📋 제외 항목 상세: [BigQuery - 정책/Noise]
📈 트렌드 대시보드: [Grafana]
```

---

### 케이스 3: 실패 있음 (RPA/Board + PC/Email/Drive 모두)

```
📊 Converter 실패 리포트 - 2025-11-09
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
전체: 1,507건 | ✅ 성공: 1,232건 (82%) | ❌ 실패: 275건 (18%)

실패 분류:
├─ 분석 대상: 157건 (5개 고객사) → 아래 테이블
├─ 정책상 제외: 113건 (xlsb 105건, 암호화 8건)
└─ Noise: 5건 (특정 파일 문제)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 [RPA/Board] 일별 수집 연속 실패 - 2개 고객사
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
고객사        수집    헤더에러    시트에러    컬럼범위    Timeout    파일손상    기타    분류실패
              방식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GC녹십자      RPA     75건        -           -           -          -           -       -
[c0159c00]            5일연속

매일홀딩스    Board   -           45건        -           -          -           -       -
[c2026600]                        3일연속
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
소계                  75건        45건        0건         0건        0건         0건     0건
                     (60%)       (40%)       (0%)        (0%)       (0%)        (0%)    (0%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ [NonRPA] 고객사 업로드 어제 실패 - 3개 고객사
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
고객사        수집         헤더에러    시트에러    컬럼범위    Timeout    파일손상    기타    분류실패
              방식
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
고피자        pc           12건        -           -           -          -           -       -
[c7005b01]                어제

제주맥주      email        -           -           8건         -          -           -       -
[c4cd3b00]                                        어제

스파젠뷰티    shared_drive -           -           -           -          -           12건    -
[caaa3b00]                                                                           어제
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
소계                  12건        0건         8건         0건        0건         12건    0건
                     (38%)       (0%)        (25%)       (0%)       (0%)        (38%)   (0%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 전체 합계
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
에러 유형: 헤더 87건 (55%) | 시트 45건 (29%) | 컬럼범위 8건 (5%) | 기타 12건 (8%)
분류 방법: 규칙 145건 (92%) | LLM 12건 (8%) | 실패 0건 (0%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 제외된 실패 (참고용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
정책상 제외: 113건 (조치 불필요)
• xlsb 파일: 105건 - 한투(70), 보령(25), 한화(10)
• 암호화 파일: 8건 - 제주맥주(5), 스파젠(3)

Noise: 5건 (같은 날 다른 파일 정상 처리)
• 한투 pc: 3건 / 15건 성공
• 보령 email: 2건 / 8건 성공

분류 방법: 규칙 145건 (92%) | LLM 12건 (8%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔗 상세 정보
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 분석 대상 상세: [BigQuery - 분석 필요 실패]
📋 제외 항목 상세: [BigQuery - 정책/Noise]
📈 트렌드 대시보드: [Grafana]
```

---

## 아키텍처 설계 (고객사별 커스터마이징 지원)

### 전체 구조

```
converter_failure_monitor/
├─ config/
│  ├─ common_config.json           # 공통 설정
│  ├─ customers/
│  │  ├─ c0159c00.json             # GC녹십자 커스텀 설정
│  │  ├─ c2026600.json             # 매일홀딩스 커스텀 설정
│  │  └─ ...
│  └─ exclude_rules/
│     ├─ common_exclude.json       # 공통 제외 규칙
│     └─ customer_exclude/
│        ├─ c0159c00.json          # 고객사별 제외 규칙
│        └─ ...
├─ main.py
├─ classifier.py                   # 에러 분류기
├─ filter.py                       # 필터링 로직
├─ formatter.py                    # 메시지 포맷터
└─ requirements.txt
```

---

### 1. 공통 설정 (`config/common_config.json`)

```json
{
  "error_types": [
    "헤더 에러",
    "시트 에러",
    "컬럼 범위 에러",
    "Timeout",
    "파일 손상",
    "기타"
  ],

  "source_type_mapping": {
    "rpa": "RPA",
    "board": "Board",
    "pc": "pc",
    "email": "email",
    "shared_drive": "shared_drive"
  },

  "consecutive_fail_threshold": {
    "rpa": 3,
    "board": 3
  },

  "table_max_rows": {
    "rpa_board": 10,
    "pc_email_drive": 10
  },

  "llm_settings": {
    "model": "gpt-4o-mini",
    "temperature": 0,
    "max_tokens": 500,
    "batch_size": 20
  }
}
```

---

### 2. 공통 제외 규칙 (`config/exclude_rules/common_exclude.json`)

```json
{
  "policy_exclusions": [
    {
      "id": "xlsb_not_supported",
      "pattern": "xlsb.*not supported|xlsb file format",
      "reason": "xlsb 파일 형식 미지원 (정책)",
      "category": "파일 형식",
      "enabled": true
    },
    {
      "id": "encrypted_file",
      "pattern": "Password.*required|encrypted|Workbook is encrypted",
      "reason": "암호화된 파일 (정책상 처리 불가)",
      "category": "암호화",
      "enabled": true
    },
    {
      "id": "file_size_limit",
      "pattern": "File size exceeds.*100MB",
      "reason": "파일 크기 제한 초과 (정책)",
      "category": "파일 크기",
      "enabled": true
    },
    {
      "id": "empty_file",
      "pattern": "empty file|no data|0 bytes",
      "reason": "빈 파일 (데이터 없음)",
      "category": "빈 파일",
      "enabled": true
    }
  ],

  "noise_rules": {
    "same_day_success_threshold": 0.8,
    "description": "같은 날 같은 config로 80% 이상 성공 시 Noise"
  }
}
```

---

### 3. 고객사별 커스텀 설정 (`config/customers/c0159c00.json`)

```json
{
  "customer_code": "c0159c00",
  "customer_name": "GC녹십자",

  "custom_error_types": {
    "enabled": false,
    "additional_types": []
  },

  "custom_exclude_rules": {
    "enabled": true,
    "rules": [
      {
        "id": "gc_specific_format",
        "pattern": "시험성적서.*not found",
        "reason": "GC녹십자 - 시험성적서는 별도 처리 (정책)",
        "category": "고객사 특수 케이스",
        "enabled": true
      }
    ]
  },

  "llm_prompt_override": {
    "enabled": true,
    "additional_context": "GC녹십자는 제약회사로, '시험성적서', 'GST', 'MSDS' 같은 제약 전문 용어가 자주 나옵니다."
  },

  "consecutive_fail_threshold_override": {
    "enabled": false,
    "value": 5
  },

  "notification_settings": {
    "enabled": false,
    "custom_webhook": null,
    "mentions": ["@data-team"]
  }
}
```

---

### 4. 고객사별 제외 규칙 (`config/exclude_rules/customer_exclude/c0159c00.json`)

```json
{
  "customer_code": "c0159c00",
  "additional_exclusions": [
    {
      "id": "gc_test_report",
      "pattern": "시험성적서.*Sheet.*not found",
      "reason": "시험성적서는 별도 처리 프로세스 있음",
      "category": "GC 특수 케이스",
      "enabled": true
    },
    {
      "id": "gc_legacy_format",
      "pattern": "xls file.*97-2003",
      "reason": "GC녹십자는 구 버전 엑셀 허용 (정책)",
      "category": "고객사 정책",
      "enabled": true
    }
  ]
}
```

---

### 5. 설정 로더 (`classifier.py`)

```python
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

class ConfigLoader:
    def __init__(self, config_dir: str = "./config"):
        self.config_dir = Path(config_dir)
        self.common_config = self._load_common_config()
        self.common_exclude = self._load_common_exclude()
        self.customer_configs = {}
        self.customer_excludes = {}

    def _load_common_config(self) -> dict:
        with open(self.config_dir / "common_config.json") as f:
            return json.load(f)

    def _load_common_exclude(self) -> dict:
        with open(self.config_dir / "exclude_rules" / "common_exclude.json") as f:
            return json.load(f)

    def get_customer_config(self, customer_code: str) -> dict:
        """고객사별 설정 로드 (없으면 공통 설정)"""
        if customer_code in self.customer_configs:
            return self.customer_configs[customer_code]

        customer_file = self.config_dir / "customers" / f"{customer_code}.json"
        if customer_file.exists():
            with open(customer_file) as f:
                config = json.load(f)
                self.customer_configs[customer_code] = config
                return config

        return {}  # 커스텀 설정 없음

    def get_exclude_rules(self, customer_code: str) -> dict:
        """고객사별 제외 규칙 (공통 + 고객사별 병합)"""
        # 공통 규칙
        rules = self.common_exclude.copy()

        # 고객사별 규칙 추가
        customer_exclude_file = self.config_dir / "exclude_rules" / "customer_exclude" / f"{customer_code}.json"
        if customer_exclude_file.exists():
            with open(customer_exclude_file) as f:
                customer_rules = json.load(f)
                # 공통 + 고객사별 병합
                if "additional_exclusions" in customer_rules:
                    rules["policy_exclusions"].extend(customer_rules["additional_exclusions"])

        # 고객사 커스텀 설정에서도 추가
        customer_config = self.get_customer_config(customer_code)
        if customer_config.get("custom_exclude_rules", {}).get("enabled"):
            rules["policy_exclusions"].extend(
                customer_config["custom_exclude_rules"]["rules"]
            )

        return rules


class ErrorClassifier:
    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self.common_config = config_loader.common_config

    def classify(self, error_message: str, customer_code: str) -> dict:
        """
        에러 분류 (규칙 + LLM)
        고객사별 커스터마이징 지원
        """
        # 1. 규칙 기반 시도
        rule_result = self._classify_by_rule(error_message)
        if rule_result:
            return rule_result

        # 2. LLM 시도 (고객사별 프롬프트)
        llm_result = self._classify_by_llm(error_message, customer_code)
        return llm_result

    def _classify_by_rule(self, error_message: str) -> Optional[dict]:
        """규칙 기반 분류"""
        error_patterns = {
            "헤더 에러": [
                r"Header .* not found",
                r"Cannot find header",
                r"Missing column",
            ],
            "시트 에러": [
                r"Sheet .* not found",
                r"Worksheet .* does not exist",
            ],
            # ... 생략
        }

        for error_type, patterns in error_patterns.items():
            for pattern in patterns:
                if re.search(pattern, error_message, re.IGNORECASE):
                    return {
                        "type": error_type,
                        "method": "rule",
                        "confidence": "high"
                    }
        return None

    def _classify_by_llm(self, error_message: str, customer_code: str) -> dict:
        """LLM 기반 분류 (고객사별 프롬프트)"""
        # 기본 프롬프트
        base_prompt = f"""
다음 엑셀 변환 에러를 분석하고 분류하세요.

에러 메시지: {error_message}

에러 유형: {', '.join(self.common_config['error_types'])}
"""

        # 고객사별 추가 컨텍스트
        customer_config = self.config_loader.get_customer_config(customer_code)
        if customer_config.get("llm_prompt_override", {}).get("enabled"):
            additional_context = customer_config["llm_prompt_override"]["additional_context"]
            base_prompt += f"\n\n[고객사 컨텍스트]\n{additional_context}\n"

        # LLM 호출
        response = self._call_llm(base_prompt)
        return {
            "type": response["type"],
            "method": "llm",
            "confidence": "medium",
            "reason": response.get("reason")
        }


class FailureFilter:
    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader

    def filter_failures(self, failures: List[dict]) -> dict:
        """
        실패 건 필터링
        - 정책상 제외
        - Noise
        - 분석 대상
        """
        result = {
            "to_analyze": [],
            "excluded_policy": [],
            "excluded_noise": []
        }

        for failure in failures:
            customer_code = failure["customer_code"]
            error_message = failure["error_message"]

            # 고객사별 제외 규칙
            exclude_rules = self.config_loader.get_exclude_rules(customer_code)

            # 1. 정책상 제외 체크
            if self._is_excluded_by_policy(error_message, exclude_rules):
                result["excluded_policy"].append(failure)
                continue

            # 2. Noise 체크
            if self._is_noise(failure, exclude_rules):
                result["excluded_noise"].append(failure)
                continue

            # 3. 분석 대상
            result["to_analyze"].append(failure)

        return result

    def _is_excluded_by_policy(self, error_message: str, exclude_rules: dict) -> bool:
        """정책상 제외 여부"""
        for rule in exclude_rules["policy_exclusions"]:
            if not rule.get("enabled", True):
                continue

            if re.search(rule["pattern"], error_message, re.IGNORECASE):
                return True
        return False

    def _is_noise(self, failure: dict, exclude_rules: dict) -> bool:
        """Noise 여부 (같은 날 다른 파일 성공)"""
        noise_rules = exclude_rules.get("noise_rules", {})
        threshold = noise_rules.get("same_day_success_threshold", 0.8)

        # 같은 날 성공률 체크 (BigQuery에서 미리 계산해서 넘김)
        same_day_success_rate = failure.get("same_day_success_rate", 0)
        return same_day_success_rate >= threshold
```

---

### 6. 메인 로직 (`main.py`)

```python
def generate_converter_report(target_date: str):
    """
    Converter 실패 리포트 생성
    """
    # 설정 로드
    config_loader = ConfigLoader("./config")
    classifier = ErrorClassifier(config_loader)
    filter_engine = FailureFilter(config_loader)

    # 1. BigQuery에서 실패 건 조회
    all_failures = fetch_failures_from_bq(target_date)

    # 2. 필터링 (정책 제외, Noise)
    filtered = filter_engine.filter_failures(all_failures)

    # 3. 분석 대상만 에러 분류
    to_analyze = filtered["to_analyze"]
    classified = []

    for failure in to_analyze:
        classification = classifier.classify(
            failure["error_message"],
            failure["customer_code"]
        )
        classified.append({**failure, **classification})

    # 4. 고객사별 그룹핑
    by_customer = group_by_customer_and_source(classified)

    # 5. 메시지 포맷팅
    message = format_message(
        by_customer=by_customer,
        excluded_policy=filtered["excluded_policy"],
        excluded_noise=filtered["excluded_noise"],
        config=config_loader.common_config
    )

    # 6. Teams 전송
    send_to_teams(message)
```

---

## 커스터마이징 시나리오

### 시나리오 1: 새 고객사 추가 (기본 설정)
```bash
# 아무 설정 안 해도 됨
# 공통 설정 자동 적용
```

### 시나리오 2: 특정 고객사만 xlsb 허용
```json
// config/exclude_rules/customer_exclude/c8cd3500.json (한투)
{
  "customer_code": "c8cd3500",
  "additional_exclusions": [],
  "rule_overrides": [
    {
      "id": "xlsb_not_supported",
      "enabled": false  // 이 고객사는 xlsb 제외 안 함
    }
  ]
}
```

### 시나리오 3: 고객사 특수 에러 패턴
```json
// config/customers/c0159c00.json (GC녹십자)
{
  "custom_exclude_rules": {
    "enabled": true,
    "rules": [
      {
        "pattern": "시험성적서.*Sheet",
        "reason": "시험성적서는 별도 처리",
        "enabled": true
      }
    ]
  },
  "llm_prompt_override": {
    "enabled": true,
    "additional_context": "제약회사 특수 용어: GST, MSDS, 시험성적서 등"
  }
}
```

### 시나리오 4: 연속 실패 임계값 변경
```json
// config/customers/c7005b01.json (고피자)
{
  "consecutive_fail_threshold_override": {
    "enabled": true,
    "value": 5  // 5일 연속 실패부터 알림
  }
}
```

---

## GCS 파일 접근 및 분석

### GCS 파일 경로 구조

실제 Excel 파일은 `gcs_path`에서 접근 가능합니다:

**BigQuery `convert_job_history`의 gcs_path**:
- 형식: `{source_type}/{source_id}/crawl/{file_id}`
- 예: `email/s12bf560/crawl/fcf7a5ae477c`

**실제 GCS 위치**:
- 버킷: `hyperlounge-{customer_code}`
- 경로: gcs_path 그대로
- 예: `gs://hyperlounge-c8cd3500/email/s12bf560/crawl/fcf7a5ae477c`

**Convert Config 위치**:
- 버킷: `hyperlounge-migrator`
- 경로: `convert_configs/{customer_code}/{config_id}.json`
- 예: `gs://hyperlounge-migrator/convert_configs/c8cd3500/eml_rv56_021.json`

---

### 파일 읽기 예시 코드

```python
from google.cloud import storage
import io
import pandas as pd
import json

def get_excel_from_gcs(customer_code: str, gcs_path: str):
    """
    gcs_path에서 실제 Excel 파일 읽기

    Args:
        customer_code: 고객사 코드 (예: "c8cd3500")
        gcs_path: BigQuery의 gcs_path 값 (예: "email/s12bf560/crawl/fcf7a5ae477c")

    Returns:
        pd.ExcelFile: Excel 파일 객체
    """
    storage_client = storage.Client(project='hyperlounge-dev')
    bucket_name = f"hyperlounge-{customer_code}"

    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(gcs_path)

    if not blob.exists():
        raise FileNotFoundError(f"File not found: gs://{bucket_name}/{gcs_path}")

    # Excel 파일 다운로드 및 로드
    excel_data = blob.download_as_bytes()
    excel_file = pd.ExcelFile(io.BytesIO(excel_data))

    return excel_file

def get_convert_config(customer_code: str, config_id: str):
    """
    Convert config JSON 읽기

    Args:
        customer_code: 고객사 코드
        config_id: config ID (예: "eml_rv56_021")

    Returns:
        dict: Convert config JSON
    """
    storage_client = storage.Client(project='hyperlounge-dev')
    bucket = storage_client.bucket("hyperlounge-migrator")
    blob = bucket.blob(f"convert_configs/{customer_code}/{config_id}.json")

    if not blob.exists():
        raise FileNotFoundError(f"Config not found: {config_id}")

    config = json.loads(blob.download_as_text())
    return config

# 사용 예시
excel_file = get_excel_from_gcs("c8cd3500", "email/s12bf560/crawl/fcf7a5ae477c")
print(f"시트 목록: {excel_file.sheet_names}")

config = get_convert_config("c8cd3500", "eml_rv56_021")
print(f"찾으려는 시트: {list(config['convert'].keys())}")
```

---

### 실제 분석 예시

2025-11-07 trinityspa (c8cd3500) email 실패 케이스:

**에러 정보** (BigQuery):
```
gcs_path: email/s12bf560/crawl/fcf7a5ae477c
convert_config_id: eml_rv56_021
error_message: not found matched sheet from ['Sheet1']
```

**실제 Excel 확인**:
```python
excel_file = get_excel_from_gcs("c8cd3500", "email/s12bf560/crawl/fcf7a5ae477c")
# 결과: sheet_names = ['Sheet1']
#       컬럼: ['가동일', '담당자', '가동률']
#       행 수: 2
```

**Convert Config 확인**:
```python
config = get_convert_config("c8cd3500", "eml_rv56_021")
# 결과: convert.keys() = ['티켓팅\\(.*\\)\\s*$']  # 정규식 패턴
```

**에러 원인 분석**:
- Config가 찾으려는 시트: `'티켓팅\(.*\)\s*$'` (정규식 - "티켓팅(어쩌고)" 형태)
- 실제 Excel의 시트: `['Sheet1']`
- **결론**: 시트 이름 불일치 → "not found matched sheet" 에러 발생

**해결 방안**:
1. Convert config 수정 (시트명 패턴 조정)
2. Excel 파일 재요청 (올바른 시트명 포함)
3. 소스 파일 자동 변환 규칙 추가

---

### LLM 분석 시 포함 정보

#### Phase 1: Basic (Error Message만)
```python
classification = classify_error(error_message)
# 규칙 기반으로 대부분 분류 가능
```

#### Phase 2: Enhanced (+ Convert Config)
```python
context = {
    "error_message": "not found matched sheet from ['Sheet1']",
    "convert_config": {
        "찾으려는_시트": "티켓팅\\(.*\\)\\s*$"
    }
}
# → LLM이 "시트명 패턴 불일치" 더 정확하게 파악
```

#### Phase 3: Deep Analysis (+ Actual Excel)
```python
context = {
    "error_message": "not found matched sheet from ['Sheet1']",
    "convert_config": {
        "찾으려는_시트": "티켓팅\\(.*\\)\\s*$"
    },
    "actual_excel": {
        "시트_목록": ["Sheet1"],
        "Sheet1_컬럼": ["가동일", "담당자", "가동률"],
        "Sheet1_행수": 2,
        "첫_3행_미리보기": [...]
    }
}
# → LLM이 정확한 원인 + 해결방안 제시 가능
```

**권장 접근**:
- 기본: Phase 1 (규칙 기반, 무료, 빠름)
- 필요 시: Phase 2 (Config 포함, 중요한 에러만)
- 특수 케이스: Phase 3 (Excel까지 읽기, 수동 분석 필요 시)

---

### 권한 요구사항

**필요한 IAM 권한**:
- `storage.objects.get` (Storage Object Viewer)
- `storage.objects.list` (필요 시)

**적용 범위**:
- `hyperlounge-{customer_code}` 버킷들 (Excel 파일)
- `hyperlounge-migrator` 버킷 (Convert configs)

---

## 구현 전략 및 로드맵

### 단계별 접근 방식

모니터링 시스템은 **점진적으로 개선**하는 방식으로 구현합니다.
- 처음부터 완벽한 시스템보다는 **작동하는 MVP**를 먼저 만들고
- **실제 운영 데이터**를 보면서 개선점 파악
- 진짜 필요한 기능만 추가 (오버엔지니어링 방지)

---

### Phase 1: MVP - 기본 모니터링 (1-3일)

**목표**: 매일 아침 Teams로 Converter 실패 리포트 받기

**핵심 기능**:
```
✅ BigQuery에서 어제 실패 건 조회
✅ 파일 레벨 그룹핑 (gcs_path 기준)
✅ 에러 분류 (규칙 기반만, LLM 없이)
✅ Teams 메시지 포맷팅
✅ RPA/Board vs NonRPA 구분
```

**의도적으로 제외**:
```
❌ LLM 에러 분석 → 규칙만으로 시작
❌ Excel 파일 읽기 → error_message만 사용
❌ Convert config 분석 → 나중에 필요하면
❌ Noise 필터링 → 일단 모든 실패 표시
❌ DAG 상태 체크 → 단순히 어제 날짜만
```

**실패 건수 많으면?**
- 상위 N개 고객사만 표시 (예: 10개)
- 나머지는 "기타 X개 고객사" 요약
- BigQuery 링크로 전체 보기

**구조**:
```
converter_monitor/
├─ main.py              # 메인 로직
├─ queries.py           # BigQuery 쿼리들
├─ classifier.py        # 에러 분류 (규칙만)
├─ formatter.py         # Teams 메시지 포맷
├─ config.py            # 설정값
└─ requirements.txt
```

**배포**: Cloud Scheduler + Cloud Function (간단)

---

### Phase 2: 운영 피드백 반영 (1-2주 운영 후)

**Phase 1 운영하면서 발견될 문제들**:

1. **실패 건수 통계 파악**
   ```
   문제: 매일 실패 건이 너무 많음 (100건+)
   대응:
   - Noise 필터링 추가 (같은 날 성공률 체크)
   - 정책상 제외 규칙 (xlsb, 암호화) 적용
   - 우선순위 로직 (연속 실패 > 일회성 실패)
   ```

2. **에러 패턴 분석**
   ```
   문제: 같은 에러가 반복됨
   대응:
   - 자주 나오는 에러 → 규칙에 추가
   - 분류 안 되는 에러 → LLM 도입 검토
   ```

3. **메시지 가독성**
   ```
   문제: 테이블이 너무 김
   대응:
   - 고객사 표시 개수 조정
   - 요약 레벨 변경
   - 링크 추가로 상세는 BigQuery/Grafana
   ```

4. **연속 실패 감지**
   ```
   문제: 같은 에러가 며칠째 반복
   대응:
   - DAG 상태 체크 추가
   - 연속 실패 일수 표시
   - 3일 이상 실패 시 강조
   ```

**개선 항목 우선순위** (실제 데이터 보고 결정):
- [ ] Noise 필터링
- [ ] 정책상 제외 규칙
- [ ] 연속 실패 감지
- [ ] LLM 에러 분류
- [ ] DAG 상태 체크

---

### Phase 3: Convert Config 분석 도구 (필요성 확인 후)

**배경**:
- Convert config JSON은 복잡하고 분석이 어려움
- 실패 원인 파악을 위해 **config vs 실제 Excel 비교** 필요
- 수동으로 하기엔 시간이 너무 많이 걸림

**Convert Config의 복잡성**:
```json
// collector/c0159c00/eml_gi00_011.json 예시
{
  "convert": {
    "약효": {  // 시트명 패턴 (정규식 가능)
      "TB01": {
        "header": true,
        "cols": "A:D",
        "rows": {
          "start": {
            "header_coordinate": "A",
            "expr": "구분",  // 정규식으로 헤더 찾기
            "match": 1,
            "offset": 0
          },
          "end": {
            "header_name": "구분",
            "empty": true
          }
        }
      }
    }
  }
}
```

**문제점**:
1. 시트명이 정규식이라 어떤 이름을 찾는지 불명확
2. 헤더 찾기 로직이 복잡 (coordinate, expr, offset...)
3. 실패 시 "어디가 문제인지" 파악 어려움
4. 과거 성공 케이스와 비교하고 싶은데 방법이 없음

---

### Convert Config Analyzer 설계

#### 목표
- Config JSON을 **시각화**하여 이해하기 쉽게
- 실패 Excel vs 성공 Excel **양쪽 비교**
- **자동으로 해결방안 제시**

#### 핵심 기능

##### 1. Config 시각화 (Human-Readable)

**입력**: `eml_rv56_021.json`
```json
{
  "convert": {
    "티켓팅\\(.*\\)\\s*$": {
      "TB01": { ... }
    }
  }
}
```

**출력**:
```
📄 Convert Config: eml_rv56_021

🔍 시트 매칭 규칙:
  패턴: '티켓팅\(.*\)\s*$' (정규식)

  설명:
  - "티켓팅"으로 시작
  - 괄호() 안에 임의의 텍스트 (.*)
  - 공백(\s*) 후 줄 끝($)

  매칭 예시:
    ✅ "티켓팅(11월)"
    ✅ "티켓팅(매출) "
    ✅ "티켓팅(일일집계)  "
    ❌ "Sheet1"
    ❌ "티켓팅"
    ❌ "티켓팅데이터"

📊 테이블 추출 규칙 (TB01):
  컬럼 범위: A:D

  헤더 찾기:
    - A 컬럼에서 "구분" 텍스트 검색
    - 1번째 매칭되는 행
    - offset 0 (바로 그 행부터)

  데이터 범위:
    - 시작: 헤더 행
    - 끝: "구분" 컬럼이 비어있는 행 (미포함)
```

##### 2. 실패 vs 성공 Excel 비교 대시보드

**웹 UI 레이아웃**:
```
┌────────────────────────────────────────────────────────────────┐
│  Converter 실패 분석: c8cd3500 - eml_rv56_021                   │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────┬─────────────────────────┐         │
│  │  ❌ 실패 케이스          │  ✅ 성공 케이스 (과거)   │         │
│  ├─────────────────────────┼─────────────────────────┤         │
│  │  📅 2025-11-07          │  📅 2025-10-15          │         │
│  │  gcs_path:              │  gcs_path:              │         │
│  │  email/.../fcf7a5ae477c │  email/.../a1b2c3d4     │         │
│  │                         │                         │         │
│  │  📊 Excel 정보:          │  📊 Excel 정보:          │         │
│  │  ├─ 시트 목록:           │  ├─ 시트 목록:           │         │
│  │  │  • Sheet1           │  │  • 티켓팅(11월)      │         │
│  │  │                     │  │                     │         │
│  │  ├─ [Sheet1] 구조:      │  ├─ [티켓팅(11월)] 구조: │         │
│  │  │  컬럼: 가동일,       │  │  컬럼: 날짜, 담당자, │         │
│  │  │        담당자,       │  │        매출, 비고    │         │
│  │  │        가동률        │  │                     │         │
│  │  │  행 수: 2           │  │  행 수: 145         │         │
│  │  │                     │  │                     │         │
│  │  │  미리보기:           │  │  미리보기:           │         │
│  │  │  [테이블 표시]       │  │  [테이블 표시]       │         │
│  │                         │                         │         │
│  └─────────────────────────┴─────────────────────────┘         │
│                                                                 │
│  📄 Convert Config (eml_rv56_021):                             │
│  ┌─────────────────────────────────────────────────┐           │
│  │  시트 패턴: '티켓팅\(.*\)\s*$'                   │           │
│  │                                                 │           │
│  │  ✅ 성공 케이스 매칭:                            │           │
│  │     "티켓팅(11월)" ← 패턴 일치                   │           │
│  │                                                 │           │
│  │  ❌ 실패 케이스 매칭:                            │           │
│  │     "Sheet1" ← 패턴 불일치                       │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  ⚠️  불일치 원인 분석:                                          │
│  ┌─────────────────────────────────────────────────┐           │
│  │  문제: 시트 이름이 패턴과 맞지 않음              │           │
│  │                                                 │           │
│  │  Config는 "티켓팅(...)" 형태의 시트를 찾지만     │           │
│  │  실제 Excel에는 "Sheet1"만 존재                  │           │
│  │                                                 │           │
│  │  과거 성공 케이스에서는 "티켓팅(11월)" 시트가     │           │
│  │  존재하여 정상 처리됨                            │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
│  💡 추천 해결방안:                                              │
│  ┌─────────────────────────────────────────────────┐           │
│  │  1. Convert Config 수정 (권장)                   │           │
│  │     시트 패턴에 "Sheet1" 추가:                   │           │
│  │     {                                           │           │
│  │       "convert": {                              │           │
│  │         "티켓팅\\(.*\\)\\s*$": { ... },           │           │
│  │         "Sheet1": { ... }  ← 추가               │           │
│  │       }                                         │           │
│  │     }                                           │           │
│  │     [Config 수정하기] [테스트]                   │           │
│  │                                                 │           │
│  │  2. Excel 파일 재요청                            │           │
│  │     고객사에 "티켓팅(월)" 형태로 시트명 변경 요청 │           │
│  │                                                 │           │
│  │  3. 소스 자동 변환 규칙 추가                      │           │
│  │     "Sheet1" → "티켓팅(현재월)" 자동 변환        │           │
│  └─────────────────────────────────────────────────┘           │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

##### 3. Config Editor & Tester

**기능**:
- Config JSON 직접 편집 (웹 에디터)
- 실시간 문법 검증
- 테스트 Excel 업로드해서 미리 검증
- 변경사항 Git 커밋/PR 자동 생성

**워크플로우**:
```
1. 실패 케이스 확인
   ↓
2. 비교 대시보드에서 원인 파악
   ↓
3. Config 수정안 확인
   ↓
4. 웹 에디터에서 수정
   ↓
5. 테스트 Excel로 검증
   ↓
6. 통과하면 자동으로 PR 생성
   ↓
7. 리뷰 후 머지
```

---

#### 기술 스택 제안

##### 웹 대시보드
```python
# Option 1: Streamlit (빠른 프로토타입)
streamlit run app.py
# 장점: 빠르게 만들 수 있음
# 단점: 커스터마이징 제한

# Option 2: Flask + React (본격 개발)
# 장점: 자유로운 UI, 확장성
# 단점: 개발 시간 오래 걸림

# 추천: Streamlit으로 시작 → 필요하면 Flask 전환
```

##### Excel 비교 로직
```python
from google.cloud import storage, bigquery
import pandas as pd
import json
import re
from difflib import SequenceMatcher

class ConvertConfigAnalyzer:
    """Convert Config와 Excel 파일 분석"""

    def __init__(self):
        self.storage_client = storage.Client()
        self.bq_client = bigquery.Client()

    def analyze_failure(self, customer_code, config_id, failed_gcs_path):
        """
        실패 케이스 분석

        1. Failed Excel 읽기
        2. Convert Config 읽기
        3. 과거 성공 케이스 찾기
        4. 비교 분석
        5. 해결방안 제시
        """
        # 1. 실패 Excel
        failed_excel = self.get_excel(customer_code, failed_gcs_path)

        # 2. Config
        config = self.get_config(customer_code, config_id)

        # 3. 과거 성공 케이스 (BigQuery 조회)
        success_case = self.find_last_success(customer_code, config_id)
        success_excel = self.get_excel(customer_code, success_case['gcs_path'])

        # 4. 비교
        comparison = self.compare_excels(
            failed_excel,
            success_excel,
            config
        )

        # 5. 해결방안
        solutions = self.suggest_solutions(comparison)

        return {
            'failed': failed_excel,
            'success': success_excel,
            'config': config,
            'comparison': comparison,
            'solutions': solutions
        }

    def compare_excels(self, failed, success, config):
        """Excel 파일 비교"""
        sheet_pattern = list(config['convert'].keys())[0]

        return {
            'sheet_names': {
                'failed': failed.sheet_names,
                'success': success.sheet_names,
                'pattern': sheet_pattern,
                'failed_matched': self.match_sheet(failed.sheet_names, sheet_pattern),
                'success_matched': self.match_sheet(success.sheet_names, sheet_pattern)
            },
            'structure': {
                # 컬럼, 행 수 비교
            },
            'content_sample': {
                # 첫 N행 비교
            }
        }

    def match_sheet(self, sheet_names, pattern):
        """시트명 패턴 매칭 검증"""
        for sheet in sheet_names:
            if re.match(pattern, sheet):
                return sheet
        return None

    def suggest_solutions(self, comparison):
        """자동 해결방안 제시"""
        solutions = []

        # 시트 불일치
        if not comparison['sheet_names']['failed_matched']:
            solutions.append({
                'type': 'config_update',
                'priority': 'high',
                'description': 'Config에 실패 케이스 시트명 추가',
                'code': self.generate_config_patch(comparison)
            })

            solutions.append({
                'type': 'request_fix',
                'priority': 'medium',
                'description': '고객사에 올바른 시트명 요청'
            })

        return solutions
```

##### Config 시각화
```python
class ConfigVisualizer:
    """Config JSON을 Human-Readable로 변환"""

    def visualize(self, config):
        """Config를 설명 텍스트로 변환"""
        output = []

        for sheet_pattern, tables in config['convert'].items():
            output.append(f"🔍 시트 매칭 규칙:")
            output.append(f"  패턴: '{sheet_pattern}'")

            # 정규식 설명
            if self.is_regex(sheet_pattern):
                explanation = self.explain_regex(sheet_pattern)
                output.append(f"\n  설명:")
                output.extend([f"  - {line}" for line in explanation])

                # 매칭 예시
                examples = self.generate_examples(sheet_pattern)
                output.append(f"\n  매칭 예시:")
                for ex, matches in examples:
                    symbol = "✅" if matches else "❌"
                    output.append(f"    {symbol} \"{ex}\"")

            # 테이블 규칙
            for table_name, table_config in tables.items():
                output.append(f"\n📊 테이블: {table_name}")
                # ... (생략)

        return "\n".join(output)

    def explain_regex(self, pattern):
        """정규식을 자연어로 설명"""
        # 간단한 패턴 매칭으로 설명 생성
        explanations = []

        if pattern.startswith("^"):
            explanations.append("줄 시작부터")
        if pattern.endswith("$"):
            explanations.append("줄 끝까지")
        if r"\(" in pattern:
            explanations.append("괄호() 포함")
        if ".*" in pattern:
            explanations.append("임의의 텍스트")
        if r"\s*" in pattern:
            explanations.append("공백 허용")

        return explanations
```

---

#### 구현 우선순위

**지금 당장 필요한가?**
- Phase 1, 2 운영해보고 **실제로 Config 분석이 자주 필요한지** 확인
- 만약 실패 케이스가 대부분 "시트명 불일치" 같은 단순 문제면 → 꼭 필요
- 복잡한 에러가 많지 않으면 → 나중에

**구현한다면 순서**:
1. **Config 시각화** (가장 쉽고 유용)
2. **실패 vs 성공 비교** (핵심 기능)
3. **Config Editor** (여유 있으면)

---

### Phase 4: 고도화 (선택사항)

**필요성이 입증된 후에만 구현**:

- [ ] LLM 기반 에러 원인 분석 (Phase 2 + Excel 읽기)
- [ ] Convert Config 자동 생성 (Excel 업로드 → Config 추천)
- [ ] 실시간 알림 (Slack/Teams에 즉시 알림)
- [ ] Grafana 대시보드 통합
- [ ] 과거 트렌드 분석 (에러 증가 추세 감지)
- [ ] 자동 복구 시도 (Config 자동 수정 PR)

---

## 구현 시 주의사항

### 1. 실패 건수가 너무 많을 경우

**예상 시나리오**:
```
매일 500건 실패 → Teams 메시지 너무 김
```

**대응 전략** (우선순위 순):

#### Level 1: 기본 필터링 (Phase 1부터)
```python
# 상위 N개만 표시
MAX_CUSTOMERS = 10

# 나머지는 요약
if len(customers) > MAX_CUSTOMERS:
    shown = customers[:MAX_CUSTOMERS]
    hidden_count = len(customers) - MAX_CUSTOMERS
    message += f"\n⚠️ 기타 {hidden_count}개 고객사 (BigQuery에서 확인)"
```

#### Level 2: 정책상 제외 (Phase 2)
```python
# 자동 제외
POLICY_EXCLUSIONS = [
    r"xlsb.*not supported",
    r"encrypted",
    r"File size exceeds"
]

# 메시지에서 분리
excluded_count = ...
message += f"\n📋 정책상 제외: {excluded_count}건 (xlsb, 암호화 등)"
```

#### Level 3: Noise 필터링 (Phase 2)
```python
# 같은 날 성공률 80% 이상이면 Noise
def is_noise(failure_record):
    same_day_success_rate = calculate_success_rate(
        failure_record['customer_code'],
        failure_record['convert_config_id'],
        failure_record['date']
    )
    return same_day_success_rate >= 0.8

# Noise는 별도 섹션
message += f"\n🔇 Noise: {noise_count}건 (같은 날 대부분 성공)"
```

#### Level 4: 우선순위 정렬 (Phase 2)
```python
# 중요도 순 정렬
def calculate_priority(failure):
    score = 0

    # 연속 실패일수 높으면 우선
    score += failure['consecutive_days'] * 10

    # RPA/Board가 NonRPA보다 우선
    if failure['source_type'] in ['rpa', 'board']:
        score += 5

    # 실패 테이블 수 많으면 우선
    score += failure['table_count']

    return score

customers.sort(key=calculate_priority, reverse=True)
```

### 2. Config 파일 분석 복잡도

**문제점**:
- Config JSON이 복잡함 (정규식, 중첩 구조)
- 모든 케이스를 자동 분석하기 어려움

**대응**:
```python
# 완벽한 자동 분석 X
# → 일단 "시트명 불일치" 같은 명확한 케이스만 처리

def analyze_config_error(error_message, config):
    """간단한 케이스만 자동 분석"""

    # 시트 에러만 처리
    if "not found matched sheet" in error_message:
        return analyze_sheet_mismatch(error_message, config)

    # 헤더 에러는 복잡해서 일단 패스
    elif "row not found" in error_message:
        return {
            'analysis': 'manual_required',
            'message': '헤더 에러는 수동 분석 필요'
        }

    # 나머지도 패스
    else:
        return {
            'analysis': 'unknown',
            'message': 'Config Analyzer 필요'
        }
```

### 3. 과거 성공 케이스 찾기

**문제**:
- 같은 config로 성공한 케이스가 없을 수도 있음
- 너무 오래된 성공 케이스는 의미 없음

**대응**:
```python
def find_last_success(customer_code, config_id, max_days=30):
    """
    최근 N일 이내 성공 케이스 찾기

    없으면 None 반환
    """
    query = f"""
    SELECT gcs_path, created_at
    FROM `convert_job_history`
    WHERE customer_code = '{customer_code}'
      AND convert_config_id = '{config_id}'
      AND status = 'success'
      AND DATE(created_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL {max_days} DAY)
    ORDER BY created_at DESC
    LIMIT 1
    """

    result = bq_client.query(query).result()

    if result.total_rows == 0:
        return None  # 성공 케이스 없음

    return next(result)
```

**UI 처리**:
```
✅ 성공 케이스 (과거)
  ⚠️ 최근 30일 내 성공 기록 없음

  이 Config는 계속 실패 중이거나
  새로 추가된 Config일 수 있습니다.
```

---

## 설계 원칙

### 1. 점진적 개선 (Incremental Improvement)
- 완벽한 시스템보다 **작동하는 시스템**
- 실제 데이터 보고 개선
- 불필요한 기능 만들지 않기

### 2. 실용주의 (Pragmatism)
- LLM: 필요하면 쓰되, 규칙으로 해결 가능하면 규칙 사용
- Config 분석: 100% 자동화 불가능 → 명확한 케이스만
- 대시보드: Streamlit으로 빠르게 시작

### 3. 확장 가능성 (Scalability)
- 나중에 기능 추가하기 쉽게 모듈화
- Config 기반 (하드코딩 최소화)
- 고객사별 커스터마이징 지원

### 4. 운영 친화적 (Ops-Friendly)
- 에러 나도 일단 메시지는 보냄 (Fail-safe)
- 로그 잘 남기기 (디버깅 용이)
- BigQuery 링크로 원본 데이터 접근 쉽게

---

## 다음 논의 포인트

### 기술 결정 필요

1. **Phase 1 배포 방식**
   - Cloud Function? Cloud Run?
   - 실행 주기: 매일 아침 몇 시?

2. **메시지 길이 제한**
   - 최대 표시 고객사 수: 10개? 20개?
   - 테이블 최대 행 수는?

3. **BigQuery 링크**
   - Looker Studio? 직접 BigQuery 콘솔?
   - 미리 만들어둘 쿼리는?

4. **Noise 판정 기준** (Phase 2)
   - 같은 날 성공률: 80%? 50%?
   - 고객사별로 다르게 설정?

5. **연속 실패 기준** (Phase 2)
   - RPA/Board: 며칠부터 강조?
   - DAG 상태 체크 필요?

### 구현 우선순위 확인

- [ ] Phase 1 MVP 먼저 구현? ✅
- [ ] Config Analyzer 필요성 있는지 확인? 🤔
- [ ] 파일럿 고객사 선정?

### Convert Config Analyzer 관련

1. **정말 필요한가?**
   - Phase 1, 2 운영 후 판단?
   - 지금 바로 필요?

2. **필요하다면 범위는?**
   - 시각화만?
   - Excel 비교까지?
   - Editor까지?

3. **기술 스택**
   - Streamlit? Flask?
   - 배포는 어떻게?

---

## Phase 1 구현 아키텍처

### 기술 스택 (Tech Stack)

#### 언어 및 런타임
- **Python 3.9** ✅
  - airflow_dag_monitor와 동일
  - GCP 라이브러리 안정적 지원
  - 타입 힌팅 지원 (Python 3.9+)

#### GCP 서비스
- **Cloud Run Job** ✅
  - 배치 작업에 최적화
  - 실행 시간 제한 없음 (최대 60분)
  - 리소스 유연하게 조정 가능
  - 로컬 Docker 테스트 가능

- **Cloud Scheduler** ✅
  - Cron 기반 스케줄링
  - Cloud Run Job 트리거
  - Timezone 지원 (Asia/Seoul)

- **BigQuery** ✅
  - `convert_job_history` 테이블 조회
  - 빠른 분석 쿼리

- **Firestore** ✅
  - 고객사 정보 (customer names)
  - env 필터링 (ops/dev)

- **Cloud Logging** ✅
  - 구조화된 로그
  - 모니터링 및 디버깅

- **Secret Manager** ✅ (권장)
  - Teams Webhook URL 보안 저장

#### Python 라이브러리

**핵심 라이브러리**:
```python
# GCP 클라이언트
google-cloud-bigquery==3.11.0      # BigQuery 조회
google-cloud-firestore==2.11.0     # Firestore 조회

# 기본 라이브러리
requests==2.31.0                   # Teams webhook 호출
pytz==2023.3                       # Timezone (KST)
```

**선택 라이브러리** (Phase 2+):
```python
# LLM 에러 분석 (Phase 2)
openai==1.3.0                      # OpenAI API
# or
google-cloud-aiplatform==1.38.0    # Vertex AI

# Excel 파일 읽기 (Phase 3)
pandas==2.1.0                      # Excel 파싱
openpyxl==3.1.2                    # xlsx 지원
google-cloud-storage==2.10.0       # GCS 파일 읽기
```

#### 컨테이너
- **Docker** ✅
  - Python 3.9-slim 베이스 이미지
  - Multi-stage build 불필요 (간단한 구조)

- **GCR (Google Container Registry)** ✅
  - Docker 이미지 저장소
  - Cloud Run Job과 통합

#### 메시징
- **Microsoft Teams Webhook** ✅
  - Incoming Webhook 커넥터
  - JSON payload 전송

#### 개발 도구
- **Git** ✅
  - 버전 관리
  - 코드 리뷰

- **VS Code** (권장)
  - Python 확장
  - Docker 확장

---

### 기술 선택 근거

#### 1. 왜 Python 3.9?

**선택 이유**:
- airflow_dag_monitor와 동일 버전 (일관성)
- GCP 라이브러리 안정적 지원
- 타입 힌팅 지원으로 코드 품질 향상

**대안 고려**:
- ❌ Python 3.11+: GCP 일부 라이브러리 미지원
- ❌ Python 3.7: 너무 오래됨, EOL 임박
- ✅ Python 3.9: 안정성과 최신 기능 균형

---

#### 2. 왜 Cloud Run Job?

**선택 이유**:
- ✅ **일관성**: airflow_dag_monitor와 동일 패턴
- ✅ **실행 시간**: 최대 60분 (Cloud Function은 9분)
- ✅ **리소스**: 메모리/CPU 유연하게 조정
- ✅ **디버깅**: 로컬 Docker 테스트 가능
- ✅ **비용**: 실행 시간만큼만 과금

**대안 비교**:

| 특성 | Cloud Function | Cloud Run Job | GKE CronJob |
|------|---------------|---------------|-------------|
| 최대 실행 시간 | 9분 | 60분 | 제한 없음 |
| 설정 복잡도 | 간단 | 간단 | 복잡 |
| 로컬 테스트 | 어려움 | 쉬움 | 쉬움 |
| 비용 | 저렴 | 중간 | 비쌈 |
| 유지보수 | 쉬움 | 쉬움 | 어려움 |

**결론**: Cloud Run Job이 최적 ✅

---

#### 3. 왜 Cloud Scheduler?

**선택 이유**:
- ✅ GCP 네이티브 (통합 용이)
- ✅ Cron 표현식 지원
- ✅ Timezone 지원 (Asia/Seoul)
- ✅ Cloud Run Job 직접 트리거
- ✅ 무료 (월 3개까지)

**대안 비교**:

| 서비스 | 장점 | 단점 |
|--------|------|------|
| Cloud Scheduler | GCP 통합, 간단 | N/A |
| Airflow | 복잡한 워크플로우 | 오버킬, 관리 복잡 |
| Cron (VM) | 유연 | VM 관리 필요 |

**결론**: Cloud Scheduler가 최적 ✅

---

#### 4. 왜 BigQuery?

**선택 이유**:
- ✅ 이미 `convert_job_history` 테이블 존재
- ✅ 빠른 분석 쿼리 (파티션 테이블)
- ✅ SQL 친숙함
- ✅ 서버리스 (관리 불필요)

**사용 패턴**:
```sql
-- 단일 날짜 조회 (매우 빠름)
WHERE DATE(created_at, 'Asia/Seoul') = '2025-11-07'
  AND status = 'fail'
  AND env != 'dev'
```

---

#### 5. 왜 Firestore?

**선택 이유**:
- ✅ 이미 고객사 정보 저장 중
- ✅ NoSQL로 유연한 스키마
- ✅ env 필터링 필요 (BigQuery에도 있지만 customer_name 매핑 필요)

**사용 패턴**:
```python
# env != 'dev' 고객사 필터링
# customer_code → customer_name 매핑
```

**대안 고려**:
- BigQuery만 사용?
  - 장점: 단일 데이터 소스
  - 단점: customer_name이 중복 저장되어 있을 수 있음
  - 결론: Firestore를 source of truth로 사용

---

#### 6. 왜 Teams Webhook?

**선택 이유**:
- ✅ 이미 airflow_dag_monitor에서 사용 중
- ✅ 설정 간단 (Incoming Webhook만)
- ✅ 코드 단순 (HTTP POST만)

**사용 패턴**:
```python
import requests

payload = {"text": message}
requests.post(WEBHOOK_URL, json=payload)
```

**대안 고려**:
- Slack: 추가 통합 필요
- Email: 포맷팅 제한적
- PubSub: 오버킬

---

#### 7. 왜 Docker?

**선택 이유**:
- ✅ Cloud Run Job 요구사항
- ✅ 로컬 테스트 가능
- ✅ 의존성 격리
- ✅ 재현 가능한 환경

**베이스 이미지**:
```dockerfile
FROM python:3.9-slim  # ✅ 작은 크기, 빠른 빌드
```

**대안**:
- `python:3.9`: 너무 큼 (900MB)
- `python:3.9-alpine`: 일부 라이브러리 빌드 문제
- `python:3.9-slim`: 적절한 크기 (150MB) ✅

---

#### 8. Phase 2+ 기술 스택

**LLM 에러 분석** (Phase 2):

**Option A: OpenAI API** (권장)
```python
import openai

# 장점:
# - API 간단
# - GPT-4o-mini 저렴 ($0.15/1M tokens)
# - 빠른 응답

# 단점:
# - 외부 서비스 (GCP 밖)
# - 데이터 외부 전송
```

**Option B: Vertex AI (PaLM/Gemini)**
```python
from google.cloud import aiplatform

# 장점:
# - GCP 네이티브
# - 데이터가 GCP 내부에만
# - 통합 결제

# 단점:
# - API 복잡
# - 비용이 더 높을 수 있음
# - 응답 속도 느릴 수 있음
```

**추천**: OpenAI API (간단, 저렴, 빠름) ✅

---

**Excel 파일 분석** (Phase 3):

```python
# 필요 라이브러리
google-cloud-storage==2.10.0   # GCS 파일 읽기
pandas==2.1.0                  # Excel 파싱
openpyxl==3.1.2                # xlsx 지원
xlrd==2.0.1                    # xls 지원 (필요시)
```

**사용 패턴**:
```python
from google.cloud import storage
import pandas as pd
import io

# GCS에서 Excel 읽기
storage_client = storage.Client()
bucket = storage_client.bucket("hyperlounge-c8cd3500")
blob = bucket.blob("email/s12bf560/crawl/fcf7a5ae477c")

excel_data = blob.download_as_bytes()
excel_file = pd.ExcelFile(io.BytesIO(excel_data))

# 시트 목록
print(excel_file.sheet_names)

# 시트 읽기
df = pd.read_excel(excel_file, sheet_name="Sheet1")
```

---

**Convert Config Analyzer 웹 대시보드** (Phase 3):

**Option A: Streamlit** (권장 - 빠른 프로토타입)
```python
streamlit==1.28.0

# 장점:
# - 빠른 개발 (Python만으로 UI)
# - 데이터 시각화 기본 제공
# - 배포 간단

# 단점:
# - 커스터마이징 제한
# - 성능 제한 (대용량 데이터)
```

**Option B: Flask + React** (본격 개발)
```python
flask==3.0.0
flask-cors==4.0.0

# + React 프론트엔드

# 장점:
# - 완전한 커스터마이징
# - 프로덕션 레벨 성능
# - 확장성

# 단점:
# - 개발 시간 오래 걸림
# - 프론트엔드/백엔드 분리 필요
```

**추천 순서**:
1. Streamlit으로 프로토타입 ✅
2. 필요하면 Flask + React 전환

---

### 의존성 관리

#### requirements.txt (Phase 1)

```txt
# GCP 클라이언트
google-cloud-bigquery==3.11.0
google-cloud-firestore==2.11.0

# HTTP 요청
requests==2.31.0

# Timezone
pytz==2023.3

# 로깅 (기본 제공이지만 명시)
# logging (built-in)
```

#### requirements-dev.txt (개발용)

```txt
# 테스트
pytest==7.4.0
pytest-cov==4.1.0
pytest-mock==3.11.1

# 코드 품질
black==23.7.0          # 포맷팅
flake8==6.1.0          # 린팅
mypy==1.5.0            # 타입 체킹

# 로컬 테스트
python-dotenv==1.0.0   # .env 파일 지원
```

---

### 버전 관리 전략

**Python 라이브러리**:
- 메이저.마이너 버전 고정 (예: `3.11.0`)
- 보안 패치는 수동 업데이트
- Dependabot 사용 안 함 (수동 관리)

**Docker 베이스 이미지**:
- `python:3.9-slim` (태그 고정 안 함)
- 매 빌드마다 최신 패치 반영
- 특정 버전 고정은 재현성 필요 시만

**이유**:
- 자동 업데이트보다 안정성 우선
- 테스트 후 수동 업데이트
- 프로덕션 예상치 못한 변경 방지

---

### 개발 환경 설정

#### 로컬 개발

```bash
# 1. Python 가상환경
python3.9 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# 2. 의존성 설치
pip install -r requirements.txt
pip install -r requirements-dev.txt  # 개발용

# 3. 환경변수 설정 (.env)
cat > .env << EOF
GCP_PROJECT_ID=hyperlounge-dev
TEAMS_WEBHOOK_URL=https://...
LOG_LEVEL=DEBUG
EOF

# 4. 실행
python -m converter_failure_monitor.main
```

#### Docker 개발

```bash
# 1. 빌드
docker build -t converter-failure-monitor:dev .

# 2. 실행 (환경변수 주입)
docker run \
  --env-file .env \
  -v ~/.config/gcloud:/root/.config/gcloud \
  converter-failure-monitor:dev

# 3. 인터랙티브 디버깅
docker run -it \
  --env-file .env \
  --entrypoint /bin/bash \
  converter-failure-monitor:dev
```

---

### 코드 품질 도구

#### Black (코드 포맷팅)

```bash
# 자동 포맷팅
black converter_failure_monitor/

# 설정 (pyproject.toml)
[tool.black]
line-length = 120
target-version = ['py39']
```

#### Flake8 (린팅)

```bash
# 린팅 체크
flake8 converter_failure_monitor/

# 설정 (.flake8)
[flake8]
max-line-length = 120
exclude = __pycache__,.venv
ignore = E203,W503  # Black 호환
```

#### MyPy (타입 체킹)

```bash
# 타입 체크
mypy converter_failure_monitor/

# 설정 (pyproject.toml)
[tool.mypy]
python_version = "3.9"
warn_return_any = true
warn_unused_configs = true
```

**적용 여부**: Phase 1은 스킵, Phase 2부터 적용 고려 ⚠️

---

### CI/CD (선택사항)

#### GitHub Actions (Phase 2+)

```yaml
# .github/workflows/deploy.yml
name: Deploy Converter Monitor

on:
  push:
    branches: [main]
    paths:
      - 'converter_failure_monitor/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup Cloud SDK
        uses: google-github-actions/setup-gcloud@v1

      - name: Deploy
        run: |
          cd converter_failure_monitor
          ./deploy.sh
```

**Phase 1**: 수동 배포로 시작 ✅
**Phase 2+**: 자동화 고려

---

### 전체 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloud Scheduler                          │
│              (매일 아침 8시 KST 실행)                        │
└────────────────────┬────────────────────────────────────────┘
                     │ Trigger
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   Cloud Run Job                             │
│              (converter_failure_monitor)                    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  main.py                                            │   │
│  │  - 메인 오케스트레이션                               │   │
│  │  - 전체 흐름 제어                                    │   │
│  └─────────┬───────────────────────────────────────────┘   │
│            │                                                │
│            ├─► clients/                                     │
│            │   ├─ bigquery_client.py (BigQuery 조회)       │
│            │   └─ firestore_client.py (고객사 정보)        │
│            │                                                │
│            ├─► analyzer/                                    │
│            │   ├─ classifier.py (에러 분류)                │
│            │   ├─ filter.py (필터링 로직)                  │
│            │   └─ aggregator.py (집계)                     │
│            │                                                │
│            ├─► formatter/                                   │
│            │   └─ teams_formatter.py (Teams 메시지)        │
│            │                                                │
│            └─► config/                                      │
│                ├─ constants.py (상수)                       │
│                └─ error_patterns.py (에러 규칙)            │
└────────────────────┬───────────────────────────────────────┘
                     │
                     ├─► BigQuery (convert_job_history)
                     ├─► Firestore (customer info)
                     └─► Teams Webhook
```

---

### 디렉토리 구조

```
converter_failure_monitor/
├─ Dockerfile                    # Cloud Run 배포용
├─ requirements.txt              # Python 의존성
├─ deploy.sh                     # 배포 스크립트
├─ README.md                     # 설명서
│
├─ main.py                       # 진입점 (Cloud Run이 실행)
│
├─ clients/                      # 외부 서비스 클라이언트
│  ├─ __init__.py
│  ├─ bigquery_client.py         # BigQuery 조회
│  └─ firestore_client.py        # Firestore 조회 (고객사 정보)
│
├─ analyzer/                     # 분석 로직
│  ├─ __init__.py
│  ├─ classifier.py              # 에러 분류 (규칙 기반)
│  ├─ filter.py                  # 필터링 (정책 제외, Noise - Phase 2)
│  └─ aggregator.py              # 집계 (파일 레벨 그룹핑)
│
├─ formatter/                    # 메시지 포맷팅
│  ├─ __init__.py
│  └─ teams_formatter.py         # Teams 메시지 생성
│
├─ config/                       # 설정
│  ├─ __init__.py
│  ├─ constants.py               # 상수 (WEBHOOK_URL 등)
│  └─ error_patterns.py          # 에러 분류 규칙
│
└─ utils/                        # 유틸리티
   ├─ __init__.py
   └─ logger.py                  # 로깅 설정
```

---

### 참조 아키텍처: airflow_dag_monitor

**기존 시스템과 동일한 패턴 사용**:
- ✅ Cloud Run Job (not Cloud Function)
- ✅ Dockerfile 기반 배포
- ✅ clients/ 디렉토리 패턴
- ✅ utils/ 디렉토리 패턴
- ✅ constants.py로 환경변수 관리

**airflow_dag_monitor 구조**:
```
airflow_dag_monitor/
├─ Dockerfile
├─ requirements.txt
├─ deploy.sh
├─ main.py
├─ clients/
│  ├─ airflow_client.py
│  └─ bigquery_client.py
├─ utils/
│  └─ formatter.py
└─ constants.py
```

**converter_failure_monitor도 동일 패턴 적용**:
- Cloud Run Job으로 배포
- 동일한 디렉토리 구조
- 동일한 배포 스크립트 패턴

---

### 주요 컴포넌트 설계

#### 1. main.py (진입점)

```python
# converter_failure_monitor/main.py

import os
import logging
from datetime import datetime, timedelta
import pytz

from .clients.bigquery_client import BigQueryClient
from .clients.firestore_client import FirestoreClient
from .analyzer.classifier import ErrorClassifier
from .analyzer.aggregator import FailureAggregator
from .formatter.teams_formatter import TeamsFormatter
from .config.constants import WEBHOOK_URL, PROJECT_ID

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_monitor():
    """메인 실행 함수"""
    logger.info("🚀 Converter Failure Monitor Started")

    # 클라이언트 초기화
    bq_client = BigQueryClient(project_id=PROJECT_ID)
    fs_client = FirestoreClient()

    # KST 기준 어제 날짜 계산
    KST = pytz.timezone('Asia/Seoul')
    now = datetime.now(KST)

    # 오전 9시 규칙 (airflow_dag_monitor와 동일)
    if now.hour < 9:
        target_date = (now - timedelta(days=1)).date()
    else:
        target_date = now.date() - timedelta(days=1)

    logger.info(f"Target date: {target_date}")

    # 1. BigQuery에서 실패 건 조회
    logger.info("Step 1: Fetching failures from BigQuery...")
    failures = bq_client.get_failures(target_date)
    logger.info(f"Found {len(failures)} failure records")

    if not failures:
        send_success_message(target_date)
        return

    # 2. Firestore에서 고객사 정보 (env != 'dev')
    logger.info("Step 2: Fetching customer info from Firestore...")
    active_customers = fs_client.get_active_customers()  # env != 'dev'
    customer_names = fs_client.get_customer_names()

    # 3. 필터링 (운영 고객사만)
    failures = [f for f in failures if f['customer_code'] in active_customers]
    logger.info(f"After filtering (env != 'dev'): {len(failures)} failures")

    # 4. 집계 (파일 레벨 그룹핑)
    logger.info("Step 3: Aggregating by file...")
    aggregator = FailureAggregator()
    aggregated = aggregator.aggregate_by_file(failures)

    # 5. 에러 분류 (규칙 기반)
    logger.info("Step 4: Classifying errors...")
    classifier = ErrorClassifier()
    for item in aggregated:
        item['error_type'] = classifier.classify(item['error_message'])

    # 6. 소스 타입별 그룹핑 (RPA/Board vs NonRPA)
    rpa_board_failures = [f for f in aggregated if f['source_type'] in ['rpa', 'board']]
    nonrpa_failures = [f for f in aggregated if f['source_type'] in ['pc', 'email', 'shared_drive']]

    # 7. Teams 메시지 생성
    logger.info("Step 5: Formatting Teams message...")
    formatter = TeamsFormatter(customer_names)
    message = formatter.create_message(
        target_date=target_date,
        rpa_board_failures=rpa_board_failures,
        nonrpa_failures=nonrpa_failures,
        total_count=len(failures)
    )

    # 8. Teams 전송
    logger.info("Step 6: Sending to Teams...")
    send_to_teams(message)

    logger.info("✅ Converter Failure Monitor Completed")


def send_to_teams(message):
    """Teams webhook으로 메시지 전송"""
    import requests

    payload = {"text": message}
    response = requests.post(WEBHOOK_URL, json=payload)

    if response.status_code == 200:
        logger.info("✅ Message sent to Teams successfully")
    else:
        logger.error(f"❌ Failed to send message: {response.status_code}")


def send_success_message(target_date):
    """실패 건이 없을 때 메시지"""
    message = f"""
📊 Converter 실패 리포트 - {target_date}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎉 실패 건이 없습니다!

전체: 모두 성공 ✅
"""
    send_to_teams(message)


if __name__ == "__main__":
    run_monitor()
```

---

#### 2. clients/bigquery_client.py

```python
# converter_failure_monitor/clients/bigquery_client.py

from google.cloud import bigquery
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class BigQueryClient:
    """BigQuery 조회 클라이언트"""

    def __init__(self, project_id):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id

    def get_failures(self, target_date):
        """
        특정 날짜의 실패 건 조회

        Returns:
            List[dict]: 실패 기록들
        """
        query = f"""
        SELECT
            customer_code,
            customer_name,
            source_type,
            source_id,
            convert_config_id,
            gcs_path,
            error_message,
            created_at,
            env
        FROM
            `{self.project_id}.dashboard.convert_job_history`
        WHERE
            DATE(created_at, 'Asia/Seoul') = '{target_date}'
            AND status = 'fail'
            AND env != 'dev'  -- 운영 환경만
        ORDER BY
            customer_code, source_type, gcs_path
        """

        logger.info(f"Querying BigQuery for date: {target_date}")

        try:
            query_job = self.client.query(query)
            results = query_job.result()

            failures = []
            for row in results:
                failures.append({
                    'customer_code': row.customer_code,
                    'customer_name': row.customer_name,
                    'source_type': row.source_type,
                    'source_id': row.source_id,
                    'convert_config_id': row.convert_config_id,
                    'gcs_path': row.gcs_path,
                    'error_message': row.error_message,
                    'created_at': row.created_at,
                    'env': row.env
                })

            return failures

        except Exception as e:
            logger.error(f"Error querying BigQuery: {e}")
            raise
```

---

#### 3. clients/firestore_client.py

```python
# converter_failure_monitor/clients/firestore_client.py

from google.cloud import firestore
import logging

logger = logging.getLogger(__name__)


class FirestoreClient:
    """Firestore 조회 클라이언트"""

    def __init__(self):
        self.db = firestore.Client()
        self.company_collection = self.db.collection("company").document("version").collection("v1.0")

    def get_active_customers(self):
        """
        운영 중인 고객사 코드 목록 (env != 'dev')

        Returns:
            Set[str]: 고객사 코드 집합
        """
        logger.info("Fetching active customers from Firestore...")

        active_customers = set()

        try:
            customer_docs = self.company_collection.list_documents()

            for customer_doc in customer_docs:
                customer_code = customer_doc.id

                # source_metas에서 env 확인
                source_metas_ref = customer_doc.collection("source_metas")
                for source_meta_doc in source_metas_ref.stream():
                    env = source_meta_doc.to_dict().get("env", "dev")

                    if env != "dev":  # ops, test 등 포함
                        active_customers.add(customer_code)
                        break  # 하나라도 발견되면 다음 고객사로

            logger.info(f"Found {len(active_customers)} active customers")
            return active_customers

        except Exception as e:
            logger.error(f"Error fetching active customers: {e}")
            raise

    def get_customer_names(self):
        """
        고객사 코드 → 이름 매핑

        Returns:
            Dict[str, str]: {customer_code: customer_name}
        """
        logger.info("Fetching customer names from Firestore...")

        customer_names = {}

        try:
            customer_docs = self.company_collection.stream()

            for customer_doc in customer_docs:
                customer_code = customer_doc.id
                customer_data = customer_doc.to_dict()
                customer_name = customer_data.get("name", "Unknown")
                customer_names[customer_code] = customer_name

            logger.info(f"Found {len(customer_names)} customer names")
            return customer_names

        except Exception as e:
            logger.error(f"Error fetching customer names: {e}")
            raise
```

---

#### 4. analyzer/classifier.py

```python
# converter_failure_monitor/analyzer/classifier.py

import re
import logging
from ..config.error_patterns import ERROR_PATTERNS

logger = logging.getLogger(__name__)


class ErrorClassifier:
    """에러 분류기 (규칙 기반)"""

    def __init__(self):
        self.patterns = ERROR_PATTERNS

    def classify(self, error_message):
        """
        에러 메시지를 분류

        Args:
            error_message (str): 에러 메시지

        Returns:
            str: 에러 유형 ("헤더 에러", "시트 에러", etc.)
        """
        if not error_message:
            return "기타"

        # 규칙 기반 매칭
        for error_type, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, error_message, re.IGNORECASE):
                    logger.debug(f"Classified as '{error_type}': {error_message[:100]}")
                    return error_type

        # 매칭 안 되면 "기타"
        logger.debug(f"Unclassified (기타): {error_message[:100]}")
        return "기타"
```

---

#### 5. analyzer/aggregator.py

```python
# converter_failure_monitor/analyzer/aggregator.py

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class FailureAggregator:
    """실패 건 집계"""

    def aggregate_by_file(self, failures):
        """
        파일 레벨로 그룹핑 (gcs_path 기준)

        하나의 파일이 여러 테이블 실패를 유발할 수 있으므로
        gcs_path를 기준으로 그룹핑

        Args:
            failures (List[dict]): 실패 기록들

        Returns:
            List[dict]: 파일 레벨로 집계된 결과
        """
        logger.info("Aggregating failures by file (gcs_path)...")

        # gcs_path를 키로 그룹핑
        grouped = defaultdict(lambda: {
            'customer_code': None,
            'customer_name': None,
            'source_type': None,
            'source_id': None,
            'gcs_path': None,
            'error_message': None,
            'failed_configs': [],
            'table_count': 0
        })

        for failure in failures:
            key = (
                failure['customer_code'],
                failure['source_type'],
                failure['gcs_path']
            )

            item = grouped[key]

            # 첫 번째 레코드로 기본 정보 설정
            if item['customer_code'] is None:
                item['customer_code'] = failure['customer_code']
                item['customer_name'] = failure['customer_name']
                item['source_type'] = failure['source_type']
                item['source_id'] = failure['source_id']
                item['gcs_path'] = failure['gcs_path']
                item['error_message'] = failure['error_message']  # 대표 에러

            # 실패한 config 추가
            if failure['convert_config_id'] not in item['failed_configs']:
                item['failed_configs'].append(failure['convert_config_id'])

            item['table_count'] += 1

        # 리스트로 변환
        result = list(grouped.values())

        logger.info(f"Aggregated {len(failures)} records into {len(result)} files")
        return result
```

---

#### 6. formatter/teams_formatter.py

```python
# converter_failure_monitor/formatter/teams_formatter.py

import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class TeamsFormatter:
    """Teams 메시지 포맷터"""

    def __init__(self, customer_names):
        """
        Args:
            customer_names (dict): {customer_code: customer_name}
        """
        self.customer_names = customer_names

    def create_message(self, target_date, rpa_board_failures, nonrpa_failures, total_count):
        """
        Teams 메시지 생성

        Args:
            target_date: 대상 날짜
            rpa_board_failures: RPA/Board 실패 목록
            nonrpa_failures: NonRPA 실패 목록
            total_count: 전체 실패 건수 (테이블 레벨)
        """
        # 헤더
        message = f"""
📊 Converter 실패 리포트 - {target_date}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
전체: {total_count}건 (테이블 레벨)
실패 파일: {len(rpa_board_failures) + len(nonrpa_failures)}개
"""

        # RPA/Board 섹션
        if rpa_board_failures:
            message += self._format_rpa_board_section(rpa_board_failures)
        else:
            message += "\n🔴 [RPA/Board] 실패 없음\n"

        # NonRPA 섹션
        if nonrpa_failures:
            message += self._format_nonrpa_section(nonrpa_failures)
        else:
            message += "\n⚠️ [NonRPA] 실패 없음\n"

        # 푸터
        message += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔗 상세 보기: [BigQuery] | [Grafana]
"""

        return message

    def _format_rpa_board_section(self, failures):
        """RPA/Board 섹션 포맷팅"""
        # 고객사별 그룹핑
        by_customer = defaultdict(list)
        for f in failures:
            by_customer[f['customer_code']].append(f)

        # 최대 10개 고객사만 표시
        MAX_CUSTOMERS = 10
        shown_customers = list(by_customer.keys())[:MAX_CUSTOMERS]

        message = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 [RPA/Board] 일별 수집 실패 - {len(shown_customers)}개 고객사
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        # 고객사별 출력
        for customer_code in shown_customers:
            customer_failures = by_customer[customer_code]
            customer_name = self.customer_names.get(customer_code, customer_code)

            # 에러 유형별 집계
            error_type_count = defaultdict(int)
            for f in customer_failures:
                error_type = f.get('error_type', '기타')
                error_type_count[error_type] += f['table_count']

            # 포맷팅
            error_summary = " | ".join([f"{k}: {v}건" for k, v in error_type_count.items()])

            message += f"{customer_name} [{customer_code}]\n"
            message += f"  파일: {len(customer_failures)}개, {error_summary}\n"

        # 나머지 고객사
        if len(by_customer) > MAX_CUSTOMERS:
            hidden_count = len(by_customer) - MAX_CUSTOMERS
            message += f"\n⚠️ 기타 {hidden_count}개 고객사 (BigQuery에서 확인)\n"

        return message

    def _format_nonrpa_section(self, failures):
        """NonRPA 섹션 포맷팅"""
        # 고객사별 그룹핑
        by_customer = defaultdict(list)
        for f in failures:
            by_customer[f['customer_code']].append(f)

        # 최대 10개 고객사만 표시
        MAX_CUSTOMERS = 10
        shown_customers = list(by_customer.keys())[:MAX_CUSTOMERS]

        message = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ [NonRPA] 고객사 업로드 실패 - {len(shown_customers)}개 고객사
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        # 고객사별 출력
        for customer_code in shown_customers:
            customer_failures = by_customer[customer_code]
            customer_name = self.customer_names.get(customer_code, customer_code)

            # 소스 타입별 그룹핑
            by_source_type = defaultdict(list)
            for f in customer_failures:
                by_source_type[f['source_type']].append(f)

            message += f"{customer_name} [{customer_code}]\n"
            for source_type, failures in by_source_type.items():
                message += f"  {source_type}: {len(failures)}개 파일\n"

        # 나머지 고객사
        if len(by_customer) > MAX_CUSTOMERS:
            hidden_count = len(by_customer) - MAX_CUSTOMERS
            message += f"\n⚠️ 기타 {hidden_count}개 고객사 (BigQuery에서 확인)\n"

        return message
```

---

#### 7. config/error_patterns.py

```python
# converter_failure_monitor/config/error_patterns.py

# 에러 분류 규칙 (정규식)
ERROR_PATTERNS = {
    "시트 에러": [
        r"not found matched sheet",
        r"Sheet .* not found",
        r"Worksheet .* does not exist",
        r"No sheet named",
    ],
    "헤더 에러": [
        r"row not found",
        r"Header .* not found",
        r"Cannot find header",
        r"Missing column",
        r"header_coordinate",
    ],
    "컬럼 범위 에러": [
        r"usecols.*out of bounds",
        r"invalid column range",
    ],
    "파일 손상": [
        r"corrupt",
        r"damaged",
        r"cannot.*read.*file",
        r"empty.*sheet",
    ],
    "Timeout": [
        r"[Tt]imeout",
        r"exceed.*time limit",
    ],
}
```

---

#### 8. config/constants.py

```python
# converter_failure_monitor/config/constants.py

import os

# GCP 프로젝트 ID
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "hyperlounge-dev")

# Teams Webhook URL
WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")

# BigQuery 테이블
BQ_TABLE = f"{PROJECT_ID}.dashboard.convert_job_history"

# Firestore 컬렉션 경로
FIRESTORE_COLLECTION = "company/version/v1.0"

# 로깅 레벨
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
```

---

#### 9. Dockerfile

```dockerfile
# converter_failure_monitor/Dockerfile

# airflow_dag_monitor와 동일한 패턴
FROM python:3.9-slim

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . /app/converter_failure_monitor/

# 실행
CMD ["python", "-m", "converter_failure_monitor.main"]
```

---

#### 10. requirements.txt

```
google-cloud-bigquery==3.11.0
google-cloud-firestore==2.11.0
requests==2.31.0
pytz==2023.3
```

---

#### 11. deploy.sh

```bash
#!/bin/bash
# converter_failure_monitor/deploy.sh

# airflow_dag_monitor/deploy.sh 참고

set -e

PROJECT_ID="hyperlounge-dev"
REGION="asia-northeast3"
JOB_NAME="converter-failure-monitor"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${JOB_NAME}"

echo "🚀 Deploying Converter Failure Monitor..."

# 1. Docker 이미지 빌드
echo "📦 Building Docker image..."
docker build -t ${IMAGE_NAME}:latest .

# 2. GCR에 푸시
echo "📤 Pushing to GCR..."
docker push ${IMAGE_NAME}:latest

# 3. Cloud Run Job 생성/업데이트
echo "☁️  Deploying to Cloud Run Job..."
gcloud run jobs deploy ${JOB_NAME} \
  --image=${IMAGE_NAME}:latest \
  --region=${REGION} \
  --project=${PROJECT_ID} \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID}" \
  --set-env-vars="TEAMS_WEBHOOK_URL=${TEAMS_WEBHOOK_URL}" \
  --memory=512Mi \
  --cpu=1 \
  --max-retries=0 \
  --task-timeout=10m

# 4. Cloud Scheduler 생성 (매일 아침 8시 KST)
echo "⏰ Setting up Cloud Scheduler..."
gcloud scheduler jobs create http ${JOB_NAME}-scheduler \
  --location=${REGION} \
  --schedule="0 8 * * *" \
  --time-zone="Asia/Seoul" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method=POST \
  --oauth-service-account-email="${PROJECT_ID}@appspot.gserviceaccount.com" \
  || echo "Scheduler already exists"

echo "✅ Deployment complete!"
```

---

### 배포 방식

#### 왜 Cloud Run Job인가?

**Cloud Function 대신 Cloud Run Job 선택 이유**:

1. **일관성** ✅
   - airflow_dag_monitor와 동일한 패턴
   - 기존 노하우 재사용
   - 유지보수 용이

2. **실행 시간** ✅
   - Cloud Function: 최대 9분
   - Cloud Run Job: 최대 60분
   - Converter 분석은 시간이 오래 걸릴 수 있음

3. **리소스** ✅
   - Cloud Function: 메모리 제한
   - Cloud Run Job: 유연한 리소스 할당

4. **디버깅** ✅
   - 로컬에서 Docker로 테스트 가능
   - 로그 확인 쉬움

**실행 흐름**:
```
Cloud Scheduler (매일 8시)
  ↓
Cloud Run Job 실행
  ↓
main.py 실행
  ↓
Teams 메시지 전송
  ↓
Job 종료
```

---

### 환경변수 관리

**필요한 환경변수**:
```bash
# deploy.sh에서 설정
GCP_PROJECT_ID=hyperlounge-dev
TEAMS_WEBHOOK_URL=https://...
LOG_LEVEL=INFO  # (선택)
```

**Secret Manager 사용** (권장):
```bash
# Webhook URL을 Secret으로 저장
gcloud secrets create teams-webhook-url --data-file=-

# Cloud Run Job에서 사용
gcloud run jobs deploy converter-failure-monitor \
  --set-secrets="TEAMS_WEBHOOK_URL=teams-webhook-url:latest"
```

---

### 로컬 테스트

```bash
# 1. Docker 빌드
docker build -t converter-failure-monitor .

# 2. 로컬 실행 (환경변수 주입)
docker run \
  -e GCP_PROJECT_ID=hyperlounge-dev \
  -e TEAMS_WEBHOOK_URL=https://... \
  -v ~/.config/gcloud:/root/.config/gcloud \
  converter-failure-monitor

# 3. Python 직접 실행 (개발 중)
export GCP_PROJECT_ID=hyperlounge-dev
export TEAMS_WEBHOOK_URL=https://...
python -m converter_failure_monitor.main
```

---

### 모니터링 및 로깅

**Cloud Logging 쿼리**:
```
resource.type="cloud_run_job"
resource.labels.job_name="converter-failure-monitor"
severity>=WARNING
```

**주요 로그**:
- ✅ 시작/종료 로그
- ✅ 각 단계별 진행 상황
- ✅ 에러 발생 시 상세 정보
- ✅ Teams 전송 성공/실패

**알림 설정** (선택):
```bash
# Job 실패 시 알림
gcloud logging metrics create converter-monitor-failures \
  --description="Converter monitor job failures" \
  --log-filter='resource.type="cloud_run_job"
    resource.labels.job_name="converter-failure-monitor"
    severity="ERROR"'
```

---

### Phase 2 확장 고려사항

**현재 아키텍처에서 쉽게 추가 가능**:

1. **Noise 필터링**
   - `analyzer/filter.py`에 추가
   - BigQuery에서 같은 날 성공률 조회

2. **LLM 에러 분석**
   - `analyzer/classifier.py`에 fallback 로직 추가
   - Vertex AI 또는 OpenAI API 호출

3. **DAG 상태 체크**
   - `clients/airflow_client.py` 추가
   - airflow_dag_monitor의 로직 재사용

4. **정책상 제외**
   - `config/error_patterns.py`에 규칙 추가
   - `analyzer/filter.py`에서 처리

**확장성 있는 구조**:
- 모듈화되어 있어 기능 추가 쉬움
- airflow_dag_monitor 패턴과 동일하여 학습 곡선 없음
- 테스트 가능한 구조

---
