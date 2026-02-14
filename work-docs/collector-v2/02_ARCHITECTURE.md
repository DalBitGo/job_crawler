# V2 아키텍처 설계

> **상태**: 설계 검토 중
> **작성일**: 2026-02-06

---

## 1. 현재 vs 목표

### 1.1 현재 구조 (문제점)

```
FileConverter (God Class - 536줄)
│
├── 책임 1: 파일 로드 (I/O)
├── 책임 2: 시트 필터링 (라우팅)
├── 책임 3: Config 적용 (설정)
├── 책임 4: ExcelConverter 호출 (변환)
├── 책임 5: Tagger 호출 (태깅)
├── 책임 6: 결과 저장 (출력)
└── 책임 7: 에러 리포팅 (로깅)

ExcelConverter (800줄)
│
├── read_excel()           # 200줄 - 너무 김
├── find_start_row_index() # regex 매칭
├── make_header_df()       # 헤더 처리
├── make_body_df()         # 본문 처리
├── transform()            # Transformer 호출
├── data_prep()            # DataPrep 호출
└── normalize()            # TypeConverter 호출

문제:
- 한 클래스가 너무 많은 일을 함
- 메서드가 길고 복잡
- 테스트하려면 전체를 다 셋업해야 함
```

### 1.2 목표 구조 (책임 분리)

```
┌─────────────────────────────────────────────────────────────────┐
│                        Pipeline                                  │
│                    (오케스트레이션만)                             │
└───────────┬─────────────────┬─────────────────┬─────────────────┘
            │                 │                 │
            ▼                 ▼                 ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  ExcelLoader  │    │  TableParser  │    │  TableWriter  │
│   (I/O만)     │    │   (변환만)    │    │   (출력만)    │
└───────────────┘    └───────┬───────┘    └───────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌───────────┐  ┌───────────┐  ┌───────────┐
       │Expression │  │HeaderProc │  │TypeConvert│
       │ Evaluator │  │  essor    │  │    er     │
       └───────────┘  └───────────┘  └───────────┘
```

---

## 2. 모듈별 설계

### 2.1 Pipeline (오케스트레이션)

```python
class Pipeline:
    """
    책임: 전체 흐름 조율
    - Loader, Parser, Writer 연결
    - 시트/테이블 반복
    - 에러 수집 및 결과 집계

    하지 않는 것:
    - 실제 파싱 로직
    - 파일 I/O
    - 데이터 변환
    """

    def __init__(self, config: ConvertConfig, output_dir: Path):
        self.config = config
        self.loader = ExcelLoader()
        self.writer = TableWriter(output_dir)

    def run(self, file_path: str) -> PipelineResult:
        results = []

        # 1. 파일 로드
        workbook = self.loader.load(file_path)

        # 2. 시트 반복
        for sheet_name in self.loader.filter_sheets(self.config.sheet_pattern):
            sheet_df = self.loader.read_sheet(sheet_name)

            # 3. 테이블 반복
            for table_name, table_config in self.config.get_tables(sheet_name):
                try:
                    # 4. 파싱
                    parser = TableParser(table_config)
                    parsed_df = parser.parse(sheet_df)

                    # 5. 출력
                    output_path = self.writer.write(parsed_df, table_name)

                    results.append(ConvertResult(
                        status="success",
                        sheet=sheet_name,
                        table=table_name,
                        output=output_path
                    ))
                except Exception as e:
                    results.append(ConvertResult(
                        status="fail",
                        sheet=sheet_name,
                        table=table_name,
                        error=str(e)
                    ))

        return PipelineResult(results)
```

### 2.2 ExcelLoader (I/O)

