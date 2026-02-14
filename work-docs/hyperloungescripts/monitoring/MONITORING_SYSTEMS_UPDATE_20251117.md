# 모니터링 시스템 UI 업데이트 (2025-11-17)

## 📋 개요

세 가지 모니터링 시스템의 Teams 메시지 포맷을 통일하고 개선했습니다.

---

## 🎯 변경된 시스템

### 1. Airflow DAG Monitor
**목적**: Airflow DAG 실행 상태 주간 리포트

**변경 사항**:
- ✅ KPI 카드 순서 변경: 실패-성공-진행중 → **성공-실패-진행중**
- ✅ KPI 카드 위치 이동: 표 아래 → **제목 바로 밑**
- ✅ 더 나은 가독성

**배포 정보**:
- Cloud Run Job: `airflow-dag-monitor-job`
- Scheduler: `run-airflow-dag-monitor-daily`
- 실행 시간: 매일 08:30 AM KST
- Service Account: `history-checker@hyperlounge-dev.iam.gserviceaccount.com`

### 2. History Checker (Crawl History)
**목적**: RPA/Board 파일 수집 실패 모니터링

**변경 사항**:
- ✅ 테이블 헤더 줄바꿈 수정:
  - `고객사코드` → `고객사<br>코드`
  - `연속실패일수` → `연속<br>실패일수`
  - `첫실패일` → `첫<br>실패일`
  - `위험등급` → `위험<br>등급`
  - `상세정보` → `상세<br>정보`
- ✅ Webhook URL 업데이트: 새 Power Automate workflow로 변경
  - Old: `c938d2c3d1d0410aa30c155c6efa9b99`
  - New: `4420c93378d24e25ac55b5b38f4381d6` (airflow-dag-report 복사본)

**배포 정보**:
- Cloud Run Job: `ops-send-crawl-history-runjob`
- Scheduler: **Power Automate** (Trigger History Check API Daily)
- Service Account: `history-checker@hyperlounge-dev.iam.gserviceaccount.com`
- 아키텍처: Power Automate → Cloud Run Job → Power Automate → Teams

### 3. Converter Failure Monitor
**목적**: 파일 변환 실패 모니터링 (LLM 분석 포함)

**변경 사항**:
- ✅ **첫 배포 완료!**
- ✅ GCS Config 기반 프롬프트 관리
- ✅ LLM 분석 기능 (Claude Sonnet 4.5)
- ✅ KPI 카드 형식 (실패 파일 / 실패 고객사)

**배포 정보**:
- Cloud Run Job: `converter-failure-monitor`
- Scheduler: `run-converter-failure-monitor-daily`
- 실행 시간: 매일 08:36 AM KST
- Service Account: `history-checker@hyperlounge-dev.iam.gserviceaccount.com`
- Config: `gs://hyperlounge-converter-monitor-config/config.json`

---

## 🔧 수정된 파일

### airflow_dag_monitor/utils/formatter.py
```python
# KPI 카드 순서: 성공-실패-진행중
<td style="text-align:center; padding:15px; border:none;">
<b style="font-size:24px; color:#36B37E;">{biz_success}</b><br>
<span style="font-size:11px; color:#6B778C;">성공</span>
</td>
<td style="text-align:center; padding:15px; border:none;">
<b style="font-size:24px; color:#DE350B;">{biz_failed}</b><br>
<span style="font-size:11px; color:#6B778C;">실패</span>
</td>
<td style="text-align:center; padding:15px; border:none;">
<b style="font-size:24px; color:#0747A6;">{biz_running}</b><br>
<span style="font-size:11px; color:#6B778C;">진행중</span>
</td>

# 메시지 순서: 제목 → 요약 → 표 → 범례
message_parts = [
    title,
    "---",
    summary_line,  # 제목 바로 밑에 요약 배치
    "---",
    "\n".join(table_rows),
    legend,
]
```

### history_checker/utils/teams_formatter_v3.py
```python
# 테이블 헤더 줄바꿈
lines.append("| 기준일 | 고객사명 | 고객사<br>코드 | 소스ID | 전체수 | 실패수 | 실패율(%) | 연속<br>실패일수 | 첫<br>실패일 | 위험<br>등급 | 상세<br>정보 |")
```

