# 모니터링 시스템 배포 수정 (2025-11-18)

## 🐛 발견된 문제

2025-11-18 08:36 AM 스케줄 실행 시 2개 시스템에서 오류 발생:

### 1. Converter Failure Monitor - ModuleNotFoundError
**Cloud Run Job**: `converter-failure-monitor`
**실행 시간**: 2025-11-18 08:36 AM KST

**에러 로그**:
```
ModuleNotFoundError: No module named 'converter_failure_monitor'
/usr/local/bin/python: Error while finding module specification for 'converter_failure_monitor.main' (ModuleNotFoundError: No module named 'converter_failure_monitor')
```

**원인**:
- Dockerfile의 COPY 경로가 잘못됨
- `COPY . /app/converter_failure_monitor/` 후 `python -m converter_failure_monitor.main` 실행
- 실제 파일 구조: `/app/converter_failure_monitor/converter_failure_monitor/...` (중복)
- WORKDIR `/app`에서 모듈을 찾을 수 없음

**해결**:
```dockerfile
# Before (WRONG):
COPY . /app/converter_failure_monitor/
CMD ["python", "-m", "converter_failure_monitor.main"]

# After (CORRECT):
COPY . .
CMD ["python", "main.py"]
```

---

### 2. History Checker - Teams 메시지 전송 실패 (400)
**Cloud Run Job**: `ops-send-crawl-history-runjob`
**실행 시간**: 2025-11-18 08:37 AM KST (Power Automate trigger)

**에러 로그**:
```
2025-11-17 23:37:01,323 - DEBUG - https://default0cad3bb20c3d4882aa6b714ad34b84.eb.environment.api.powerplatform.com:443 "POST /powerautomate/automations/direct/workflows/c938d2c3d1d0410aa30c155c6efa9b99/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=GJ0akvQeMqH-KxWAp1SFCXQxUETxzaCjTILxJZyjjgE HTTP/1.1" 400 190
2025-11-17 23:37:01,324 - ERROR - ❌ Teams 메시지 전송 실패 (Status: 400)
```

**원인**:
- **deploy.sh line 31**에 **OLD** webhook URL 하드코딩됨
- OLD workflow ID: `c938d2c3d1d0410aa30c155c6efa9b99`
- NEW workflow ID: `4420c93378d24e25ac55b5b38f4381d6` (airflow-dag-report 복사본)
- constants.py는 NEW URL로 업데이트했지만, deploy.sh가 환경변수로 덮어씀

**아키텍처**:
```
Power Automate: Trigger History Check API Daily
  ↓ (POST with {"type": "rpa", "ingestion_date": "..."})
API Gateway
  ↓
history_checker_caller (Cloud Function)
  ↓
Cloud Run Job: ops-send-crawl-history-runjob
  ↓ (실행 성공, 결과 생성)
Power Automate: crawl-history-report-to-teams (NEW workflow)
  ↓ (하지만 OLD URL 사용 → 400 error)
Teams (메시지 전송 실패)
```

**해결**:
```bash
# deploy.sh line 31
# Before (WRONG):
WEBHOOK_URL="https://default0cad3bb20c3d4882aa6b714ad34b84.eb.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/c938d2c3d1d0410aa30c155c6efa9b99/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=GJ0akvQeMqH-KxWAp1SFCXQxUETxzaCjTILxJZyjjgE"

# After (CORRECT):
WEBHOOK_URL="https://default0cad3bb20c3d4882aa6b714ad34b84.eb.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/4420c93378d24e25ac55b5b38f4381d6/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=qt-4cz7TriRgbxUxBZppUmApO19eMFFIXJSmWkG1DGw"
```

---

## ✅ 수정된 파일

### 1. converter_failure_monitor/Dockerfile
**변경 사항**:
- COPY 경로 단순화: `/app/converter_failure_monitor/` → `.` (WORKDIR 기준)
- CMD 단순화: `python -m converter_failure_monitor.main` → `python main.py`

### 2. history_checker/deploy.sh
**변경 사항**:
- Line 31: Webhook URL을 OLD → NEW로 변경
- Workflow ID: `c938d2c3d1d0410aa30c155c6efa9b99` → `4420c93378d24e25ac55b5b38f4381d6`

---

## 🚀 재배포 절차

### 1. Converter Failure Monitor
```bash
cd /mnt/c/Users/박준현/Desktop/hyperloungescripts/hyperloungescripts/converter_failure_monitor
bash deploy.sh
```