```python
class ExcelLoader:
    """
    책임: 파일 읽기만
    - 파일 열기 (로컬/GCS)
    - 시트 목록 조회
    - 시트를 raw DataFrame으로 반환

    하지 않는 것:
    - 헤더 처리
    - 데이터 변환
    - Config 해석
    """

    def __init__(self, engine: str = "auto"):
        self.engine = engine  # openpyxl, xlrd, auto
        self._workbook = None

    def load(self, file_path: str) -> "ExcelLoader":
        """파일 열기"""
        # 커스텀 openpyxl 사용 (sheet_name 파라미터 지원)
        pass

    def get_sheet_names(self) -> List[str]:
        """전체 시트 목록"""
        pass

    def filter_sheets(self, pattern: str) -> List[str]:
        """패턴과 매칭되는 시트만"""
        pass

    def read_sheet(self, sheet_name: str) -> pd.DataFrame:
        """
        시트를 raw DataFrame으로 반환
        - header=None (헤더 처리 안 함)
        - 모든 셀을 그대로 읽음
        """
        pass
```

### 2.3 TableParser (변환)

```python
class TableParser:
    """
    책임: 테이블 파싱
    - 시작/종료 행 찾기
    - 헤더 추출
    - 본문 추출
    - 타입 변환

    하지 않는 것:
    - 파일 I/O
    - 결과 저장
    """

    def __init__(self, config: TableConfig):
        self.config = config
        self.expr_eval = ExpressionEvaluator()

    def parse(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        """
        raw DataFrame → 정제된 DataFrame

        Steps:
        1. 시작 행 찾기
        2. 헤더 추출
        3. 종료 행 찾기
        4. 본문 추출
        5. 컬럼 필터링
        6. 타입 변환
        """
        # 1. 시작 행
        start_row = self._find_start_row(raw_df)

        # 2. 헤더
        header = self._extract_header(raw_df, start_row)

        # 3. 종료 행
        end_row = self._find_end_row(raw_df, start_row)

        # 4. 본문 추출
        body_df = raw_df.iloc[start_row + 1:end_row].copy()
        body_df.columns = header

        # 5. 컬럼 필터링
        body_df = self._filter_columns(body_df)

        # 6. 타입 변환
        body_df = self._convert_types(body_df)

        return body_df

    def _find_start_row(self, df: pd.DataFrame) -> int:
        """표현식으로 시작 행 찾기"""
        if isinstance(self.config.rows_start, int):
            return self.config.rows_start

        return self.expr_eval.find_row(
            df,
            column=self.config.rows_start.header_coordinate,
            pattern=self.config.rows_start.expr,
            match_nth=self.config.rows_start.match
        )
```

### 2.4 ExpressionEvaluator (표현식)

```python
class ExpressionEvaluator:
    """
    책임: 표현식 평가
    - Regex 패턴 매칭
    - 행/열 검색

    최적화:
    - 패턴 캐싱 (한 번 컴파일, 재사용)
    """

    def __init__(self):
        self._pattern_cache: Dict[str, re.Pattern] = {}

    def _get_pattern(self, expr: str) -> re.Pattern:
        """캐싱된 패턴 반환"""
        if expr not in self._pattern_cache:
            self._pattern_cache[expr] = re.compile(expr)
        return self._pattern_cache[expr]

    def find_row(
        self,
        df: pd.DataFrame,
        column: str,
        pattern: str,
        match_nth: int = 1,
        start_from: int = 0
    ) -> Optional[int]:
        """
        패턴과 매칭되는 N번째 행 찾기

        최적화: vectorized str.contains 사용
        """
        compiled = self._get_pattern(pattern)
        col_idx = self._col_to_idx(column)

        # vectorized 방식 (iterrows 대신)
        matches = df.iloc[start_from:, col_idx].astype(str).str.contains(
            compiled, na=False
        )
        match_indices = matches[matches].index.tolist()

        if len(match_indices) >= match_nth:
            return match_indices[match_nth - 1]
        return None
```

### 2.5 TableWriter (출력)

```python
class TableWriter:
    """
    책임: 결과 저장
    - Parquet 출력
    - 메타데이터 JSON
    - 청크 분할 (대용량)

    하지 않는 것:
    - CSV 출력 (deprecated)
    - 태깅
    """

    def __init__(self, output_dir: Path, chunk_size_mb: int = 50):
        self.output_dir = output_dir
        self.chunk_size_mb = chunk_size_mb

    def write(
        self,
        df: pd.DataFrame,
        name: str,
        metadata: Optional[Dict] = None
    ) -> Path:
        """Parquet + 메타데이터 저장"""
        output_path = self.output_dir / f"{name}.parquet"

        # Parquet 저장 (zstd 압축)
        df.to_parquet(output_path, compression="zstd", index=False)

        # 메타데이터 저장
        if metadata:
            meta_path = self.output_dir / f"{name}.meta.json"
            with open(meta_path, "w") as f:
                json.dump(metadata, f)

        return output_path
```

