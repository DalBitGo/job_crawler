# 내일식품(c73be300) Convert 오류 분석 및 해결 방안

**작성일**: 2025-12-31
**작성자**: Claude Code
**상태**: 분석 완료, 배포 대기

---

## 1. 문제 현상

### 1.1 오류 발생 정보
| 항목 | 내용 |
|------|------|
| 고객사 | 내일식품 (c73be300) |
| DAG | `c73be300-20250219-1` |
| 실패 Task | `convert-with-job-pc` |
| Cloud Run Job | `job-convert-4-2` |
| 오류 유형 | 20분 timeout (1200초) |
| 발생일 | 2025-12-26, 2025-12-30 |

### 1.2 실패 파일
- `2025.12.25 매출_e159d005_20251226.xlsx`
- `2025.12.29 매출_xxxxx_20251230.xlsx`

### 1.3 로그 분석
```
[openpyxl] A-02 sheet is appended
... (이후 20분간 응답 없음)
ERROR: Not finished tasks=1
```

---

## 2. 원인 분석

### 2.1 Excel 파일 구조
```
openpyxl 인식 max_row: 20,750행
실제 데이터 존재 행: 1,780행 (1~1780)
빈 행 (서식만 적용): 18,970행 (1781~20750)
```

- Excel에서 셀 서식(number_format 등)이 20,750행까지 적용됨
- 실제 데이터(값)는 1,780행까지만 존재
- openpyxl은 서식이 있는 행도 유효한 행으로 인식

### 2.2 커스텀 openpyxl 설정
**파일 위치**: `openpyxl/conf/openpyxl_for_hyperlounge.json`
```json
{
  "hl_remove_empty_row": true,
  "hl_remove_named_style": true
}
```

### 2.3 문제의 함수
**파일**: `openpyxl/worksheet/_reader.py`

```python
def _remove_empty_row(self):
    """현재 구현 - 매우 비효율적"""
    cur_idx = self.ws.max_row  # 20750
    while cur_idx > 0:
        cells = (self.ws.cell(row=cur_idx, column=column)
                 for column in range(min_col, max_col + 1))
        cells_value = tuple(cell.value for cell in cells)
        if any(cells_value) is False:
            self.ws.delete_rows(cur_idx)  # 19,000번 개별 호출!
        else:
            return True
        cur_idx -= 1
    return False
```

### 2.4 성능 문제
| 항목 | 값 |
|------|---|
| `delete_rows()` 1회 소요 시간 | ~0.18초 |
| 빈 행 개수 | ~19,000개 |
| 총 예상 소요 시간 | **56분** |
| 현재 timeout | 20분 |

---

## 3. 해결 방안

### 3.1 최적화된 `_remove_empty_row()` 함수

```python
def _remove_empty_row(self):
    """최적화된 구현 - 일괄 삭제"""
    if self.ws.max_row <= 1:
        return False

    min_col = self.ws.min_column or 1
    max_col = self.ws.max_column or 1

    # 1단계: 실제 데이터가 있는 마지막 행 찾기 (한 번 스캔)
    real_max_row = None
    for row in range(self.ws.max_row, 0, -1):
        cells_value = tuple(
            self.ws.cell(row=row, column=col).value
            for col in range(min_col, max_col + 1)
        )
        if any(cells_value):
            real_max_row = row
            break

    # 2단계: 빈 행 일괄 삭제
    if real_max_row is None:
        # 전체가 빈 시트
        return False

    if real_max_row < self.ws.max_row:
        rows_to_delete = self.ws.max_row - real_max_row
        self.ws.delete_rows(real_max_row + 1, rows_to_delete)  # 한 번에 삭제!

    return True
```

### 3.2 성능 비교
| 방식 | 소요 시간 |
|------|----------|
| 기존 (개별 삭제) | ~56분 |
| 최적화 (일괄 삭제) | **~0.55초** |

### 3.3 로컬 테스트 결과
```
마지막 데이터 행 찾기: 0.22초
일괄 삭제 (18,970행): 0.31초
총 소요 시간: 0.55초
결과: max_row 20750 → 1780 (정상)
```

