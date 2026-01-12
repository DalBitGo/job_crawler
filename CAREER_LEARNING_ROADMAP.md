# Career Learning Roadmap

**목표**: 이직 준비를 위한 체계적인 학습 및 포트폴리오 구축

**Last Updated**: 2025-01-12

---

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Career Learning Strategy                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [1] hl-learn          [2] projects           [3] oss           │
│  ┌───────────┐         ┌───────────┐         ┌───────────┐     │
│  │ 실무 기반  │         │ 개인 프로젝트│         │ OSS 분석  │     │
│  │ 클론 코딩  │    +    │ 포트폴리오 │    +    │ 아키텍처  │     │
│  │           │         │           │         │ 학습      │     │
│  └─────┬─────┘         └─────┬─────┘         └─────┬─────┘     │
│        │                     │                     │           │
│        └─────────────────────┴─────────────────────┘           │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │   Portfolio     │                         │
│                    │   + Interview   │                         │
│                    │   Ready         │                         │
│                    └─────────────────┘                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Track 1: hl-learn (실무 기반 학습)

> **목표**: 회사 실무 코드 패턴을 익히고, 유사한 프로젝트를 직접 구현하여 포트폴리오화

### 현재 진행 상황

| 카테고리 | 학습 문서 | 상태 |
|---------|----------|------|
| **Backend** | Django 아키텍처, 권한 시스템, 모델 상속 | 완료 |
| **Data** | VDL, BigQuery, 데이터 파이프라인 | 완료 |
| **Cloud** | Cloud Run, GCS, Cloud SQL | 완료 |
| **Frontend** | React, OAuth, API 연동, SSE | 완료 |
| **Domain** | 비즈니스 도메인 지식 | 완료 |

### Phase 1: 백엔드 클론 프로젝트 (우선순위 높음)

**목표**: Django 기반 실무 패턴을 적용한 미니 프로젝트 구현

```
학습한 내용                    →    구현할 프로젝트
─────────────────────────────────────────────────────
Django 권한 시스템              →    Multi-tenant SaaS 백엔드
Django 모델 상속                →    계층적 데이터 모델 설계
REST API 설계                   →    RESTful API 서버
```

**구현 항목**:
- [ ] Django 프로젝트 셋업 (Docker, PostgreSQL)
- [ ] 사용자 인증/권한 시스템 (JWT, Role-based)
- [ ] 테넌트 기반 데이터 분리
- [ ] API 문서화 (Swagger/OpenAPI)
- [ ] 테스트 코드 작성 (pytest)

**기술 스택**: Django, DRF, PostgreSQL, Docker, Redis

---

### Phase 2: 데이터 파이프라인 클론 프로젝트

**목표**: VDL 시스템과 유사한 데이터 파이프라인 구현

```
학습한 내용                    →    구현할 프로젝트
─────────────────────────────────────────────────────
VDL 3계층 (S/H/RPT)            →    데이터 레이크 파이프라인
증분 처리, BSDA                 →    Change Data Capture
BigQuery CLONE/SNAPSHOT         →    dbt + Snowflake/BigQuery
```

**구현 항목**:
- [ ] 데이터 수집 레이어 (Airbyte/Singer)
- [ ] 변환 레이어 (dbt)
- [ ] 증분 처리 로직
- [ ] 대시보드 연동 (Metabase/Superset)

**기술 스택**: dbt, BigQuery/Snowflake, Airflow, Python

---

### Phase 3: 프론트엔드 클론 프로젝트

**목표**: React 기반 대시보드 UI 구현

```
학습한 내용                    →    구현할 프로젝트
─────────────────────────────────────────────────────
React + OAuth                   →    인증 플로우 구현
SSE 실시간 업데이트              →    실시간 대시보드
API 연동 패턴                   →    데이터 시각화 대시보드
```

**구현 항목**:
- [ ] React 프로젝트 셋업 (Vite, TypeScript)
- [ ] OAuth 2.0 로그인 (Google/GitHub)
- [ ] 차트 라이브러리 연동 (Recharts/Chart.js)
- [ ] SSE 기반 실시간 업데이트

