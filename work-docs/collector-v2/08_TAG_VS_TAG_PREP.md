# Tag vs Tag Prep 구조 분석

> **작성일**: 2026-02-11
> **상태**: 분석 완료

---

## 1. 전체 파이프라인

```
Excel 파일
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  CONVERT                                                         │
│  - 원본 테이블 → unpivot → TBL_DATA, TBL_META                    │
│  - HNDL_STEP_CD = "CVT"                                          │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  TAGGER                                                          │
│  - 태그 구조 생성 (원시값 그대로)                                  │
│  - TAG_TBL, TAG_CLMN, TAG_ROW 저장                               │
│  - HNDL_STEP_CD = "TAG"                                          │
│  - 파일명: {cvt_meta_id}.csv                                      │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  TAG_PREP                                                        │
│  - Tagger 결과를 읽어서 값 정규화                                 │
│  - 같은 테이블에 정규화된 값으로 다시 저장                         │
│  - HNDL_STEP_CD = "PREP"                                         │
│  - 파일명: prep_{cvt_meta_id}.csv                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Tagger vs Tag Prep 비교

### 2.1 역할 차이

| | Tagger | Tag Prep |
|---|---|---|
| **역할** | 태그 구조 생성 | 값 정규화 (후처리) |
| **입력** | Convert 결과 (DataFrame) | Tagger 출력 (CSV) |
| **출력** | 원시값 CSV | 정규화된 CSV |
| **HNDL_STEP_CD** | `"TAG"` | `"PREP"` |
| **파일명** | `{cvt_meta_id}.csv` | `prep_{cvt_meta_id}.csv` |

### 2.2 값 변환 예시

| 원시값 (Tagger) | 정규화 (Tag Prep) | 변환 내용 |
|-----------------|-------------------|-----------|
| `"20211001"` | `"2021-10-01"` | 날짜 포맷 통일 |
| `"1,234,567"` | `"1234567"` | 콤마 제거 |
| `"100"` (단위:백만) | `"100000000"` | 스케일링 |
| `"2021Q1"` | `"2021-03-31"` | 분기 → 날짜 |

### 2.3 GCS 저장 구조

```
gs://{bucket}/ext/EXT_TAG_ROW/BSDA=2024-01-01/CVT_META_ID={id}/
├── {cvt_meta_id}.csv           ← Tagger가 씀 (HNDL_STEP_CD = "TAG")
└── prep_{cvt_meta_id}.csv      ← Tag Prep이 씀 (HNDL_STEP_CD = "PREP")
```

BigQuery external table에서는 둘 다 읽혀서, `WHERE HNDL_STEP_CD = 'PREP'`로 필터링해서 사용.

---

## 3. Tagger 내부 구조

### 3.1 파일 구성

```
collector/excel/
├── tag.py           # 상수/모델 정의
├── tagger.py        # 오케스트레이션
├── tag_compiler.py  # Config 전처리
├── tag_builder.py   # 태그 생성 (핵심, 병목점)
└── tag_writer.py    # CSV 출력
```

### 3.2 각 파일 역할

| 파일 | 라인수 | 역할 |
|------|--------|------|
| `tag.py` | ~240 | 상수 클래스 (TagNamespace, TagCategory 등), Tag 데이터 모델 |
| `tagger.py` | ~416 | 전체 오케스트레이션, VDL에서 데이터 로드, auto_scan 처리 |
| `tag_compiler.py` | ~192 | 태깅 config의 column expression을 미리 평가 (`expr` → `computed`) |
| `tag_builder.py` | ~1100 | **핵심** - 실제 태그 트리 생성, `iterrows()` 병목점 |
| `tag_writer.py` | ~232 | 태그 트리를 CSV로 저장 (TAG_TBL, TAG_CLMN, TAG_ROW) |

### 3.3 호출 관계

```
Tagger.run()
    │
    ├── load_tables()  ← VDL에서 데이터 로드 (또는 Convert 결과 직접 사용)
    │
    └── TagBuilder.build()
            │
            ├── TagCompiler.compile_table_conf()  ← config 전처리
            │
            ├── build_row_nodes()  ← ⚠️ iterrows() 병목점
            │       │
            │       └── for row in df.iterrows():
            │               make_row_tags()
            │               is_matched_row_by_row_key()  ← regex 반복
            │
            └── TagWriter.flush_tags()  ← CSV 저장
```

---

## 4. Tag Prep 내부 구조

### 4.1 파일 위치

```
mdm/tag_mapping/
├── main.py              # Entry point (Cloud Function)
├── normalizer.py        # 값 정규화
├── date_extractor.py    # 날짜 추출
├── manual_normalizer.py # 고객별 커스텀 정규화
├── manual_data_prep.py  # 고객별 커스텀 데이터 처리
├── type_replacer.py     # 타입 힌트
├── type_validator.py    # 타입 검증
└── data_writer.py       # 최종 CSV 저장
```

### 4.2 처리 순서 (Processor Chain)

```python
processors = [
    TypeReplacer,      # 1. type hint 제공
    DateExtractor,     # 2. wrap_date 추출
    ManualNormalizer,  # 3. 고객별 ad-hoc 태그 정규화
    ManualDataPrep,    # 4. 고객별 ad-hoc 데이터 처리
    TypeValidator,     # 5. 타입 유효성 검증
    Normalizer,        # 6. 값 정규화 (날짜, 숫자 등)
    DataWriter         # 7. 최종 GCS 저장
]
```

---

## 5. 왜 분리되어 있나?

### 5.1 역사적 이유 (추정)

1. Tagger는 Convert와 함께 실행 가능 (`inplace_tag` 옵션)
2. Tag Prep은 나중에 추가된 후처리 단계
3. 고객별 정규화 룰이 복잡해서 별도 Cloud Function으로 분리

### 5.2 현재 구조의 문제점

| 문제 | 설명 |
|------|------|
| 데이터 2번 저장 | 같은 테이블에 TAG, PREP 두 번 저장 |
| I/O 비효율 | Tagger → GCS → Tag Prep → GCS |
| 복잡한 의존성 | Airflow에서 3단계 호출 필요 |

### 5.3 개선 가능성

```
현재: Convert → Tagger(저장) → Tag Prep(읽고 저장)

개선안: Convert → Tagger+정규화(저장) → 끝
        └── 정규화 로직을 Tagger에 통합
```

다만, 고객별 `ManualNormalizer`, `ManualDataPrep` 로직이 복잡해서
단순 통합은 어려울 수 있음. 점진적 통합 검토 필요.

---

## 6. 관련 문서

| 문서 | 내용 |
|------|------|
| [04_OPTIMIZATION.md](./04_OPTIMIZATION.md) | 성능 최적화 포인트 |
| [06_OUTPUT_FORMAT_ISSUES.md](./06_OUTPUT_FORMAT_ISSUES.md) | 5개 테이블 구조 분석 |
| [CONVERTER_TAGGER_OPTIMIZATION.md](/docs/architecture/CONVERTER_TAGGER_OPTIMIZATION.md) | 전체 최적화 계획 |
