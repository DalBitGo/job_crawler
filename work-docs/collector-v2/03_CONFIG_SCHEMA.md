# V2 Config Schema 설계

> **상태**: 설계 검토 중
> **작성일**: 2026-02-06

---

## 0. Config 복잡성에 대하여

### 0.1 왜 복잡할 수밖에 없는가?

다양한 엑셀 포맷을 커버해야 하기 때문:

```
실제 엑셀 파일들의 다양성:
├── 시작 행이 다름 (1행, 3행, 5행...)
├── 헤더 위치가 다름 (있음/없음/멀티헤더)
├── 머지 셀 존재
├── 가변 컬럼 수
├── 중간에 빈 행/요약 행
├── 시트마다 다른 포맷
└── 등등...

→ 이걸 다 커버하려면 옵션이 많을 수밖에 없음
```

### 0.2 복잡성을 줄일 수 있는 방향

| 현재 문제 | 개선 방향 |
|----------|----------|
| 오타 → 런타임 에러 | Pydantic으로 **타입 검증** |
| 어떤 필드가 필수인지 모름 | **필수 vs 선택** 명확히 구분 |
| 기본값 없음 | **합리적인 기본값** 제공 |
| 문서 부족 | 각 필드 **설명 + 예시** |
| 전부 수동 작성 | 자주 쓰는 패턴은 **템플릿/프리셋** |

### 0.3 템플릿/프리셋 아이디어

**단순한 케이스용 프리셋:**
```python
# 80% 케이스: 단순한 테이블
config = SimpleTableConfig(
    sheet=".*",
    header_row=1,
    start_col="A",
    end_col="Z"
)
# → 내부적으로 FullConfig로 변환
```

**자주 쓰는 패턴 템플릿:**
```python
# 패턴 1: 헤더 + 빈 행까지
config = from_template("header_until_empty",
    header_expr="팀코드",
    cols="A:Z"
)

# 패턴 2: 멀티 헤더
config = from_template("multi_header",
    header_levels=2,
    start_row=3
)

# 패턴 3: 특정 값까지
config = from_template("until_pattern",
    header_expr="시작",
    end_expr="^합계"
)
```

**복잡한 케이스만 풀 옵션:**
```python
# 20% 케이스: 특수한 포맷
config = FullConfig(
    rows={"start": {...}, "end": {...}, "body": {...}},
    multi_header={"level": 2},
    multi_index=["조직", "하위조직"],
    filters=[...],
    ...
)
```

### 0.4 결론

```
필드 수 자체는 줄이기 어려움 (범용성 필요)
     ↓
대신 "사용성" 개선에 집중:
  1. 타입 검증 (Pydantic)
  2. 기본값 제공
  3. 템플릿/프리셋
  4. 명확한 문서
```

---

## 1. 현재 Config 구조 분석

### 1.1 전체 구조

```json
{
  "_CVT_OPTIONS_": { ... },     // 전역 옵션
  "convert": { ... },           // 시트/테이블별 변환 규칙
  "tagging": { ... }            // 태깅 설정 (V2 범위 외)
}
```

### 1.2 _CVT_OPTIONS_ (전역 옵션)

```json
{
  "_CVT_OPTIONS_": {
    "version": "1.0",
    "normalize_header": {       // 헤더 정규화 규칙
      "\n": "_",
      " ": "",
      "\r": "",
      ")": "_",
      "(": "_"
    },
    "normalize_index": {        // 인덱스 정규화 규칙
      " ": "",
      ")": "_",
      "(": "_"
    },
    "sheet_range": {            // 시트 범위
      "count": 3,
      "forward": true
    },
    "max_rows": 100000,         // 최대 행 수
    "data_only": true,          // 수식 대신 값만
    "hidden": {                 // 숨김 처리
      "sheet": false,
      "row": true,
      "column": false
    }
  }
}
```

### 1.3 convert (테이블별 설정)

```json
{
  "convert": {
    ".+": {                         // 시트 패턴 (regex)
      "TB01": {                     // 테이블 이름
        "header": true,             // 헤더 있음
        "cols": "A:Z",              // 컬럼 범위
        "rows": {
          "start": {                // 시작 행 (표현식)
            "header_coordinate": "A",
            "expr": "팀코드",
            "match": 1,
            "offset": 0
          },
          "end": {                  // 종료 행 (표현식)
            "header_name": "팀코드",
            "empty": true,
            "including": false
          }
        }
      }
    }
  }
}
```

### 1.4 rows 설정 변형들

```json
// Case 1: 고정 행 번호
"rows": {
  "start": 5,
  "end": 100
}

// Case 2: 표현식
"rows": {
  "start": {
    "header_coordinate": "A",
    "expr": "^합계",
    "match": 1,
    "offset": 0,
    "optional": false
  }
}

// Case 3: 빈 행까지
"rows": {
  "end": {
    "header_name": "column_name",
    "empty": true
  }
}

// Case 4: 특정 값까지
"rows": {
  "end": {
    "header_name": "column_name",
    "expr": "^Total",
    "including": true
  }
}

// Case 5: body 별도 지정
"rows": {
  "start": { ... },
  "body": {
    "header_name": "데이터",
    "expr": "시작",
    "offset": 1
  },
  "end": { ... }
}

// Case 6: 필터
"rows": {
  "filters": [
    {
      "header_name": "상태",
      "expr": "Active",
      "mode": "in"      // "in" or "out"
    }
  ]
}
```