---

## 4. 배포 전략

### 4.1 버전 관리 원칙
- `job-convert-4-2`: 기존 유지 (다른 고객사 영향 방지)
- `job-convert-4-3`: 새로 생성 (최적화된 openpyxl 포함)

### 4.2 Cloud Run 리소스 현황

**Cloud Run Services (HTTP 함수):**
| 이름 | 상태 | 비고 |
|------|------|------|
| convert-excel-4-2 | 존재 | 단일 파일 변환용 |
| convert-excel-4-3 | 존재 | 단일 파일 변환용 |

**Cloud Run Jobs (배치 작업):**
| 이름 | 상태 | 비고 |
|------|------|------|
| job-convert-4-2 | 존재 | 현재 사용 중 |
| job-convert-4-3 | **없음** | 새로 생성 필요 |

### 4.3 Firestore 설정 변경
**컬렉션**: `customers/{c73be300}/versions`

변경 전:
```json
{
  "convert_job_name": "job-convert-4-2"
}
```

변경 후:
```json
{
  "convert_job_name": "job-convert-4-3"
}
```

---

## 5. 배포 작업 체크리스트

### 5.1 사전 준비
- [x] 문제 원인 분석 완료
- [x] 최적화 로직 설계 완료
- [x] 로컬 테스트 완료 (성능 검증)
- [ ] 사이드 이펙트 검토

### 5.2 코드 수정
- [ ] `openpyxl/worksheet/_reader.py` 수정
  - `_remove_empty_row()` 함수 최적화
- [ ] 커스텀 openpyxl whl 파일 재빌드
  - 경로: `collector/deploy/converter_job/dist/openpyxl-3.0.10-py2.py3-none-any.whl`

### 5.3 배포
- [ ] Docker 이미지 빌드 (job-convert-4-3)
- [ ] Cloud Run Job 생성 (`job-convert-4-3`)
- [ ] 배포 테스트

### 5.4 적용
- [ ] Firestore 설정 변경 (c73be300)
- [ ] DAG 수동 실행 테스트
- [ ] 모니터링

---

## 6. 주의사항

### 6.1 사이드 이펙트 검토 필요
1. **중간 빈 행 처리**: 현재 로직은 끝에서부터 연속된 빈 행만 삭제
   - 데이터 중간의 빈 행은 유지됨 (기존 동작과 동일)

2. **완전히 빈 시트**: `real_max_row = None`인 경우 처리
   - 기존: 모든 행 개별 삭제 후 False 반환
   - 변경: 바로 False 반환 (빈 시트 유지)

3. **다른 고객사 영향**:
   - `job-convert-4-2`는 변경하지 않음
   - 내일식품만 `job-convert-4-3` 사용

### 6.2 롤백 계획
문제 발생 시:
1. Firestore에서 `convert_job_name`을 `job-convert-4-2`로 되돌림
2. DAG 재실행

---

## 7. 관련 파일 경로

```
hyperloungescripts/
├── airflow-dags/dags/
│   └── c73be300.py                          # 내일식품 DAG
├── collector/
│   ├── deploy/converter_job/
│   │   ├── dist/
│   │   │   └── openpyxl-3.0.10-py2.py3-none-any.whl  # 커스텀 openpyxl
│   │   ├── Dockerfile
│   │   └── build_docker.sh
│   └── excel/
│       └── reader/hl_openpyxl.py            # openpyxl 래퍼
└── .venv/Lib/site-packages/openpyxl/
    ├── worksheet/_reader.py                  # 수정 대상 (로컬 참조용)
    └── conf/openpyxl_for_hyperlounge.json   # 커스텀 설정
```

---

## 8. 다음 단계

1. **즉시**: 이 문서를 기반으로 팀 내 공유 및 검토
2. **단기**: job-convert-4-3 배포 및 테스트
3. **중기**: 다른 고객사에서 유사 이슈 발생 시 동일 방식 적용 검토

---

## 변경 이력

| 날짜 | 내용 | 작성자 |
|------|------|--------|
| 2025-12-31 | 초안 작성 | Claude Code |
