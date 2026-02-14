# [Tech] tag_prep 병렬 처리 개선 및 안정화

| 항목 | 내용 |
|------|------|
| 증상 | c8cd3500 board `tag-prep-board` 태스크 3시간 소요, 타임아웃 에러 |
| 원인 | Cloud Run Job 없음, Service 방식으로 20개 병렬 제한 |
| 개선 방향 | Cloud Run Job 전환 (convert/tagger와 동일) |
| 영향 고객사 | 전체 |
| 위험도 | 낮음 |

---

## 증상

- 엘앤케이웰니스(c8cd3500) board 소스 `tag-prep-board` 태스크 **3시간 소요**
- 645개 테이블 처리 중 간헐적 타임아웃 발생
- `ServerTimeoutError: Timeout on reading data from socket`

## 현재 구조

### tag_prep 실행 흐름

```
Airflow DAG
    │
    ▼
create_tag_prep_task()
    │
    ▼
tag_prep_caller() → run_tag_prep()
    │
    ▼
trigger_tag_prep() → run_tag_preprocessing()
    │
    ▼
call_cloud_function()  ← HTTP 호출 (Cloud Run Service)
    │
    ├── gcf_url: tag-prep-2-0
    ├── connect_limit: 20      ← 20개씩만 병렬!
    └── timeout_seconds: 3600  ← 1시간 타임아웃
```

### convert/tagger vs tag_prep 비교

| Task | 배포 방식 | 병렬 처리 | 소요 시간 (645건) |
|------|----------|----------|------------------|
| convert | Cloud Run **Job** | 100개 동시 | ~5분 |
| tagger | Cloud Run **Job** | 100개 동시 | ~5분 |
| **tag_prep** | Cloud Run **Service** | **20개 동시** | **~3시간** |

### 왜 tag_prep만 느린가?

```python
# collector/tag_preprocessing/tag_preprocessing.py:11-36
call_cloud_function(
    param_list=post_params,
    gcf_url=gcf_url,
    connect_limit=20,        # ← 병목! (convert/tagger는 Job으로 100개)
    timeout_seconds=3600,
)
```

## 문제 원인

| 항목 | 내용 |
|------|------|
| 배포 방식 | Cloud Run Service (HTTP) - Job 없음 |
| 병렬 제한 | `connect_limit=20` (aiohttp 동시 연결 수) |
| 타임아웃 | 개별 요청 1시간, 소켓 읽기 타임아웃 미설정 |
| 재시도 | 있음 (retry=1), 하지만 37분 갭 발생 |
| Job 부재 | `mdm/tag_mapping/`에 Dockerfile, Job 스크립트 없음 |

### 실제 로그 분석 (2026-02-10, c8cd3500 board)

```
시작: 20:18:50 UTC
├── Total tasks: 645
├── 20:18:50 - tid0~tid19 시작 (20개 동시)
├── 22:31:48 - 641/645 완료
├── 22:31:48 ~ 23:08:45 - 타임아웃 에러 발생
│   └── ServerTimeoutError (tid558, tid566)
├── 23:12:11 - retry 후 재시도
└── 23:16:00 - 643/645 완료

소요: 약 3시간
```

## 개선 방향: Cloud Run Job 전환

convert/tagger와 동일하게 Cloud Run Job 방식으로 전환:

```
mdm/tag_mapping/
├── main.py                  # 기존 Service 진입점
├── deploy.sh                # 기존 Service 배포
│
├── Dockerfile               # [신규] Job용 이미지
├── job_main.py              # [신규] Job 진입점
├── build_docker.sh          # [신규] Docker 빌드
└── deploy_job.sh            # [신규] Job 배포
```

### Job 진입점 예시

```python
# job_main.py
TASK_INDEX = int(os.getenv("CLOUD_RUN_TASK_INDEX", 0))
TASK_COUNT = int(os.getenv("CLOUD_RUN_TASK_COUNT", 1))

# GCS에서 분할된 items 로드
items = load_items_from_gcs(items_path)

# 자기 Task만 처리
process_tag_prep(items[TASK_INDEX])
```

### 장점

- 병렬 100개 (5배 향상)
- convert/tagger와 일관된 아키텍처
- 비용 효율적 (실행 시간 기반)
- 개별 Task 독립으로 타임아웃 영향 최소화

## 영향 범위

| 항목 | 내용 |
|------|------|
| 수정 대상 | `mdm/tag_mapping/` + Airflow DAG |
| 영향 고객사 | 전체 (tag_prep 사용 고객) |
| 위험도 | 낮음 (기존 로직 유지, 실행 방식만 변경) |

## 예상 효과

| 지표 | Before | After |
|------|--------|-------|
| 병렬 처리 | 20개 | 100개 |
| 소요 시간 (645건) | ~3시간 | **~30분** |
| 타임아웃 빈도 | 간헐적 발생 | 감소 (개별 Task 독립) |

## 조치 계획

| 단계 | 내용 | 담당 |
|------|------|------|
| 1단계 | tag_prep Job용 Dockerfile, 진입점 개발 | - |
| 2단계 | Airflow `tag_prep_with_job` 함수 추가 | - |
| 3단계 | 테스트 고객사 적용 (c8cd3500) | - |
| 4단계 | 전체 고객사 롤아웃 | - |

## 관련 파일

```
collector/tag_preprocessing/
├── create_task.py              # Airflow Task 생성
├── run_tag_prep.py             # 실행 오케스트레이션
└── tag_preprocessing.py        # call_cloud_function 호출

mdm/tag_mapping/
├── main.py                     # Cloud Run Service 진입점
├── deploy.sh                   # 현재 배포 (tag-prep-2-0)
└── (Job 관련 파일 없음)         # ← 신규 개발 필요
```

## 참고: convert/tagger Job 구조

```
collector/deploy/converter_job/
├── Dockerfile
├── main.py                     # TASK_INDEX로 분할 처리
├── build_docker.sh
└── requirements.txt

collector/deploy/tagger_job/
├── Dockerfile
├── main.py
├── build_docker.sh
└── requirements.txt
```

---

**작성일**: 2026-02-11
**관련 이슈**: c8cd3500 tag-prep-board 3시간 소요, 타임아웃 에러