### 1.5 cols 설정 변형들

```json
// Case 1: 범위 문자열
"cols": "A:Z"

// Case 2: 리스트
"cols": ["A", "B", "E:G"]

// Case 3: 표현식 필터
"cols": {
  "initial": "A:Z",
  "expr": "^(?!Draft)"   // Draft로 시작하지 않는 컬럼
}
```

---

## 2. Pydantic 모델 설계

### 2.1 전역 옵션

```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Union, List
from enum import Enum


class NormalizeRules(BaseModel):
    """문자열 치환 규칙"""
    rules: Dict[str, str] = Field(default_factory=dict)

    class Config:
        extra = "allow"  # 추가 키 허용


class SheetRange(BaseModel):
    """시트 범위 설정"""
    count: int = Field(default=10, description="처리할 시트 수")
    forward: bool = Field(default=True, description="앞에서부터")
    sort: bool = Field(default=False, description="정렬 여부")


class HiddenConfig(BaseModel):
    """숨김 처리 설정"""
    sheet: bool = Field(default=False)
    row: bool = Field(default=True)
    column: bool = Field(default=False)


class CvtOptions(BaseModel):
    """전역 변환 옵션 (_CVT_OPTIONS_)"""
    version: str = Field(default="1.0")
    normalize_header: Dict[str, str] = Field(default_factory=dict)
    normalize_index: Dict[str, str] = Field(default_factory=dict)
    sheet_range: Optional[SheetRange] = None
    max_rows: int = Field(default=100000)
    data_only: bool = Field(default=True)
    hidden: Optional[HiddenConfig] = None
```

### 2.2 행 설정

```python
class RowExprStart(BaseModel):
    """행 시작 표현식"""
    header_coordinate: str = Field(description="검색할 컬럼 (A, B, ...)")
    expr: str = Field(description="regex 패턴")
    match: int = Field(default=1, description="N번째 매칭")
    offset: int = Field(default=0, description="오프셋")
    optional: bool = Field(default=False, description="없어도 OK")


class RowExprEnd(BaseModel):
    """행 종료 표현식"""
    header_name: Optional[str] = Field(default=None, description="컬럼 이름")
    expr: Optional[str] = Field(default=None, description="regex 패턴")
    empty: bool = Field(default=False, description="빈 행까지")
    including: bool = Field(default=True, description="매칭 행 포함")


class RowExprBody(BaseModel):
    """본문 시작 표현식"""
    header_name: str
    expr: str
    match: int = Field(default=1)
    offset: int = Field(default=0)


class RowFilter(BaseModel):
    """행 필터"""
    header_name: str
    expr: str
    mode: str = Field(default="in", pattern="^(in|out)$")
    optional: bool = Field(default=False)


class RowsConfig(BaseModel):
    """행 설정"""
    start: Union[int, RowExprStart]
    end: Optional[Union[int, RowExprEnd]] = None
    body: Optional[RowExprBody] = None
    filters: Optional[List[RowFilter]] = None
```

### 2.3 열 설정

```python
class ColsExpr(BaseModel):
    """열 표현식"""
    initial: str = Field(description="초기 범위 (A:Z)")
    expr: str = Field(description="필터 regex")


# cols는 여러 타입 가능
ColsType = Union[str, List[str], ColsExpr]
```

### 2.4 테이블 설정

```python
class TableConfig(BaseModel):
    """테이블별 변환 설정"""
    header: Union[bool, int] = Field(default=True)
    header_names: Optional[List[str]] = None
    rows: Optional[RowsConfig] = None
    cols: Optional[ColsType] = None
    converters: Optional[Dict[str, str]] = None  # 타입 변환
    multi_index: Optional[List[str]] = None
    multi_header: Optional[Dict] = None
    merge_option: Optional[Dict[str, str]] = None
    auto_scan: bool = Field(default=False)
    const: bool = Field(default=False)

    class Config:
        extra = "allow"  # 알 수 없는 필드 허용 (하위 호환)
```

### 2.5 전체 Config

```python
class ConvertConfig(BaseModel):
    """전체 변환 설정"""
    cvt_options: Optional[CvtOptions] = Field(
        default=None,
        alias="_CVT_OPTIONS_"
    )
    convert: Dict[str, Dict[str, TableConfig]] = Field(
        description="시트패턴 → 테이블이름 → 설정"
    )
    tagging: Optional[Dict] = Field(
        default=None,
        description="태깅 설정 (V2 범위 외)"
    )

    class Config:
        populate_by_name = True  # alias와 필드명 둘 다 허용

    def get_tables(self, sheet_name: str) -> List[tuple[str, TableConfig]]:
        """시트 이름에 매칭되는 테이블 설정들 반환"""
        result = []
        for sheet_pattern, tables in self.convert.items():
            if re.match(sheet_pattern, sheet_name):
                for table_name, table_config in tables.items():
                    result.append((table_name, table_config))
        return result
```

