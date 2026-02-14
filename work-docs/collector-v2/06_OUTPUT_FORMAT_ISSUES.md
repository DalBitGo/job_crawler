# V2 출력 포맷 이슈 및 개선 방향

> **상태**: 분석 완료
> **작성일**: 2026-02-08
> **관련 문서**: [TAGGING_CONFIG_GUIDE.md](../../docs/TAGGING_CONFIG_GUIDE.md)

---

## 1. 현재 출력 포맷 구조

### 1.1 5개 테이블 구조

```
Convert 결과 (2개):
├── CVT_TBL_META    - 테이블 메타정보
└── CVT_TBL_DATA    - 셀 데이터 (unpivot)

Tagging 결과 (3개):
├── TAG_TBL         - 테이블 레벨 태그
├── TAG_CLMN        - 컬럼 표준화 (원본→표준KEY)
└── TAG_ROW         - index 컬럼 값 저장
```

### 1.2 테이블 간 관계

```
TBL_DATA ──── TBL_ROW_NO ────→ TAG_ROW
    │                            │
    │                            │
    └──── TBL_CLMN_NM ────→ TAG_CLMN
```

---

## 2. 핵심 문제점

### 2.1 쿼리 복잡성

**"담당코드별 처방금액 합계"를 구하려면:**

```sql
-- JOIN 2~3번 필요!
SELECT
    r.TAG_NM AS contact_code,
    SUM(CAST(d.TBL_VL AS FLOAT64)) AS total_amount
FROM TAG_ROW r
JOIN TBL_DATA d ON r.TBL_ROW_NO = d.TBL_ROW_NO      -- JOIN 1
JOIN TAG_CLMN c ON d.TBL_CLMN_NM = c.TBL_CLMN_NM   -- JOIN 2
WHERE r.TAG_KEY = 'contact_code'
  AND c.TAG_KEY = 'sales_amount'
GROUP BY r.TAG_NM;
```

### 2.2 학습 곡선

| 이해해야 할 것 | 설명 |
|--------------|------|
| TBL_DATA 구조 | 셀 단위 unpivot (Long format) |
| TAG_ROW 구조 | index 컬럼만 저장, measure 없음 |
| TAG_CLMN 구조 | 컬럼명 → 표준KEY 매핑 |
| TBL_ROW_NO 역할 | JOIN 키 (행 식별자) |
| Dimension vs Measure | index vs value 컬럼 구분 |

### 2.3 명명 규칙 불일치

```
TBL_DATA:  TBL_VL    (Table Value)     ← 값이니까 VL
TAG_ROW:   TAG_NM    (Tag Name)        ← 근데 여기도 값인데 NM?

→ TAG_VL이 더 적절했을 것
```

### 2.4 정규화 vs 현대 트렌드

| | 현재 (정규화) | 현대 빅데이터 |
|---|---|---|
| 철학 | 중복 제거 | JOIN 줄이기 |
| 저장 비용 | 옛날: 비쌈 | 지금: 저렴 |
| 쿼리 | 복잡 | 단순 선호 |
| 권장 | - | **비정규화** |

---

## 3. 구체적 이슈

### 3.1 TAG_ROW에는 Measure가 없음

```
원본:
├── 팀코드 (index)     → TAG_ROW에 있음
├── 담당코드 (index)   → TAG_ROW에 있음
├── 처방수량 (measure) → TAG_ROW에 없음!
└── 처방금액 (measure) → TAG_ROW에 없음!

→ Measure 값 보려면 TBL_DATA JOIN 필수
```

### 3.2 원본 컬럼명은 TAG_ROW에 없음

```
TAG_ROW:
┌─────────────────────────┬────────┐
│ TAG_KEY                 │ TAG_NM │
├─────────────────────────┼────────┤
│ organization_code       │ A71    │  ← 원본 "팀코드" 어디?
└─────────────────────────┴────────┘

→ 원본 컬럼명 보려면 TAG_CLMN JOIN 필요
```

### 3.3 표준KEY로 Measure 검색하려면 추가 JOIN

