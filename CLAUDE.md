# Career Hub - 이직 준비 대시보드

> **목표**: Senior Data Engineer 이직 (목표 연봉: 5,500~7,000만원)
> **전략**: 프로젝트 60% + OSS 분석 25% + kb 참고 15%

---

## 현재 상태 (Quick View)

```
┌─────────────────────────────────────────────────────────────┐
│  realtime-crypto-pipeline 진행률                            │
│  ██████████░░░░░░░░░░  50% (Phase 3 진행 중!)               │
│                                                             │
│  Phase 1: MVP (PostgreSQL)  ██████████ 100% ✅ 완료         │
│  Phase 2: Redis Streams     ────────── SKIP                 │
│  Phase 3: Kafka + Spark     ████░░░░░░  40%  ← 현재 진행    │
│  Phase 4: K8s + 모니터링     ░░░░░░░░░░   0%                 │
│  Phase 5: 문서화            ░░░░░░░░░░   0%                  │
└─────────────────────────────────────────────────────────────┘
```

### 이번 주 목표
- [ ] 토스, 당근페이 지원 완료
- [ ] Kafka 환경 테스트 (docker-compose up)
- [ ] Spark 기초 학습 시작

### 다음 할 일 (Next Action)
```
→ 이력서 개인정보 추가 후 토스/당근페이 지원
→ Kafka 테스트 후 Spark 연동
```

---

## Gap 스킬 진행률

| 스킬 | 현재 | 목표 | 진행률 | 학습 방법 |
|------|------|------|--------|-----------|
| **Kafka** | ★★☆☆☆ | ★★★★☆ | ████░░░░░░ 40% | Producer 완료, 테스트 예정 |
| **Spark** | ★☆☆☆☆ | ★★★★☆ | ░░░░░░░░░░ 0% | 이번 주 시작 |
| **Kubernetes** | ★★☆☆☆ | ★★★★☆ | ░░░░░░░░░░ 0% | Phase 4 예정 |
| **dbt** | ★★☆☆☆ | ★★★☆☆ | ░░░░░░░░░░ 0% | 트랙 3 추후 |
| **AWS** | ★☆☆☆☆ | ★★★☆☆ | ░░░░░░░░░░ 0% | GCP 경험으로 대체 |

### 이미 보유 (Phase 1에서 확인)
- ✅ Python asyncio, WebSocket
- ✅ PostgreSQL, asyncpg
- ✅ Airflow DAG
- ✅ Grafana 대시보드
- ✅ Docker Compose

---

## 프로젝트: realtime-crypto-pipeline

> **위치**: `/home/junhyun/projects/realtime-crypto-pipeline`

### 개요
실시간 암호화폐 가격 수집 → Kafka → Spark 처리 → 분석

### 목표 지표 (면접에서 말할 숫자)
| 지표 | 목표 | 현재 |
|------|------|------|
| 처리량 | 10,000 msg/sec | 수천 건/sec (Phase 1) |
| 지연 | < 100ms | - |
| 데이터 | 100GB+ | 수집 중 |

### Phase 상세

#### Phase 1: MVP (PostgreSQL) ✅ 완료!
- [x] Binance WebSocket 실시간 수집 (5개 심볼)
- [x] PostgreSQL 저장 (asyncpg)
- [x] Grafana 대시보드
- [x] Airflow DAG (집계/품질/정리)

#### Phase 2: Redis Streams (선택)
- [ ] Producer/Consumer 분리
- [ ] Redis Streams 메시지 큐
- [ ] TimescaleDB 마이그레이션

#### Phase 3: Kafka + Spark ⭐ 핵심 목표 (진행 중!)
- [x] Kafka 클러스터 구성 (docker-compose) ✅
- [x] Kafka Producer 구현 (aiokafka) ✅
- [ ] Kafka 환경 테스트 (docker-compose up)
- [ ] Spark Streaming Consumer
- [ ] 실시간 캔들 생성 (1분, 5분)
- [ ] ClickHouse 저장

#### Phase 4: K8s + 모니터링
- [ ] Kubernetes 배포
- [ ] Prometheus 메트릭 수집

#### Phase 5: 문서화
- [ ] README 업데이트
- [ ] 아키텍처 다이어그램
- [ ] 성능 벤치마크 결과

---

## OSS 분석 현황

| OSS | 목적 | 상태 | 프로젝트 연계 |
|-----|------|------|---------------|
| **aiokafka** | Kafka Producer 패턴 | ⬜ 예정 | Phase 1 |
| **delta-rs** | 데이터 레이크 | ⬜ 예정 | Phase 3 |
| **bytewax** | Python 스트리밍 | ⬜ 예정 | Phase 2 |

---

## 학습 자료 (kb)

