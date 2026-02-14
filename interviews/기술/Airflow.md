# Airflow 면접 준비

---

## 기본 개념 질문

### Q1: Airflow란 무엇인가요?
**A**:
- Apache Airflow는 워크플로우 오케스트레이션 플랫폼
- DAG(Directed Acyclic Graph)로 작업 의존성 정의
- 스케줄링, 모니터링, 재실행 기능 제공

**내 경험 연결**:
> "22개 고객사의 데이터 파이프라인을 Airflow로 관리했습니다.
> 각 고객사별 DAG를 분리하고, 공통 로직은 재사용 가능한 Operator로 구현했습니다."

---

### Q2: DAG란 무엇인가요?
**A**:
- Directed Acyclic Graph (방향성 비순환 그래프)
- Task들의 의존 관계를 정의
- 순환 참조 불가 (A→B→A 불가)

---

### Q3: Executor 종류와 차이점?
**A**:
| Executor | 특징 | 사용 케이스 |
|----------|------|-------------|
| SequentialExecutor | 순차 실행 | 개발/테스트 |
| LocalExecutor | 로컬 병렬 실행 | 소규모 |
| CeleryExecutor | 분산 처리 | 대규모 |
| KubernetesExecutor | K8s Pod 실행 | 클라우드 |

---

### Q4: XCom이란?
**A**:
- Task 간 데이터 전달 메커니즘
- 작은 데이터만 (대용량은 외부 저장소 사용)
- `xcom_push`, `xcom_pull` 사용

---

## 실무 경험 질문

### Q5: Airflow에서 어려웠던 점과 해결 방법?
**A**:
> "22개 고객사 DAG를 운영하면서 백필(Backfill) 관리가 어려웠습니다.
> 해결: catchup=False 설정하고, 필요시 CLI로 수동 백필 실행.
> 모니터링 대시보드를 만들어 DAG 상태를 한눈에 확인할 수 있게 했습니다."

---

### Q6: DAG 성능 최적화 경험?
**A**:
- Pool 사용으로 동시 실행 Task 제한
- 병렬화 가능한 Task는 병렬 처리
- SLA 설정으로 지연 알림

---

### Q7: 장애 대응 경험?
**A**:
> "DAG 실패 시 Slack 알림 설정,
> 모니터링 시스템 4개 직접 개발해서
> 장애 감지 시간을 크게 단축했습니다."

---

## 심화 질문

### Q8: Airflow 2.x의 주요 변경점?
**A**:
- TaskFlow API (데코레이터 기반)
- Full REST API
- Scheduler HA
- Smart Sensor

---

### Q9: Airflow vs Prefect vs Dagster?
**A**:
| 도구 | 장점 | 단점 |
|------|------|------|
| Airflow | 성숙한 생태계, 커뮤니티 | 복잡한 설정 |
| Prefect | 현대적 API, 동적 워크플로우 | 상대적으로 작은 생태계 |
| Dagster | 타입 시스템, 테스트 용이 | 학습 곡선 |

---

## 내 강점 어필 포인트

1. **22개 고객사 DAG 운영** - 대규모 멀티테넌트 경험
2. **모니터링 시스템 4개 개발** - 문제 해결 능력
3. **Unified Converter 개발** - 3개 서비스 통합, 60% 성능 개선

---

*마지막 업데이트: 2026-01-28*