**예상 결과**:
- Docker image 빌드 성공
- Artifact Registry 푸시 성공
- Cloud Run Job 업데이트 성공
- 다음 스케줄 실행 시 (내일 08:36 AM) 정상 동작

### 2. History Checker
```bash
cd /mnt/c/Users/박준현/Desktop/hyperloungescripts/hyperloungescripts/history_checker
bash deploy.sh
```

**예상 결과**:
- Docker image 빌드 성공
- Artifact Registry 푸시 성공
- Cloud Run Job 업데이트 (환경변수 포함)
- 다음 Power Automate trigger 시 Teams 메시지 전송 성공

---

## 🧪 테스트 방법

### Converter Failure Monitor (수동 실행)
```bash
gcloud run jobs execute converter-failure-monitor --region=asia-northeast3 --wait
```

**성공 확인**:
```bash
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=converter-failure-monitor' \
  --limit 20 \
  --format="table(timestamp,textPayload)"
```

- "✅ Teams 메시지 전송 성공" 로그 확인
- Teams 채널에 메시지 도착 확인

### History Checker (특정 날짜로 수동 실행)
```bash
gcloud run jobs execute ops-send-crawl-history-runjob \
  --region=asia-northeast3 \
  --update-env-vars INGESTION_DATE=20251116 \
  --wait
```

**성공 확인**:
```bash
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=ops-send-crawl-history-runjob' \
  --limit 20 \
  --format="table(timestamp,textPayload)"
```

- "✅ Teams 메시지 전송 성공" 로그 확인
- Teams 채널에 메시지 도착 확인
- Webhook URL에 NEW workflow ID 포함 확인 (`4420c933...`)

---

## 📝 커밋 메시지

```bash
git add converter_failure_monitor/Dockerfile \
        history_checker/deploy.sh

git commit -m "모니터링 시스템 배포 오류 수정

- converter_failure_monitor: Dockerfile COPY 경로 수정 (ModuleNotFoundError 해결)
- history_checker: deploy.sh webhook URL 업데이트 (OLD → NEW workflow)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 🔍 트러블슈팅 가이드

### Converter: ModuleNotFoundError 재발 시
1. Dockerfile의 COPY가 `.`인지 확인
2. CMD가 `python main.py`인지 확인
3. WORKDIR이 `/app`인지 확인
4. 재배포 후 docker image 확인:
   ```bash
   gcloud artifacts docker images list asia-northeast3-docker.pkg.dev/hyperlounge-dev/hyperlounge-repo/converter-failure-monitor
   ```

### History Checker: 400 Error 재발 시
1. deploy.sh line 31의 webhook URL 확인
2. Workflow ID가 `4420c933...`인지 확인
3. Cloud Run Job 환경변수 확인:
   ```bash
   gcloud run jobs describe ops-send-crawl-history-runjob \
     --region=asia-northeast3 \
     --format="value(template.template.containers[0].env)"
   ```
4. 로그에서 실제 사용된 URL 확인:
   ```bash
   gcloud logging read \
     'resource.type=cloud_run_job AND resource.labels.job_name=ops-send-crawl-history-runjob' \
     --limit 50 | grep "POST /powerautomate"
   ```

---

## 📊 시스템 상태 요약

| 시스템 | 상태 | 마지막 성공 실행 | 다음 스케줄 |
|--------|------|------------------|-------------|
| Airflow DAG Monitor | ✅ 정상 | 2025-11-17 08:30 | 2025-11-18 08:30 |
| History Checker | 🔧 수정 필요 | - | Power Automate trigger |
| Converter Monitor | 🔧 수정 필요 | - | 2025-11-18 08:36 |

**재배포 후 예상 상태**:
| 시스템 | 상태 | 비고 |
|--------|------|------|
| Airflow DAG Monitor | ✅ 정상 | 수정 불필요 |
| History Checker | ✅ 정상 | Webhook URL 수정 완료 |
| Converter Monitor | ✅ 정상 | Dockerfile 수정 완료 |

---

**작성일**: 2025-11-18
**작성자**: Claude Code
**관련 문서**:
- `MONITORING_SYSTEMS_UPDATE_20251117.md`
- `MONITORING_QUICK_REFERENCE.md`
- `converter_failure_monitor/DEPLOYMENT_GUIDE.md`
- `history_checker/TEAMS_INTEGRATION_DESIGN.md`
