# [Tech] RPA fileid-mapping output 검사 로직 단순화

## 증상

- 케이드라이브(c3737100) fileid-mapping-rpa 단계에서 정상 수집된 파일이 `fail` 처리됨
- 실제 파일은 GCS에 존재하나 status가 fail로 기록
- error_message가 단순히 "fail"로 표시되어 원인 파악 어려움

### 발생 사례 (2026-01-20)

| file_name | status | error_message |
|-----------|--------|---------------|
| 20260120_20260101-20260120_D_rv17_금월_NA_NA.xlsx | fail | fail |
| 20260120_20260119-20260119_D_as10_전일_NA_NA.xlsx | fail | fail |
| 20260120_20260119-20260119_D_as11_전일_NA_NA.xlsx | fail | fail |
| 20260120_20260119-20260119_D_as12_전일_NA_NA.xlsx | fail | fail |
| 20260120_20260119-20260119_D_as13_전일_NA_NA.xlsx | fail | fail |

---

## 현재 구조

```
[RPA 수집] → [output.xlsx 생성] → [fileid-mapping] → [output 파싱하여 성공/실패 판정]
                                         ↓
                              "처리완료" 아니면 fail 처리
```

- 관련 파일: `collector/cloud/file_renamer.py`
- 검사 로직: `check_result()`, `get_result()`

---

## 문제 원인

| 항목 | 표준 RPA | 케이드라이브 |
|------|---------|-------------|
| 수집 방식 | SSH + VM 관리 | 고객사 PC 내 직접 수집 |
| output.xlsx | 표준 형식 | 형식 다름/없음 |
| 결과 | 정상 동작 | 매칭 실패 → fail |

### 원인 코드 (`file_renamer.py:293`)

```python
def check_result(self, file_name):
    # ... 파일명 파싱 ...

    if result_value[0] == "처리완료":
        return JOB_STATUS_SUCCESS, None

    return JOB_STATUS_FAIL, "fail"  # ← 여기서 fail 반환
```

---

## 관련 복잡 로직들

| 로직 | 파일 | 목적 | 실제 활용도 |
|------|------|------|------------|
| output 검사 | `file_renamer.py` | 성공/실패 판정 | 낮음 (비표준 환경에서 오작동) |
| run_time 분배 | `rpa_actions_splitter.py` | VM 간 균등 분배 | 낮음 (대부분 단일 VM) |
| 이어서 수집 | `rpa_checker.py` | 실패 조건만 재수집 | 낮음 (실패 시 수동 개입) |
| set_run_time | `file_renamer.py` | 수행시간 피드백 | 낮음 (VM 분배 안쓰면 무의미) |

---

## 개선 방향

**복잡한 자동화 → 단순한 구조 + 모니터링**

| 변경 | Before | After |
|------|--------|-------|
| fileid-mapping | output 파싱 → 성공/실패 판정 | 파일 존재 → success |
| 작업 분배 | run_time 기반 자동 분배 | 수동 세팅 또는 단순 분배 |
| 재수집 | 실패 조건만 자동 재수집 | 전체 초기화 후 수동 재수집 |

### 철학

```
복잡한 자동화 < 단순한 구조 + 좋은 모니터링 + 빠른 수동 대응
```

---

## 수정 대상

### 1. `collector/cloud/file_renamer.py`

| 라인 | 내용 | 조치 |
|------|------|------|
| 70-72 | `self.result` 초기화 + RPA일 때 `get_result()` 호출 | RPA 조건 제거 |
| 203-206 | `if self.source_type == SOURCE_RPA and self.result:` | 제거 (항상 success) |
| 216-239 | `if self.result:` 결과 처리 루프 | RPA 부분 제거 |
| 256-293 | `check_result()` 메서드 | 제거 |
| 323-381 | `get_result()` RPA 부분 | 제거 |

### 2. `collector/rpa/rpa_checker.py`

| 메서드 | 조치 |
|--------|------|
| `check_rpa_error_file()` | 제거 또는 로깅만 |

### 3. `collector/rpa/rpa_actions_splitter.py` (선택)

| 메서드 | 조치 |
|--------|------|
| `split_actions_with_run_time()` | 단순 분배로 변경 |
| `set_run_time()` 호출 | 제거 |

### 4. DAG 파일들

| 태스크 | 조치 |
|--------|------|
| `check_error_file_task` | 제거 또는 단순화 |

---

## 영향 범위

### 수정 파일
- `collector/cloud/file_renamer.py`
- `collector/rpa/rpa_checker.py`
- `collector/rpa/rpa_actions_splitter.py`
- DAG 파일들 (약 15개)

### 영향 고객사
RPA 사용 전체 고객사:
- c3737100 (케이드라이브) - 비표준
- c8cd3500, c28e7803, c4792900, c230c700, c4402103, c73be300 등

### Side-effect

| 변경 | 영향 | 심각도 |
|------|------|--------|
| output 검사 제거 | RPA 실패 조기 감지 불가 | 낮음 (RPA 단계에서 감지) |
| set_run_time 제거 | VM 분배 최적화 안됨 | 낮음 (단일 VM이면 무관) |
| 이어서 수집 제거 | 실패 시 전체 재수집 | 중간 (빈도 낮음) |
| "NO DATA" 추적 불가 | 히스토리 기록 안됨 | 낮음 |

---

## 조치 계획

### Phase 1: file_renamer.py 수정 (우선)
- [ ] RPA output 검사 로직 제거
- [ ] 테스트: 케이드라이브 DAG 수동 실행
- [ ] 배포: prod 환경

### Phase 2: rpa_checker.py 수정
- [ ] check_rpa_error_file() 제거 또는 단순화
- [ ] DAG에서 check_error_file_task 제거
- [ ] 테스트 및 배포

### Phase 3: rpa_actions_splitter.py 수정 (선택)
- [ ] run_time 기반 분배 → 단순 분배
- [ ] 테스트 및 배포

---

## 배포 방법

```bash
# 수동 테스트 (빠른 확인)
gsutil cp collector/cloud/file_renamer.py \
  gs://asia-northeast3-prodcomp2-4-fe0f3a24-bucket/dags/collector/cloud/

# 정식 배포 (커밋 후)
cd airflow-dags
./deploy_dags.sh prodcomp2-4
```

---

## 롤백 계획

| 상황 | 조치 |
|------|------|
| fileid-mapping 실패 급증 | git revert → 재배포 |
| 수집 누락 발생 | 수동 재수집 + 롤백 |
| DAG 실행 실패 | 이전 버전 DAG 복원 |

---

## 비고

- 케이드라이브 긴급 조치 필요 (현재 fail 발생 중)
- 운영 편의성 > 고도화 방향으로 결정
- 기존 고객사도 복잡한 로직 혜택 미미
- BOARD/DB 소스의 error_result.json 검사 로직은 유지

---

## 관련 문서

- `collector/cloud/file_renamer.py` - fileid-mapping 핵심 로직
- `collector/rpa/rpa_checker.py` - 에러 파일 재수집 로직
- `collector/rpa/rpa_actions_splitter.py` - VM 분배 로직
- `airflow-dags/dags/dependencies/rpa_tasks.py` - DAG 태스크 정의