**기술 스택**: React, TypeScript, TailwindCSS, Recharts

---

## Track 2: projects (개인 프로젝트)

> **목표**: 완성도 높은 포트폴리오 프로젝트 구축

### 현재 프로젝트 현황

| 프로젝트 | 상태 | 진행도 | 우선순위 |
|---------|------|--------|---------|
| **realtime-crypto-pipeline** | Active | 40% | 1순위 |
| **StoreBridge** | Paused | 70% | 2순위 (사업자등록 후) |
| **focus-reader** | Merged | 100% | - |
| **youtube-project** | Paused | 20% | 낮음 |
| **project-inspector** | Paused | 60% | 낮음 |

### Phase 1: Realtime Crypto Pipeline 완성 (현재 진행 중)

**포트폴리오 가치**: 데이터 엔지니어링 핵심 역량 증명

```
현재 완료                      →    남은 작업
─────────────────────────────────────────────────────
WebSocket 실시간 수집           →    PostgreSQL 저장
Docker Compose 인프라           →    Grafana 대시보드
                               →    Airflow DAG 구현
                               →    데이터 품질 체크
```

**목표 아키텍처**:
```
Binance WS → Collector → PostgreSQL → Grafana
                ↓
            Airflow (집계/품질)
```

**완료 기준**:
- [ ] 실시간 데이터 저장 (TimescaleDB/PostgreSQL)
- [ ] Grafana 실시간 대시보드
- [ ] Airflow DAG (시간별/일별 집계)
- [ ] 데이터 품질 모니터링
- [ ] README + 아키텍처 문서 완성

---

### Phase 2: StoreBridge 재개 (사업자등록 후)

**포트폴리오 가치**: 풀스택 + API 연동 역량

```
완료된 부분                    →    남은 작업
─────────────────────────────────────────────────────
아키텍처 설계                   →    실제 API 연동
Rate Limiter, Option Mapper     →    Celery Workers
Unit Tests (47/47)              →    프론트엔드 대시보드
```

---

### 새로운 프로젝트 아이디어 (Optional)

| 프로젝트 | 학습 가치 | 난이도 |
|---------|----------|--------|
| **분산 웹 크롤러** | Celery, 분산 처리 | ★★★ |
| **API Gateway** | 마이크로서비스, Kong/Nginx | ★★★★ |
| **로그 분석 시스템** | ELK, ClickHouse | ★★★★ |
| **코드 리뷰 에이전트** | LLM, GitHub API | ★★★ |

---

## Track 3: oss (오픈소스 분석)

> **목표**: 대규모 프로젝트의 아키텍처 이해, 설계 패턴 학습

### 완료된 분석

| 프로젝트 | 카테고리 | 핵심 학습 |
|---------|----------|----------|
| **mini-sglang** | LLM 서빙 | 런타임 최적화, 배칭 |
| **crawl4ai** | 웹 크롤링 | LLM 친화적 데이터 추출 |
| **exo** | 분산 시스템 | 분산 AI 클러스터 |
| **unsloth** | ML Ops | 파인튜닝 최적화 |
| **chatterbox** | AI/Audio | TTS 파이프라인 |
| **cocoindex** | 데이터 처리 | Rust, 데이터 변환 |
| **dify** | 플랫폼 | 에이전트 워크플로우 |

### 다음 분석 후보

| 프로젝트 | Stars | 학습 포인트 |
|---------|-------|------------|
| **DeepSeek-V3** | 100K+ | MoE 아키텍처 |
| **OpenHands** | 60K+ | AI 개발 플랫폼 |
| **n8n** | 63K+ | 워크플로우 자동화 |
| **CrewAI** | 38K+ | 멀티에이전트 |

### 분석 방법론

```
1. README/Docs 읽기 → 프로젝트 목적 이해
2. 폴더 구조 분석 → 아키텍처 파악
3. 핵심 코드 리딩 → 설계 패턴 학습
4. 문서 작성 → 나만의 언어로 정리
```

