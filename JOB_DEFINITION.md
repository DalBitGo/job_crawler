# 박준현 직무 정의서

> **직책**: 플랫폼 엔지니어 / 데이터 파이프라인 총괄
> **경력**: 3년차
> **소속**: 하이퍼라운지 플랫폼팀
> **작성일**: 2026-01-23

---

## 1. 핵심 역할 요약

**RPA + 데이터 파이프라인 + 인프라 운영**을 총괄하는 풀스택 플랫폼 엔지니어

한 문장 정의:
> "RPA 봇 개발부터 데이터 파이프라인 설계, GCP 인프라 운영까지 전체 데이터 플랫폼을 총괄하는 플랫폼 엔지니어"

---

## 2. 담당 시스템 개요

### hyperloungescripts (80+ 마이크로서비스)

| 영역 | 시스템 | 역할 |
|------|--------|------|
| **데이터 수집** | `collector`, `email-collector-v2` | 다양한 소스에서 데이터 수집 |
| **데이터 변환** | `unified-converter`, `converter_failure_monitor` | 3개 Cloud Function → 1개 Cloud Run 통합 |
| **태깅 시스템** | `tagging_tool`, `tag_preprocessing` | 데이터 태깅 및 전처리 |
| **파이프라인** | `airflow-dags` | 22개 고객사 DAG 관리 |
| **모니터링** | `airflow_dag_monitor`, `history_checker` | 파이프라인 상태 모니터링 |
| **API Gateway** | `api-gateway`, `apigee`, `krakend` | API 라우팅 및 인증 |
| **데이터 싱크** | `pvcsync`, `postgres_sync`, `sync_bq2pg_table_caller` | BigQuery ↔ PostgreSQL 동기화 |
| **보안/인프라** | `key_rotator`, `iam_automation`, `keycloak` | 키 관리, IAM, SSO |
| **LLM 서비스** | `llm_service`, `llm-converter-backfill-job` | LLM 기반 데이터 변환 |

### collect-manager (API 서버)
- Flask 기반 REST API 서버
- Collection Item 관리 API
- GCP 인증 연동

### 하이퍼라운지 RPA
- UiPath 기반 RPA 봇 개발 및 운영
- 고객사 VM 관리
- Board 수집 자동화

---

## 3. 담당 업무 상세

### 3.1 데이터 파이프라인 아키텍처 설계 및 개발

**파이프라인 플로우**:
```
Crawler → FileID Mapping → Filter → Convert → Tag → Tag-Prep → Load → Transform → Sync
```

**주요 성과 - Unified Converter 개발**:
| 지표 | Before | After | 개선율 |
|------|--------|-------|--------|
| API 호출 | 3회 | 1회 | 67% 감소 |
| Airflow Task | 6-8개 | 2-3개 | 75% 감소 |
| 지연 시간 | ~5분 | ~2분 | 60% 단축 |
| 장애 포인트 | 3개 | 1개 | 67% 감소 |

### 3.2 Airflow DAG 관리
- 22개 고객사 DAG 운영 및 유지보수
- DAG 모니터링 시스템 개발 (`airflow_dag_monitor`)
- Backfill 가이드 및 운영 절차 수립

### 3.3 모니터링 시스템 구축

| 시스템 | 역할 |
|--------|------|
| `history_checker` | 파이프라인 이력 추적 |
| `history_checker_nonrpa` | Non-RPA 파이프라인 모니터링 |
| `converter_failure_monitor` | 변환 실패 알림 |
| `sli_slo` | 서비스 수준 지표 관리 |

### 3.4 인프라 운영 (GCP)

| 서비스 | 용도 |
|--------|------|
| Cloud Run | 서비스 배포 및 스케일링 |
| Cloud Functions | 서버리스 함수 관리 |
| Cloud Composer | Airflow 환경 운영 |
| BigQuery | 데이터 웨어하우스 |
| Cloud SQL | PostgreSQL 관리 |
| GCS | 오브젝트 스토리지 |
| Pub/Sub | 메시지 큐 |

### 3.5 RPA 프로젝트 총괄
- UiPath 기반 RPA 봇 개발 및 운영
- 고객사 VM 관리 (Anydesk)
- 보안 업데이트 및 2FA 인증 관리
- Board 수집 자동화

### 3.6 문서화 및 이슈 관리
- 아키텍처 문서 작성 (Cloud Run Job, SSH V2)
- 이슈 해결 리포트 (TCP Timeout, HAI Renamer 중복 등)
- 모니터링 가이드 작성

---

## 4. 기술 스택

| 분류 | 기술 |
|------|------|
| **언어** | Python, SQL |
| **클라우드** | GCP (Cloud Run, Cloud Functions, BigQuery, Composer, GCS, Pub/Sub) |
| **데이터 파이프라인** | Apache Airflow, Dataform |
| **데이터베이스** | BigQuery, PostgreSQL, Firestore |
| **API** | Flask, FastAPI |
| **RPA** | UiPath |
| **인프라** | Docker, Cloud Build, IAM, Keycloak |
| **모니터링** | Cloud Logging, Custom Monitoring Scripts |
| **AI/ML** | LLM 기반 데이터 변환 |

---

## 5. 주요 성과/프로젝트

| 프로젝트 | 설명 | 임팩트 |
|----------|------|--------|
| Unified Converter | 3개 CF → 1개 Cloud Run 통합 | 성능 60% 개선, 유지보수 단순화 |
| SSH V2 설계 | 보안 연결 아키텍처 재설계 | 보안 강화, 연결 안정성 향상 |
| Cloud Run Job 아키텍처 | 배치 처리 시스템 설계 | 대용량 처리 지원 |
| LLM Convert 서비스 | AI 기반 데이터 변환 | 자동화 범위 확대 |
| 모니터링 시스템 | 실시간 파이프라인 상태 추적 | 장애 대응 시간 단축 |

---

## 6. 일일 업무 비율 (추정)

```
파이프라인 운영/모니터링  ████████░░  40%
개발/개선 작업            ██████░░░░  30%
이슈 대응/트러블슈팅      ████░░░░░░  20%
문서화/미팅               ██░░░░░░░░  10%
```

---

## 7. 직무 키워드

- Data Pipeline Engineering
- ETL/ELT Architecture
- Cloud Infrastructure (GCP)
- Workflow Orchestration (Airflow)
- RPA Development (UiPath)
- API Development
- Monitoring & Observability
- DevOps Practices

---

*마지막 업데이트: 2026-01-23*
