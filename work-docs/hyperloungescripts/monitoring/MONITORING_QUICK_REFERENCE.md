# 모니터링 시스템 Quick Reference

## 🚀 빠른 명령어

### 수동 실행
```bash
# Airflow DAG Monitor
gcloud run jobs execute airflow-dag-monitor-job --region=asia-northeast3 --wait

# History Checker (어제 날짜)
gcloud run jobs execute ops-send-crawl-history-runjob --region=asia-northeast3 --wait

# History Checker (특정 날짜)
gcloud run jobs execute ops-send-crawl-history-runjob \
  --region=asia-northeast3 \
  --update-env-vars INGESTION_DATE=20251116 \
  --wait

# Converter Failure Monitor
gcloud run jobs execute converter-failure-monitor --region=asia-northeast3 --wait
```

### 로그 확인
```bash
# Airflow DAG Monitor
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=airflow-dag-monitor-job' \
  --limit 50

# History Checker
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=ops-send-crawl-history-runjob' \
  --limit 50

# Converter Failure Monitor
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=converter-failure-monitor' \
  --limit 50
```

### 재배포
```bash
cd /mnt/c/Users/박준현/Desktop/hyperloungescripts/hyperloungescripts

# Airflow DAG Monitor
cd airflow_dag_monitor && bash deploy.sh && cd ..

# History Checker
cd history_checker && bash deploy.sh && cd ..

# Converter Failure Monitor
cd converter_failure_monitor && bash deploy.sh && cd ..
```

---

## 📊 시스템 정보

| 시스템 | Job 이름 | 스케줄 | 시간 (KST) | 트리거 |
|--------|----------|--------|-----------|--------|
| Airflow DAG | airflow-dag-monitor-job | 매일 | 08:30 AM | GCP Scheduler |
| History Checker | ops-send-crawl-history-runjob | 매일 | 09:00 AM (추정) | Power Automate |
| Converter | converter-failure-monitor | 매일 | 08:36 AM | GCP Scheduler |

---

## 🔧 문제 발생 시

### Teams 메시지 안 옴
1. Cloud Run Job 로그 확인
2. Power Automate workflow 실행 이력 확인
3. Webhook URL 확인

### 실행 실패
1. 로그에서 에러 확인
2. Service Account 권한 확인
3. 수동 실행 테스트

### Config 수정 (Converter만)
```bash
cd converter_failure_monitor
vi config.json
python upload_config.py
```

---

## 📞 Power Automate Workflows

| 시스템 | Workflow 이름 | Workflow ID |
|--------|--------------|-------------|
| Airflow DAG | airflow-dag-report-to-teams | 06478634e746... |
| History Checker | crawl-history-report-to-teams | 4420c93378d2... |
| Converter | converter-monitoring-report-to-teams | 62fbc41220c0... |

---

## 🎯 일반적인 작업

### 스케줄러 목록 확인
```bash
gcloud scheduler jobs list --location=asia-northeast3
```

### Cloud Run Jobs 목록
```bash
gcloud run jobs list --region=asia-northeast3 | grep -E "monitor|history|converter"
```

### 최근 실행 이력
```bash
# Airflow DAG
gcloud run jobs executions list \
  --job=airflow-dag-monitor-job \
  --region=asia-northeast3 \
  --limit=5

# History Checker
gcloud run jobs executions list \
  --job=ops-send-crawl-history-runjob \
  --region=asia-northeast3 \
  --limit=5

# Converter
gcloud run jobs executions list \
  --job=converter-failure-monitor \
  --region=asia-northeast3 \
  --limit=5
```

---

**마지막 업데이트**: 2025-11-17