---

## 3. 검증 로직

### 3.1 커스텀 검증

```python
from pydantic import validator, root_validator


class RowsConfig(BaseModel):
    # ... 필드 정의 ...

    @validator('end')
    def validate_end(cls, v, values):
        """end가 있으면 start보다 커야 함 (둘 다 int인 경우)"""
        start = values.get('start')
        if isinstance(start, int) and isinstance(v, int):
            if v <= start:
                raise ValueError(f"end({v}) must be greater than start({start})")
        return v


class TableConfig(BaseModel):
    # ... 필드 정의 ...

    @root_validator
    def validate_header_config(cls, values):
        """header=False면 header_names 필요"""
        header = values.get('header')
        header_names = values.get('header_names')

        if header is False and not header_names:
            # 경고만 (에러 X)
            import warnings
            warnings.warn("header=False but header_names not provided")

        return values
```

### 3.2 Config 로드 함수

```python
def load_config(config_json: dict) -> ConvertConfig:
    """
    JSON dict를 ConvertConfig로 변환

    Args:
        config_json: Firestore/API/로컬에서 가져온 JSON

    Returns:
        ConvertConfig: 검증된 config 객체

    Raises:
        ValidationError: 검증 실패 시
    """
    try:
        return ConvertConfig(**config_json)
    except ValidationError as e:
        # 상세 에러 메시지
        errors = []
        for err in e.errors():
            loc = " → ".join(str(l) for l in err['loc'])
            errors.append(f"  {loc}: {err['msg']}")

        raise ConfigValidationError(
            f"Config validation failed:\n" + "\n".join(errors)
        ) from e


def load_config_safe(config_json: dict) -> tuple[ConvertConfig, List[str]]:
    """
    검증 + 경고 반환 (실패해도 기본값으로 진행)
    """
    warnings = []
    # ... 구현
    return config, warnings
```

---

## 4. 기존 Config와의 호환성

### 4.1 필드 매핑

| 기존 | Pydantic | 비고 |
|------|----------|------|
| `_CVT_OPTIONS_` | `cvt_options` | alias로 둘 다 지원 |
| `convert` | `convert` | 동일 |
| `tagging` | `tagging` | 그대로 전달 |

### 4.2 하위 호환 전략

```python
class TableConfig(BaseModel):
    class Config:
        extra = "allow"  # 알 수 없는 필드 무시 (에러 X)

# 기존에 있지만 V2에서 안 쓰는 필드들
# → extra = "allow"로 무시됨
# → 나중에 필요하면 추가
```

### 4.3 마이그레이션 불필요

```
기존 JSON 그대로 사용 가능
→ Pydantic이 파싱하면서 기본값 채움
→ 타입 검증만 추가됨
```

---

## 5. 사용 예시

### 5.1 Config 로드

```python
from collector.excel.v2.config import load_config

# Firestore에서 가져온 JSON
config_json = {
    "_CVT_OPTIONS_": {"version": "1.0"},
    "convert": {
        ".+": {
            "TB01": {
                "header": True,
                "cols": "A:Z",
                "rows": {
                    "start": {"header_coordinate": "A", "expr": "팀코드"}
                }
            }
        }
    }
}

# 검증 + 변환
config = load_config(config_json)

# 사용
print(config.cvt_options.version)  # "1.0"
print(config.convert[".+"]["TB01"].cols)  # "A:Z"
```

### 5.2 테이블 설정 가져오기

```python
# 시트 이름으로 매칭되는 테이블들
tables = config.get_tables("Sheet1")

for table_name, table_config in tables:
    print(f"Table: {table_name}")
    print(f"  cols: {table_config.cols}")
    print(f"  rows.start: {table_config.rows.start}")
```

---

## 6. 결정 필요 사항

### 6.1 엄격한 검증 vs 느슨한 검증

```
[ ] Option A: 엄격 (unknown field → error)
    - 장점: 오타 발견 가능
    - 단점: 기존 config 호환 안될 수 있음

[ ] Option B: 느슨 (unknown field → ignore)  ← 현재 설계
    - 장점: 기존 config 100% 호환
    - 단점: 오타 발견 못함

[ ] Option C: 경고만 (unknown field → warning)
    - 장점: 둘 다 만족
    - 단점: 구현 복잡
```

### 6.2 기본값 정책

```
[ ] 기존 코드와 동일한 기본값 사용
[ ] 새로운 합리적인 기본값 사용
    → 기존과 다르면 결과 달라질 수 있음

→ 검토 필요
```

---

## 7. 다음 단계

1. [ ] 기존 config 샘플들로 Pydantic 모델 검증
2. [ ] 누락된 필드 확인 및 추가
3. [ ] 기본값 검토
4. [ ] 04_OPTIMIZATION.md 작성
