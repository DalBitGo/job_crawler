# V2 마이그레이션 계획

> **상태**: 설계 검토 중
> **작성일**: 2026-02-06

---

## 1. 마이그레이션 전략

### 1.1 점진적 교체 (Strangler Fig Pattern)

```
Phase 1: V2 개발
         - 기존 코드 유지
         - V2 새로 작성
         - 테스트 환경에서 검증

Phase 2: 병렬 운영
         - 기존 + V2 둘 다 실행
         - 결과 비교 검증
         - 불일치 수정

Phase 3: V2 전환
         - Entry point를 V2로 변경
         - 기존 코드는 fallback으로 유지

Phase 4: 정리
         - 기존 코드 deprecated 표시
         - 일정 기간 후 제거
```

### 1.2 왜 점진적으로?

```
❌ Big Bang 교체의 위험:
- 실 운영 중인 시스템
- 다양한 config 조합
- 엣지 케이스 많음
- 롤백 어려움

✅ 점진적 교체의 장점:
- 기존 시스템 안정성 유지
- 문제 발견 시 빠른 롤백
- 결과 비교로 품질 검증
- 팀원 적응 시간 확보
```

---

## 2. Entry Point 분석

### 2.1 현재 Entry Points

```python
# 1. Cloud Function (converter/)
from collector.excel.file_converter import FileConverter
converter = FileConverter(...)
result = converter.convert()

# 2. Cloud Run Job (converter_job/)
from collector.excel.gcs_file_converter import GCSFileConverter
converter = GCSFileConverter(...)
result = converter.convert()

# 3. 로컬 테스트 (sample/)
from collector.excel.local_file_converter import LocalFileConverter
converter = LocalFileConverter(...)
result = converter.convert()
```

### 2.2 V2 Entry Point

```python
# V2 통합 entry point
from collector.excel.v2 import Pipeline, load_config

config = load_config(config_json)
pipeline = Pipeline(config, output_dir)
result = pipeline.run(file_path)
```

### 2.3 전환 계획

```python
# Step 1: Flag 기반 분기
USE_V2 = os.environ.get("USE_CONVERTER_V2", "false") == "true"

if USE_V2:
    from collector.excel.v2 import Pipeline, load_config
    config = load_config(config_json)
    pipeline = Pipeline(config, output_dir)
    result = pipeline.run(file_path)
else:
    from collector.excel.file_converter import FileConverter
    converter = FileConverter(...)
    result = converter.convert()

# Step 2: 점진적으로 V2 비율 증가
# - 특정 고객만 V2
# - 특정 source_type만 V2
# - 전체 V2

# Step 3: 기존 코드 제거
# if USE_V2: 분기 제거, V2만 유지
```

---

## 3. 결과 비교 검증

### 3.1 비교 항목

```python
@dataclass
class ComparisonResult:
    file_name: str
    sheet_name: str
    table_name: str

    # 기본 비교
    row_count_match: bool
    column_count_match: bool
    column_names_match: bool

    # 데이터 비교
    data_match: bool
    diff_cells: List[tuple]  # (row, col, v1, v2)

    # 메타데이터 비교
    meta_match: bool
```

### 3.2 비교 스크립트

```python
def compare_results(v1_path: Path, v2_path: Path) -> ComparisonResult:
    """V1과 V2 결과 비교"""

    # Parquet 로드
    df_v1 = pd.read_parquet(v1_path)
    df_v2 = pd.read_parquet(v2_path)

    result = ComparisonResult(...)

    # 기본 비교
    result.row_count_match = len(df_v1) == len(df_v2)
    result.column_count_match = len(df_v1.columns) == len(df_v2.columns)
    result.column_names_match = list(df_v1.columns) == list(df_v2.columns)

    # 데이터 비교
    if result.row_count_match and result.column_names_match:
        diff = df_v1.compare(df_v2)
        result.data_match = diff.empty
        if not diff.empty:
            result.diff_cells = extract_diff_cells(diff)

    return result
```

### 3.3 자동화 테스트