---

## 3. 데이터 흐름

```
INPUT: Excel File
│
▼
┌─────────────────────────────────────────────────────────────────┐
│ ExcelLoader.load()                                               │
│   - openpyxl/xlrd로 파일 열기                                    │
│   - 시트 목록 캐싱                                               │
└─────────────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────────────┐
│ ExcelLoader.read_sheet(sheet_name)                               │
│   - raw DataFrame 반환 (header=None)                            │
│   - 모든 셀 그대로                                               │
└─────────────────────────────────────────────────────────────────┘
│
▼ pd.DataFrame (raw)
│
┌─────────────────────────────────────────────────────────────────┐
│ TableParser.parse(raw_df)                                        │
│   1. _find_start_row() → ExpressionEvaluator                    │
│   2. _extract_header()                                           │
│   3. _find_end_row() → ExpressionEvaluator                      │
│   4. _filter_columns()                                           │
│   5. _convert_types()                                            │
└─────────────────────────────────────────────────────────────────┘
│
▼ pd.DataFrame (parsed)
│
┌─────────────────────────────────────────────────────────────────┐
│ TableWriter.write(parsed_df)                                     │
│   - Parquet 저장                                                 │
│   - 메타데이터 저장                                              │
└─────────────────────────────────────────────────────────────────┘
│
▼
OUTPUT: .parquet + .meta.json
```

---

## 4. 의존성 관계

```
Pipeline
├── depends on: ExcelLoader, TableParser, TableWriter, ConvertConfig
│
ExcelLoader
├── depends on: openpyxl (커스텀), xlrd, pandas
├── no internal dependencies
│
TableParser
├── depends on: ExpressionEvaluator, TableConfig
├── depends on: pandas
│
ExpressionEvaluator
├── depends on: re (stdlib)
├── no internal dependencies
│
TableWriter
├── depends on: pandas, pyarrow
├── no internal dependencies
│
ConvertConfig (Pydantic)
├── depends on: pydantic
├── no internal dependencies
```

---

## 5. 인터페이스 정의

### 5.1 Result Types

```python
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path

@dataclass
class ConvertResult:
    status: str  # "success" | "fail" | "skip"
    sheet: str
    table: str
    output: Optional[Path] = None
    error: Optional[str] = None
    rows_count: int = 0

@dataclass
class PipelineResult:
    results: List[ConvertResult]

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.status == "success")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "fail")

    def to_dict(self) -> dict:
        return {
            "status": "success" if self.fail_count == 0 else "partial",
            "total": len(self.results),
            "success": self.success_count,
            "fail": self.fail_count,
            "results": [asdict(r) for r in self.results]
        }
```

---

## 6. 검토 필요 사항

### 6.1 머지셀 처리

```
현재: HyperloungeExcel에서 처리
V2: 어떻게 할지?

[ ] Option A: HyperloungeExcel 재사용
[ ] Option B: pandas + 별도 로직으로 처리
[ ] Option C: openpyxl 직접 사용

→ 결정 필요
```

### 6.2 멀티 헤더

```
현재: ExcelConverter.make_header_df()에서 복잡하게 처리

[ ] 단순화 가능한지 검토 필요
[ ] 어떤 케이스들이 있는지 정리 필요
```

### 6.3 auto_scan

```
현재: FileConverter.remake_auto_scan_conf()에서 처리

[ ] V2에 포함할지?
[ ] 별도 모듈로 분리할지?
```

---

## 7. 다음 단계

1. [ ] 03_CONFIG_SCHEMA.md - Config 모델 상세 설계
2. [ ] 04_OPTIMIZATION.md - 성능 최적화 포인트 정리
3. [ ] 결정 필요 사항 논의
4. [ ] 프로토타입 구현 시작
