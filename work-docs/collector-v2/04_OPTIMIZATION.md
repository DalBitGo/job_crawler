# V2 성능 최적화

> **상태**: 설계 검토 중
> **작성일**: 2026-02-06

---

## 1. 현재 성능 문제점

### 1.1 식별된 병목

| 위치 | 문제 | 영향 |
|------|------|------|
| `excel_converter.py:770` | `iteritems()` 사용 | 대용량 데이터 느림 |
| `excel_converter.py:303-408` | 매번 regex 컴파일 | CPU 낭비 |
| `table_writer.py` | CSV + Parquet 이중 출력 | I/O 2배 |
| `file_converter.py` | 시트 순차 처리 | 멀티코어 미활용 |

### 1.2 현재 코드 예시

```python
# 문제 1: iteritems (pandas 2.x에서 제거됨)
for idx, value in col_data.iteritems():
    if p.search(str(value)):
        return idx

# 문제 2: 매번 regex 컴파일
def find_start_row_index(self, ...):
    p = re.compile(row_expr)  # 매 호출마다 컴파일!
    for idx, value in col_data.iteritems():
        if p.search(str(value)):
            ...

# 문제 3: CSV + Parquet 둘 다 출력
df.to_csv(csv_path)      # 느림
df.to_parquet(pq_path)   # 빠름, 이것만 필요
```

---

## 2. 최적화 전략

### 2.1 O1: Regex 캐싱

**현재:**
```python
def find_row(self, expr):
    p = re.compile(expr)  # 매번 컴파일
    ...
```

**개선:**
```python
class ExpressionEvaluator:
    def __init__(self):
        self._cache: Dict[str, re.Pattern] = {}

    def _get_pattern(self, expr: str) -> re.Pattern:
        if expr not in self._cache:
            self._cache[expr] = re.compile(expr)
        return self._cache[expr]

    def find_row(self, expr):
        p = self._get_pattern(expr)  # 캐시 사용
        ...
```

**예상 효과:** 같은 패턴 반복 사용 시 30-50% 개선

---

### 2.2 O2: Vectorized 연산

**현재 (iterrows/iteritems):**
```python
# O(n) Python 루프 - 느림
for idx, value in col_data.iteritems():
    if p.search(str(value)):
        return idx
```

**개선 (vectorized):**
```python
# pandas 내부 C 구현 - 빠름
def find_row_vectorized(self, df, column, pattern):
    col_idx = self._col_to_idx(column)
    col_data = df.iloc[:, col_idx].astype(str)

    # str.contains는 내부적으로 vectorized
    matches = col_data.str.contains(pattern, regex=True, na=False)

    # 첫 번째 True 인덱스
    match_indices = matches[matches].index
    if len(match_indices) > 0:
        return match_indices[0]
    return None
```

**예상 효과:** 50-70% 개선 (특히 대용량 데이터)

---

### 2.3 O3: CSV 출력 제거

**현재:**
```python
# table_writer.py
df.to_csv(csv_path)      # 1. CSV (느림, 레거시)
df.to_parquet(pq_path)   # 2. Parquet (빠름)
# 같은 데이터를 2번 씀
```

**개선:**
```python
# Parquet만 출력
df.to_parquet(pq_path, compression='zstd')

# CSV 필요시 별도 변환 (lazy)
# csv_converter.py (필요할 때만)
```

**예상 효과:** I/O 50% 감소, GCS 비용 절감

---

### 2.4 O4: 청크 처리 개선

**현재:**
```python
# 1000행마다 체크, 50MB 초과시 분할
if row_idx % 1000 == 0 and get_size(out_tables) > 50MB:
    yield chunk
```

**개선:**
```python
# 고정 청크 사이즈로 스트리밍
CHUNK_SIZE = 100_000  # 행 단위

for chunk in pd.read_excel(file, chunksize=CHUNK_SIZE):
    process_chunk(chunk)
    write_chunk(chunk)

# 또는 pyarrow 직접 사용
import pyarrow.parquet as pq
writer = pq.ParquetWriter(path, schema)
for chunk in chunks:
    writer.write_table(pa.Table.from_pandas(chunk))
writer.close()
```

**예상 효과:** 메모리 사용량 안정화, 대용량 파일 처리 가능

---

### 2.5 O5: 시트 병렬 처리

**현재:**
```python
# 순차 처리
for sheet in sheets:
    process_sheet(sheet)  # 하나씩
```

**개선:**
```python
from concurrent.futures import ThreadPoolExecutor

# 병렬 처리 (I/O bound이므로 Thread 적합)
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(process_sheet, s) for s in sheets]
    results = [f.result() for f in futures]
```

