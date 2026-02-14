# Airflow Backfill 가이드

## Composer 환경 정보

- **Environment**: `prodcomp2-4`
- **Location**: `asia-northeast3`
- **Project**: `hyperlounge-dev`

---

## Backfill 명령어

### 기본 형식

```bash
gcloud composer environments run prodcomp2-4 \
  --location asia-northeast3 \
  --project hyperlounge-dev \
  dags backfill -- {DAG_ID} \
  --start-date {DATE}T{TIME}+00:00 \
  --end-date {DATE}T{TIME}+00:00 \
  --reset-dagruns
```

### 예시: kdrive (c3737100) - 10:00 KST (01:00 UTC)

```bash
gcloud composer environments run prodcomp2-4 \
  --location asia-northeast3 \
  --project hyperlounge-dev \
  dags backfill -- c3737100-20251230-1 \
  --start-date 2026-01-19T01:00:00+00:00 \
  --end-date 2026-01-19T01:00:00+00:00 \
  --reset-dagruns
```

### 예시: 엘앤케이웰니스 (c8cd3500) - 23:00 KST (14:00 UTC)

```bash
gcloud composer environments run prodcomp2-4 \
  --location asia-northeast3 \
  --project hyperlounge-dev \
  dags backfill -- c8cd3500-20240517-1 \
  --start-date 2026-01-19T14:00:00+00:00 \
  --end-date 2026-01-19T14:00:00+00:00 \
  --reset-dagruns
```

---

## DAG 수정 후 Backfill 주의사항

### 문제 상황

DAG에 새로운 task를 추가한 후 기존 DagRun을 backfill하면, **새로운 task가 실행되지 않음**.

### 원인

- Airflow DagRun은 생성 시점의 DAG 구조를 스냅샷으로 저장
- 기존 DagRun에는 새로운 TaskInstance가 추가되지 않음
- `--reset-dagruns` 옵션도 상태만 리셋하고, 새 task를 추가하지 않음

### 해결 방법

1. **Airflow UI에서 해당 DagRun 삭제**
   - Browse > DAG Runs
   - 해당 DagRun 선택
   - Actions > Delete

2. **삭제 후 backfill 명령어 실행**
   ```bash
   gcloud composer environments run prodcomp2-4 \
     --location asia-northeast3 \
     --project hyperlounge-dev \
     dags backfill -- {DAG_ID} \
     --start-date {DATE}T{TIME}+00:00 \
     --end-date {DATE}T{TIME}+00:00 \
     --reset-dagruns
   ```

3. 새로운 DagRun이 생성되면서 수정된 DAG 구조로 실행됨

---

## 스케줄 시간 참고 (UTC 기준)

| 고객사 | DAG ID | KST | UTC |
|--------|--------|-----|-----|
| 케이드라이브 | c3737100-20251230-1 | 10:00 | 01:00 |
| 엘앤케이웰니스 | c8cd3500-20240517-1 | 23:00 | 14:00 |

---

## 자주 사용하는 명령어

### DAG 목록 확인

```bash
gcloud composer environments run prodcomp2-4 \
  --location asia-northeast3 \
  --project hyperlounge-dev \
  dags list
```

### 특정 DAG 상태 확인

```bash
gcloud composer environments run prodcomp2-4 \
  --location asia-northeast3 \
  --project hyperlounge-dev \
  dags state -- {DAG_ID} {EXECUTION_DATE}
```

### Task 상태 확인

```bash
gcloud composer environments run prodcomp2-4 \
  --location asia-northeast3 \
  --project hyperlounge-dev \
  tasks state -- {DAG_ID} {TASK_ID} {EXECUTION_DATE}
```