```sql
-- 원본 컬럼명으로 검색 (JOIN 1개)
WHERE d.TBL_CLMN_NM = '처방금액'

-- 표준KEY로 검색 (JOIN 2개)
JOIN TAG_CLMN c ON d.TBL_CLMN_NM = c.TBL_CLMN_NM
WHERE c.TAG_KEY = 'sales_amount'
```

---

## 4. V2 개선 옵션

### 4.1 Option A: 기존 포맷 유지 (보수적)

```
장점: 기존 시스템 호환성 100%
단점: 복잡성 그대로 유지
권장: 단기적으로는 이 방식
```

### 4.2 Option B: TBL_DATA 확장

```
TBL_DATA에 컬럼 추가:
┌────────────┬────────────┬─────────────────────┬────────┬──────────┐
│ TBL_ROW_NO │ TBL_CLMN_NM│ STD_KEY             │ TBL_VL │ IS_INDEX │
├────────────┼────────────┼─────────────────────┼────────┼──────────┤
│     1      │ 팀코드      │ organization_code   │ A71    │ true     │
│     1      │ 처방금액    │ sales_amount        │ -40502 │ false    │
└────────────┴────────────┴─────────────────────┴────────┴──────────┘

장점: JOIN 없이 바로 검색 가능
단점: 중복 저장 (비정규화)
권장: 장기적으로 검토
```

### 4.3 Option C: 통합 테이블 추가

```
기존 5개 테이블 유지 + 통합 뷰/테이블 추가

ALL_DATA (통합):
├── 기존 테이블들 JOIN한 결과를 materialized view로
├── 쿼리 시 이 테이블만 사용
└── 기존 시스템 호환성 유지하면서 편의성 제공

장점: 호환성 + 편의성 둘 다
단점: 저장 공간 증가
권장: 중기적으로 검토
```

---

## 5. 구현 우선순위

| 순위 | 개선 사항 | 난이도 | 효과 | 호환성 |
|------|----------|--------|------|--------|
| 1 | 문서화 (완료) | 낮음 | 중간 | 100% |
| 2 | 코드 리팩토링 | 중간 | 높음 | 100% |
| 3 | 통합 뷰 추가 | 중간 | 높음 | 100% |
| 4 | TBL_DATA 확장 | 높음 | 높음 | 90% |
| 5 | 전체 재설계 | 매우높음 | 매우높음 | 0% |

---

## 6. 권장 전략

### Phase 1: 기존 포맷 유지 + 문서화 (현재)
```
✓ TAGGING_CONFIG_GUIDE.md 작성 완료
✓ OUTPUT_FILES_GUIDE.md 작성 완료
→ 학습 곡선 낮추기
```

### Phase 2: 코드 리팩토링
```
- 출력 포맷은 그대로
- 내부 코드만 개선 (V2 본 목표)
- 테스트 용이성 확보
```

### Phase 3: 통합 뷰 검토 (선택)
```
- 기존 테이블 유지
- 편의용 통합 뷰 추가
- 쿼리 단순화
```

---

## 7. 결론

**현재 상태:**
- 5개 테이블 구조는 과도한 정규화
- JOIN 복잡성이 사용성 저해
- 현대 빅데이터 트렌드와 맞지 않음

**V2 접근:**
- 출력 포맷 변경은 리스크 높음
- 우선 코드 리팩토링에 집중
- 통합 뷰는 필요시 추가 검토

**핵심:**
```
"기존 호환성 유지하면서 내부 코드만 개선"
"출력 포맷 변경은 별도 프로젝트로"
```

---

## 8. 관련 문서

| 문서 | 내용 |
|------|------|
| [01_OVERVIEW.md](./01_OVERVIEW.md) | V2 전체 개요 |
| [TAGGING_CONFIG_GUIDE.md](../../docs/TAGGING_CONFIG_GUIDE.md) | 현재 태깅 구조 상세 |
| [OUTPUT_FILES_GUIDE.md](../../docs/OUTPUT_FILES_GUIDE.md) | 5개 출력 파일 가이드 |