### history_checker/constants.py
```python
# Power Automate - crawl-history workflow (airflow-dag-report 복사본)
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or "https://default0cad3bb20c3d4882aa6b714ad34b84.eb.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/4420c93378d24e25ac55b5b38f4381d6/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=qt-4cz7TriRgbxUxBZppUmApO19eMFFIXJSmWkG1DGw"
```

---

## 🚀 배포 절차

### 1. 코드 커밋
```bash
git add airflow_dag_monitor/utils/formatter.py \
        history_checker/utils/teams_formatter_v3.py \
        history_checker/constants.py

git commit -m "Update monitoring systems UI formatting

- airflow_dag_monitor: KPI 카드 순서 변경 (성공-실패-진행중), 제목 밑으로 이동
- history_checker: 테이블 헤더 줄바꿈 수정 (고객사/코드, 연속/실패일수, 첫/실패일, 위험/등급, 상세/정보)
- history_checker: Webhook URL 업데이트 (airflow-dag-report 복사본)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Commit: `cb3e8569`

### 2. 배포 실행
```bash
# 동시 배포 (3개 Git Bash 창에서)

# Terminal 1
cd airflow_dag_monitor && bash deploy.sh

# Terminal 2
cd history_checker && bash deploy.sh

# Terminal 3
cd converter_failure_monitor && bash deploy.sh
```

**배포 완료 시간**: 2025-11-17 20:xx

---

## ✅ 배포 검증

### 배포 성공 확인
```bash
# Cloud Run Jobs 확인
gcloud run jobs list --region=asia-northeast3 | grep -E "airflow-dag|history|converter"

# Schedulers 확인 (airflow, converter만)
gcloud scheduler jobs list --location=asia-northeast3 | grep -E "airflow|converter"
```

### 예상 결과
```
✅ airflow-dag-monitor-job
✅ ops-send-crawl-history-runjob
✅ converter-failure-monitor
```

### 수동 테스트
```bash
# 1. Airflow DAG Monitor
gcloud run jobs execute airflow-dag-monitor-job --region=asia-northeast3 --wait

# 2. History Checker (INGESTION_DATE 필요)
gcloud run jobs execute ops-send-crawl-history-runjob \
  --region=asia-northeast3 \
  --update-env-vars INGESTION_DATE=20251116 \
  --wait

# 3. Converter Failure Monitor
gcloud run jobs execute converter-failure-monitor --region=asia-northeast3 --wait
```

---

## 📊 시스템 아키텍처 비교

### Airflow DAG Monitor
```
GCP Scheduler (08:30 AM)
  ↓
Cloud Run Job: airflow-dag-monitor-job
  ↓
Power Automate: airflow-dag-report-to-teams
  ↓
Teams (Hyperlounge 채널)
```

### History Checker
```
Power Automate: Trigger History Check API Daily
  ↓
Cloud Run Job: ops-send-crawl-history-runjob
  ↓
Power Automate: crawl-history-report-to-teams (NEW: 4420c933...)
  ↓
Teams (Hyperlounge 채널)
```

### Converter Failure Monitor
```
GCP Scheduler (08:36 AM)
  ↓
Cloud Run Job: converter-failure-monitor
  ↓ (GCS Config 로드)
gs://hyperlounge-converter-monitor-config/config.json
  ↓ (LLM 분석)
Vertex AI: Claude Sonnet 4.5
  ↓
Power Automate: converter-monitoring-report-to-teams
  ↓
Teams (Hyperlounge 채널)
```

---

## 🎨 Teams 메시지 포맷

### 공통 스타일
- **KPI 카드**: HTML `<table>` 형식
- **색상**:
  - 성공: `#36B37E` (녹색)
  - 실패: `#DE350B` (빨강)
  - 진행중: `#0747A6` (파랑)

### Airflow DAG Monitor
```
📊 Airflow 주간 배치 현황 - 2025-11-17 배치 기준
---
🚨 11/17 배치 요약

┌─────────┬─────────┬─────────┐
│    5    │    0    │    1    │
│  성공   │  실패   │ 진행중  │
└─────────┴─────────┴─────────┘
총 22개 배치
---
[주간 배치 표]
✅ 성공  ❌ 실패  🏃‍♂️ 진행중  ❓ 미실행  🌙 휴일
```