```python
# tests/test_v2_compatibility.py

import pytest
from collector.excel.v2 import Pipeline
from collector.excel.file_converter import FileConverter

TEST_CONFIGS = [
    ("c0159c00", "s9e99bb1", "erp_sa00_011"),
    ("c8cd3500", "s4da50eb", "board_config_001"),
    # ... 더 많은 config
]

@pytest.mark.parametrize("customer,source,config_id", TEST_CONFIGS)
def test_v2_compatibility(customer, source, config_id, test_file):
    """V1과 V2 결과가 동일한지 확인"""

    # V1 실행
    v1_result = run_v1(test_file, config)

    # V2 실행
    v2_result = run_v2(test_file, config)

    # 비교
    comparison = compare_results(v1_result, v2_result)

    assert comparison.row_count_match
    assert comparison.column_names_match
    assert comparison.data_match, f"Diff: {comparison.diff_cells}"
```

---

## 4. 롤백 계획

### 4.1 롤백 트리거

```
자동 롤백 조건:
- 에러율 > 5%
- 결과 불일치 > 1%
- 처리 시간 2x 이상 증가

수동 롤백:
- 심각한 버그 발견
- 다운스트림 영향 확인
```

### 4.2 롤백 방법

```bash
# 환경 변수로 즉시 롤백
export USE_CONVERTER_V2=false

# 또는 config에서 제어
{
  "converter_version": "v1"  // "v2"에서 "v1"로 변경
}
```

### 4.3 롤백 후 조치

```
1. 로그 분석 - 어떤 케이스에서 실패?
2. 재현 - 해당 config + 파일로 로컬 테스트
3. 수정 - V2 코드 수정
4. 검증 - 다시 비교 테스트
5. 재배포
```

---

## 5. 타임라인

### 5.1 Phase 1: 개발 (예상)

```
Week 1-2: 핵심 모듈 구현
  - [ ] config/schema.py (Pydantic 모델)
  - [ ] loader/excel_loader.py
  - [ ] parser/expression.py (최적화 포함)

Week 3-4: 통합 및 테스트
  - [ ] parser/table_parser.py
  - [ ] writer/table_writer.py
  - [ ] pipeline.py
  - [ ] 단위 테스트
```

### 5.2 Phase 2: 검증

```
Week 5-6: 호환성 테스트
  - [ ] 기존 config 샘플로 비교 테스트
  - [ ] 엣지 케이스 수집 및 수정
  - [ ] 성능 벤치마크
```

### 5.3 Phase 3: 배포

```
Week 7: 스테이징 배포
  - [ ] 특정 고객만 V2 활성화
  - [ ] 모니터링

Week 8: 프로덕션 배포
  - [ ] 점진적 롤아웃
  - [ ] 전체 전환
```

---

## 6. 체크리스트

### 6.1 개발 완료 기준

```
[ ] 모든 단위 테스트 통과
[ ] 기존 config 100% 파싱 가능
[ ] 샘플 파일 변환 결과 일치
[ ] 성능 벤치마크 통과 (기존 대비 동등 이상)
[ ] 코드 리뷰 완료
```

### 6.2 배포 전 체크리스트

```
[ ] 스테이징에서 72시간 무장애 운영
[ ] 결과 비교 테스트 100% 통과
[ ] 롤백 절차 검증
[ ] 모니터링 대시보드 준비
[ ] 팀 공유 및 교육
```

### 6.3 배포 후 체크리스트

```
[ ] 에러율 모니터링
[ ] 처리 시간 모니터링
[ ] 사용자 피드백 수집
[ ] 기존 코드 deprecated 표시
```

---

## 7. 위험 요소 및 대응

| 위험 | 가능성 | 영향 | 대응 |
|------|--------|------|------|
| Config 파싱 실패 | 중 | 높 | extra="allow"로 느슨하게 |
| 결과 불일치 | 중 | 높 | 비교 테스트 자동화 |
| 성능 저하 | 낮 | 중 | 벤치마크 후 배포 |
| 롤백 실패 | 낮 | 높 | 롤백 절차 사전 테스트 |

---

## 8. 다음 단계

1. [ ] 문서 검토 완료
2. [ ] 결정 필요 사항 논의
3. [ ] Phase 1 구현 시작