**예상 효과:** 멀티 시트 파일에서 2-4x 향상

**주의:**
- 메모리 사용량 증가
- 에러 핸들링 복잡
- 로깅 순서 뒤섞임

---

## 3. 구현 우선순위

| 순위 | 최적화 | 난이도 | 효과 | 리스크 |
|------|--------|--------|------|--------|
| 1 | O3: CSV 제거 | 낮음 | 높음 | 낮음 |
| 2 | O1: Regex 캐싱 | 낮음 | 중간 | 낮음 |
| 3 | O2: Vectorized | 중간 | 높음 | 중간 |
| 4 | O4: 청크 처리 | 중간 | 중간 | 중간 |
| 5 | O5: 병렬 처리 | 높음 | 높음 | 높음 |

---

## 4. 벤치마크 계획

### 4.1 테스트 데이터셋

```
Small:  1,000 rows × 20 cols  (~50KB)
Medium: 50,000 rows × 50 cols (~10MB)
Large:  500,000 rows × 100 cols (~200MB)
```

### 4.2 측정 항목

```python
import time
import tracemalloc

# 시간 측정
start = time.perf_counter()
result = convert(file)
elapsed = time.perf_counter() - start

# 메모리 측정
tracemalloc.start()
result = convert(file)
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()

print(f"Time: {elapsed:.2f}s")
print(f"Memory: current={current/1e6:.1f}MB, peak={peak/1e6:.1f}MB")
```

### 4.3 비교 대상

```
| 버전 | Small | Medium | Large |
|------|-------|--------|-------|
| 기존 |   ?s  |    ?s  |    ?s |
| V2   |   ?s  |    ?s  |    ?s |
```

---

## 5. V2에서의 적용

### 5.1 ExpressionEvaluator (O1 + O2 적용)

```python
class ExpressionEvaluator:
    """
    최적화 적용:
    - O1: Regex 캐싱
    - O2: Vectorized 연산
    """

    def __init__(self):
        self._pattern_cache: Dict[str, re.Pattern] = {}

    def _get_pattern(self, expr: str) -> re.Pattern:
        """O1: 캐싱"""
        if expr not in self._pattern_cache:
            self._pattern_cache[expr] = re.compile(expr)
        return self._pattern_cache[expr]

    def find_row(
        self,
        df: pd.DataFrame,
        column: Union[str, int],
        pattern: str,
        match_nth: int = 1
    ) -> Optional[int]:
        """O2: Vectorized"""
        compiled = self._get_pattern(pattern)

        # 컬럼 인덱스 변환
        if isinstance(column, str):
            col_idx = ord(column.upper()) - ord('A')
        else:
            col_idx = column

        # vectorized 검색
        col_data = df.iloc[:, col_idx].astype(str)
        matches = col_data.str.contains(compiled, na=False)

        match_indices = matches[matches].index.tolist()
        if len(match_indices) >= match_nth:
            return match_indices[match_nth - 1]

        return None
```

### 5.2 TableWriter (O3 적용)

```python
class TableWriter:
    """
    최적화 적용:
    - O3: Parquet만 출력 (CSV 제거)
    """

    def write(self, df: pd.DataFrame, name: str) -> Path:
        output_path = self.output_dir / f"{name}.parquet"

        # Parquet만 출력 (zstd 압축)
        df.to_parquet(
            output_path,
            compression='zstd',
            index=False
        )

        return output_path

    # CSV 필요시 별도 메서드
    def write_csv_legacy(self, df: pd.DataFrame, name: str) -> Path:
        """레거시 호환용 (필요시만 호출)"""
        output_path = self.output_dir / f"{name}.csv"
        df.to_csv(output_path, index=False)
        return output_path
```

---

## 6. 검토 필요 사항

### 6.1 CSV 제거 영향

```
[ ] 기존에 CSV를 읽는 downstream 코드가 있는지?
[ ] BigQuery external table이 CSV를 참조하는지?
[ ] 있다면 마이그레이션 계획 필요
```

### 6.2 병렬 처리 도입 여부

```
[ ] 멀티 시트 파일이 얼마나 많은지?
[ ] 메모리 제약이 있는 환경인지?
[ ] 복잡성 증가 대비 효과가 있는지?

→ Phase 2에서 검토
```

---

## 7. 다음 단계

1. [ ] 벤치마크 환경 구축
2. [ ] 기존 코드 baseline 측정
3. [ ] V2 구현하면서 최적화 적용
4. [ ] Before/After 비교