### History Checker
```
📊 수집 실패 리포트 - 2025-11-16
---
┌─────────┬─────────┐
│    4    │    1    │
│실패 파일│실패 고객│
└─────────┴─────────┘
---
🔴 [RPA] - 1개 고객사
[테이블: 고객사/코드, 연속/실패일수, 첫/실패일, 위험/등급, 상세/정보]
---
🟢 [Board] - 없음
```

### Converter Failure Monitor
```
📊 Converter 실패 리포트 - 2025-11-17
---
┌─────────┬─────────┬─────────┐
│    5    │    3    │   12    │
│실패 파일│실패 고객│실패 건수│
└─────────┴─────────┴─────────┘
---
🤖 [AI 분석]
1. .xlsb 파일 형식 오류 (5건, 42%)
   ▪ 영향: ...
   ▪ 패턴: ...
   ▪ 조치: ...
```

---

## 🔧 트러블슈팅

### 1. Power Automate Webhook 오류
**증상**: Teams 메시지 전송 안 됨

**확인**:
```bash
# History Checker
gsutil cat gs://hyperlounge-converter-monitor-config/config.json | grep teams_webhook_url

# Converter
python converter_failure_monitor/test_teams.py
```

**해결**:
- Workflow ID 확인
- `{"text": "메시지"}` 형식 사용 (OLD 스키마 아님!)

### 2. 테이블 헤더 깨짐
**증상**: `고객사코/드`, `위험등/급` 등 이상한 위치에서 줄바꿈

**원인**: Teams Markdown 자동 줄바꿈

**해결**: `<br>` 태그로 직접 지정
```markdown
| 고객사<br>코드 | 위험<br>등급 |
```

### 3. KPI 카드가 텍스트로 표시
**증상**: HTML 테이블이 렌더링 안 됨

**원인**: Power Automate workflow가 Markdown만 지원

**해결**:
- Workflow 설정에서 HTML 허용
- 또는 Adaptive Card 형식 사용

### 4. Cloud Run Job 실행 실패
**확인**:
```bash
# 로그 확인
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=converter-failure-monitor' \
  --limit 50

# 실행 이력
gcloud run jobs executions list \
  --job=converter-failure-monitor \
  --region=asia-northeast3 \
  --limit=5
```

---

## 📝 유지보수

### Config 업데이트 (Converter만)
```bash
# 1. config.json 수정
vi converter_failure_monitor/config.json

# 2. GCS 업로드 (재배포 불필요!)
cd converter_failure_monitor
python upload_config.py

# 3. 다음 스케줄 실행 시 자동 반영 (08:36 AM)
```

### 코드 업데이트 (모든 시스템)
```bash
# 1. 코드 수정
vi airflow_dag_monitor/utils/formatter.py

# 2. 커밋
git add ... && git commit -m "..."

# 3. 재배포
cd airflow_dag_monitor && bash deploy.sh
```

---

## 📞 참고 문서

### Airflow DAG Monitor
- 배포 가이드: `airflow_dag_monitor/deploy.sh`
- 포맷터: `airflow_dag_monitor/utils/formatter.py`

### History Checker
- 배포 가이드: `history_checker/deploy.sh`
- 통합 문서: `history_checker/TEAMS_INTEGRATION_DESIGN.md`
- 포맷터: `history_checker/utils/teams_formatter_v3.py`

### Converter Failure Monitor
- 첫 배포: `converter_failure_monitor/FIRST_DEPLOYMENT.md`
- 배포 요약: `converter_failure_monitor/DEPLOYMENT_SUMMARY.md`
- 운영 가이드: `converter_failure_monitor/DEPLOYMENT_GUIDE.md`
- LLM 통합: `converter_failure_monitor/LLM_INTEGRATION.md`

---

## ✨ 다음 단계

### 단기 (1주일)
1. ✅ 매일 Teams 메시지 확인
2. ✅ KPI 카드 렌더링 확인
3. ✅ LLM 분석 품질 확인 (Converter)

### 중기 (1개월)
1. 필요시 프롬프트 튜닝 (Converter)
2. 대시보드 필요성 재평가
3. 알림 임계값 조정

### 장기
1. 실패 패턴 분석
2. 자동 조치 기능 추가
3. Slack 연동 검토

---

**작성일**: 2025-11-17
**작성자**: Claude Code
**버전**: 1.0
**마지막 커밋**: cb3e8569
