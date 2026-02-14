# V2 Converter 개요

> **상태**: 설계 검토 중
> **작성일**: 2026-02-06

---

## 1. 왜 V2가 필요한가?

### 1.1 현재 문제점 요약

| 문제 | 현재 상태 | 영향 |
|------|----------|------|
| **God Class** | FileConverter 536줄, 7가지 책임 | 유지보수 어려움 |
| **Config 복잡도** | 30+ 필드, 검증 없음 | 오타 시 런타임 에러 |
| **Tight Coupling** | 모든 클래스가 얽혀있음 | 단위 테스트 불가 |
| **성능 비효율** | iterrows, 매번 regex 컴파일 | 대용량 파일 느림 |
| **테스트 어려움** | 로컬 환경 설정 복잡 | 디버깅 시간 증가 |
| **출력 포맷 복잡** | 5개 테이블, JOIN 필수 | 학습 곡선 높음, 쿼리 복잡 |

### 1.2 V2 목표

```
1. 책임 분리     → 각 모듈이 하나의 역할만
2. Config 검증   → Pydantic으로 타입 안전성
3. 테스트 용이성 → 각 컴포넌트 독립 테스트 가능
4. 성능 최적화   → vectorized 연산, 캐싱
5. 기존 호환성   → 기존 config JSON 포맷 지원
```

---

## 2. 범위 (Scope)

### 2.1 포함

```
[포함]
├── Excel 파일 로드 (xlsx, xls)
├── 테이블 파싱 (행/열 범위, 헤더)
├── 데이터 변환 (타입 캐스팅, 정규화)
├── 결과 출력 (Parquet, 메타데이터)
└── Config 검증
```

### 2.2 제외 (별도 프로젝트)

```
[제외]
├── Tagger (tag_builder, tag_writer) → 추후 검토
├── Source Type 아키텍처 → 별도 회의 필요
├── LLM Converter 통합 → 별도 프로젝트
└── Airflow DAG 구조 → 별도 프로젝트
```

---

## 3. 기존 코드와의 관계

### 3.1 기존 구조

```
collector/excel/
├── file_converter.py      # 536줄 - God class
├── excel_converter.py     # 800줄 - 핵심 변환 로직
├── excel_config.py        # 400줄 - Config 파싱
├── table_writer.py        # 200줄 - 출력
├── tagger.py              # 300줄 - 태깅
├── transformer.py         # 변환 헬퍼
├── data_prep.py           # 데이터 정제
├── type_converter.py      # 타입 변환
└── reader/
    ├── hl_excel.py        # Excel 래퍼
    ├── hl_openpyxl.py     # openpyxl 래퍼
    └── hl_xlrd.py         # xlrd 래퍼
```

### 3.2 V2 구조 (목표)

```
collector/excel/v2/
├── config/                # Config 검증
│   ├── schema.py          # Pydantic 모델
│   └── validator.py       # 검증 로직
├── loader/                # I/O 분리
│   └── excel_loader.py    # 파일 로드만
├── parser/                # 변환 로직
│   ├── table_parser.py    # 테이블 파싱
│   └── expression.py      # 표현식 평가
├── writer/                # 출력
│   └── table_writer.py    # Parquet 출력
└── pipeline.py            # 오케스트레이션
```

### 3.3 마이그레이션 전략

```
Phase 1: V2 개발 (기존 코드 유지)
         ↓
Phase 2: V2 검증 (기존과 결과 비교)
         ↓
Phase 3: 점진적 교체 (entry point 전환)
         ↓
Phase 4: 기존 코드 deprecate
```

---

## 4. 관련 문서

| 문서 | 내용 |
|------|------|
| [02_ARCHITECTURE.md](./02_ARCHITECTURE.md) | 클래스 구조, 데이터 흐름 |
| [03_CONFIG_SCHEMA.md](./03_CONFIG_SCHEMA.md) | Config Pydantic 모델 설계 |
| [04_OPTIMIZATION.md](./04_OPTIMIZATION.md) | 성능 최적화 포인트 |
| [05_MIGRATION.md](./05_MIGRATION.md) | 마이그레이션 계획 |
| [06_OUTPUT_FORMAT_ISSUES.md](./06_OUTPUT_FORMAT_ISSUES.md) | 출력 포맷 복잡성 분석 |
| [07_DEPLOYMENT_ARCHITECTURE.md](./07_DEPLOYMENT_ARCHITECTURE.md) | Cloud Run Job/Service 배포 구조 |

---

## 5. 결정 필요 사항

### 5.1 Config 호환성

```
[ ] Option A: 기존 JSON 구조 100% 유지
    - 장점: 마이그레이션 비용 없음
    - 단점: 레거시 필드명 유지

[ ] Option B: 새 구조 + 변환 레이어
    - 장점: 깔끔한 필드명
    - 단점: 변환 로직 필요
```

### 5.2 Tagger 통합

```
[ ] Option A: V2에 Tagger 포함
    - 장점: 한 번에 처리
    - 단점: 범위 증가

[ ] Option B: Tagger는 별도 유지
    - 장점: 범위 제한
    - 단점: 인터페이스 정의 필요
```

### 5.3 기존 코드 재사용

```
[ ] Option A: HyperloungeExcel 래핑해서 재사용
    - 장점: 검증된 코드 활용
    - 단점: 기존 복잡성 유입

[ ] Option B: pandas 직접 사용
    - 장점: 단순화
    - 단점: 머지셀 등 재구현 필요
```

---

## 6. 다음 단계

1. [ ] 02_ARCHITECTURE.md 검토
2. [ ] 03_CONFIG_SCHEMA.md 검토
3. [ ] 결정 필요 사항 논의
4. [ ] 우선순위 결정 후 구현 시작