---

## Timeline & Milestones

### 2025 Q1 (1-3월)

```
Month 1 (January)
├── [projects] Realtime Crypto Pipeline 완성
├── [hl-learn] 백엔드 클론 프로젝트 시작
└── [oss] DeepSeek-V3 분석

Month 2 (February)
├── [hl-learn] 백엔드 클론 프로젝트 완성
├── [hl-learn] 데이터 파이프라인 클론 시작
└── [oss] OpenHands 분석

Month 3 (March)
├── [hl-learn] 데이터 파이프라인 클론 완성
├── [projects] 포트폴리오 정리
└── 이력서/포트폴리오 준비
```

### 2025 Q2 (4-6월)

```
├── 이직 활동 시작
├── [projects] StoreBridge 재개 (사업자등록 시)
├── [hl-learn] 프론트엔드 클론 프로젝트
└── 기술 면접 준비
```

---

## Weekly Schedule

```
주중 (월-금)
├── 회사 업무
├── 퇴근 후 1-2시간: hl-learn 학습/구현
└── 이동 시간: 기술 블로그/문서 읽기

주말 (토-일)
├── 토요일 오전: projects 사이드 프로젝트
├── 토요일 오후: oss 분석
└── 일요일: 정리/문서화
```

**시간 배분**:
- hl-learn: 40% (실무 역량)
- projects: 40% (포트폴리오)
- oss: 20% (아키텍처 학습)

---

## Tech Stack Summary

### 현재 보유 스킬

| Category | Skills |
|----------|--------|
| **Backend** | Django, FastAPI, Python |
| **Database** | PostgreSQL, BigQuery |
| **Cloud** | GCP (Cloud Run, GCS, Cloud SQL) |
| **Data** | Dataform, dbt 기초 |
| **Frontend** | React 기초 |
| **DevOps** | Docker, GitHub Actions |

### 목표 스킬 (보강 필요)

| Category | Skills | 학습 방법 |
|----------|--------|----------|
| **Backend** | Node.js, Go | 사이드 프로젝트 |
| **Data** | Airflow, Kafka | Crypto Pipeline |
| **Cloud** | AWS, Kubernetes | 개인 프로젝트 배포 |
| **Frontend** | TypeScript, Next.js | 클론 프로젝트 |

---

## Portfolio Checklist

이직 시 보여줄 수 있는 항목:

### 1. GitHub 프로젝트

- [ ] **realtime-crypto-pipeline**: 실시간 데이터 파이프라인
  - README with architecture diagram
  - 동작하는 데모 (Docker Compose)
  - 기술 블로그 포스트

- [ ] **hl-learn 클론 프로젝트**: Django 백엔드
  - 실무 패턴 적용
  - 테스트 커버리지 80%+
  - API 문서화

- [ ] **StoreBridge**: 풀스택 자동화 도구
  - 아키텍처 문서
  - 테스트 코드

### 2. 기술 문서

- [ ] 시스템 설계 문서 (hl-learn/docs)
- [ ] OSS 분석 보고서 (oss/projects)
- [ ] 기술 블로그 포스트 (Optional)

### 3. 면접 준비

- [ ] 시스템 설계 질문 대비
- [ ] 프로젝트 설명 스크립트
- [ ] 기술 스택별 심화 질문 대비

---

## Notes

### 핵심 원칙

1. **한 번에 하나씩** - 여러 프로젝트 동시 진행 금지
2. **완성 우선** - 새 프로젝트보다 기존 프로젝트 완성
3. **문서화** - 배운 것은 반드시 기록
4. **실전 지향** - 이론보다 구현 우선

### 위험 요소

- 너무 많은 것을 동시에 하려고 함
- 완성 없이 새 프로젝트 시작
- 문서화 미루기

### 성공 지표

- 완성된 프로젝트 수
- GitHub 커밋 그래프
- 정리된 문서 수

---

**Remember**: 완성된 하나가 미완성 열 개보다 낫다.