| 토픽 | 위치 | 활용 시점 |
|------|------|-----------|
| Spark | `/home/junhyun/kb/Apache-Spark/` | Phase 2-3 |
| Kafka | `/home/junhyun/kb/Kafka-Stream-Processing/` | Phase 1 |
| K8s | `/home/junhyun/kb/Kubernetes/` | Phase 4 |

---

## 주간 기록

### Week 1 (2026-01-23 ~)
**목표**: Phase 3 (Kafka + Spark) 시작
- [x] 프로젝트 현황 파악 - Phase 1 MVP 완료 확인!
- [x] Phase 2 스킵 결정 → 바로 Kafka!
- [x] Kafka Docker 환경 구성 (Zookeeper + Kafka + UI)
- [x] Kafka Producer 구현 (aiokafka)
- [ ] Kafka 환경 테스트 실행
- [ ] aiokafka OSS 분석 시작

**회고**: (주말에 작성)

---

## 사용자 프로필

| 항목 | 내용 |
|------|------|
| **경력** | 3년차 |
| **현재 직무** | 플랫폼 엔지니어 / 데이터 파이프라인 총괄 (하이퍼라운지) |
| **현재 스킬** | Python, SQL, GCP, Airflow, Docker, PostgreSQL |
| **상세** | → `JOB_DEFINITION.md` |

---

## 채용 공고 관리

> **위치**: `employment/공고/`
> **비교 분석**: `employment/공고_비교분석.md`

### 현재 관심 공고 (우선순위순)

#### 즉시 지원 가능 (Gap 최소) ⭐
| 순위 | 회사 | 포지션 | 매칭도 | 핵심 이유 |
|:----:|------|--------|:------:|----------|
| **1** | 토스 | Data Engineer (Platform) | ★★★★★ | **"Airflow 초급 OK"** 명시! |
| **2** | 당근페이 | 데이터 엔지니어 | ★★★★★ | Airflow 명시, Kafka 우대 |

#### Spark 학습 후 지원
| 순위 | 회사 | 포지션 | 매칭도 | Gap |
|:----:|------|--------|:------:|-----|
| **3** | 카카오뱅크 | 빅데이터 데이터 엔지니어 | ★★★★☆ | Spark |
| **4** | 현대오토에버 | Data Engineer (스마트팩토리) | ★★★★☆ | Hadoop/Spark |
| **5** | 카카오엔터 | Data Engineer | ★★★★☆ | Spark/Flink |

### Gap 보완 우선순위
```
1순위: Kafka → Phase 3 진행 중 (토스/당근페이 지원에 필요)
2순위: Spark → Phase 3 예정 (대부분 공고 요구)
3순위: AWS → GCP 경험으로 대체 가능, 필요시 학습
```

### 공고 폴더 구조
```
employment/
├── 공고/
│   ├── 대기/          # 관심 있는 공고
│   ├── 지원완료/      # 지원한 공고
│   ├── 면접/          # 면접 진행 중
│   └── 최종/          # 최종 결과
└── 템플릿/
    └── 공고_템플릿.md  # 새 공고 등록 시 사용
```

### 지원 준비 체크리스트
- [ ] 이력서 업데이트 (DevOps/Data Engineer 강조)
- [ ] realtime-crypto-pipeline Phase 3 완료
- [ ] GitHub README 정리
- [ ] Kubernetes 기초 학습

---

## 문서 구조

```
career-hub/
├── CLAUDE.md                 # ← 지금 보는 파일 (대시보드)
├── JOB_DEFINITION.md         # 현재 직무 정의
├── SKILL_GAP_ANALYSIS.md     # Gap 분석 상세
├── LEARNING_STRATEGY.md      # 학습 전략 상세
├── CAREER_LEARNING_ROADMAP.md
└── employment/
    ├── 공고/                 # 채용 공고 관리
    │   ├── 대기/
    │   ├── 지원완료/
    │   ├── 면접/
    │   └── 최종/
    ├── 템플릿/
    │   └── 공고_템플릿.md
    └── (기존 크롤러 파일들)
```

---

## 중요 원칙

1. **한 번에 하나씩** - realtime-crypto-pipeline 완성이 최우선
2. **GitHub이 증거** - 매일 커밋, 측정 가능한 결과
3. **막히면 kb** - 구글링 전에 kb 먼저
4. **OSS로 깊이** - "왜 이렇게?" 답할 수 있게

> "완성된 하나가 미완성 열 개보다 낫다"

---

## Claude 작업 요청 예시

```
"이번 주 진행 상황 업데이트해줘"
"Phase 1 다음 할 일 뭐야?"
"Kafka Producer 구현 도와줘"
"aiokafka 소스 분석해줘"
"kb에서 Spark DataFrame 찾아줘"
"진행률 업데이트해줘 - Phase 1 50% 완료"
```

---

*마지막 업데이트: 2026-01-24 (공고 분석 + 이력서 완료)*
*다음 업데이트: 지원 결과 반영*
