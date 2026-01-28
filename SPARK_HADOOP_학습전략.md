# Spark/Hadoop Gap 학습 전략

> **목표**: Data Engineer 공고 필수 요건 충족
> **현재 수준**: Airflow ✅, Kafka △ (학습중), Spark/Hadoop ✗
> **목표 기간**: 4주

---

## 1. 왜 Spark/Hadoop인가?

### 공고 요구사항 분석
```
현대오토에버: "Hadoop, Hive, Spark 기반 데이터 처리 시스템 구축/운영 경험"
카카오뱅크:   "Hadoop, Kafka, Spark, SQL, Airflow 등 대용량 데이터 처리"
당근:        "Hadoop MR, Hive, Spark, Flink 사용 경험"
쿠팡:        "EMR, Spark, Hive 또는 기타 빅데이터 프레임워크"
```

### 핵심 포인트
- **Spark**가 거의 모든 공고에서 언급됨
- Hadoop은 "에코시스템 이해" 수준 요구
- 실제 운영보다 "경험" 자체가 중요

---

## 2. 학습 전략: 프로젝트 기반

### 2.1 realtime-crypto-pipeline 활용 (최우선)

```
현재 상태:
Phase 1: MVP (PostgreSQL)     ✅ 완료
Phase 3: Kafka                 △ Producer 완료
         Spark Streaming       ← 여기서 학습!
```

**이게 최고인 이유:**
1. 이미 데이터 소스 있음 (Binance WebSocket)
2. Kafka로 데이터 흐르고 있음
3. Spark Streaming 연결만 하면 됨
4. 포트폴리오 + 학습 동시 해결

### 2.2 구체적 학습 로드맵

```
Week 1: Spark 기초
├── PySpark 설치 및 환경 설정
├── DataFrame API 기초
├── Spark SQL 기초
└── 로컬에서 간단한 처리 실습

Week 2: Spark Streaming + Kafka 연동
├── Structured Streaming 개념
├── Kafka Consumer 연결
├── 실시간 데이터 처리
└── realtime-crypto-pipeline에 적용

Week 3: 집계 및 윈도우 처리
├── Window 함수 (Tumbling, Sliding)
├── 1분/5분 캔들 생성
├── Watermark 처리
└── 결과를 DB에 저장

Week 4: 최적화 및 정리
├── 성능 튜닝 기초
├── 처리량 측정 (면접용 숫자)
├── README 정리
└── 면접 대비 정리
```

---

## 3. 학습 자료

### 3.1 kb 폴더 활용
```
/home/junhyun/kb/Apache-Spark/       ← 먼저 확인
/home/junhyun/kb/Kafka-Stream-Processing/
```

### 3.2 추천 자료

**입문 (1-2일)**
- Spark 공식 Quick Start
- PySpark DataFrame 튜토리얼

**실전 (1주)**
- Structured Streaming Programming Guide
- Kafka + Spark 연동 예제

**심화 (필요시)**
- Spark The Definitive Guide (책)
- 데이터브릭스 블로그

### 3.3 실습 환경

```python
# Docker로 로컬 Spark 환경
# docker-compose.yml에 추가
spark-master:
  image: bitnami/spark:latest
  ports:
    - "8080:8080"
    - "7077:7077"
```

---

## 4. Hadoop 에코시스템 이해

### 4.1 알아야 할 것 (개념 수준)

| 컴포넌트 | 역할 | 면접 한 줄 |
|---------|------|-----------|
| HDFS | 분산 파일 시스템 | "대용량 파일을 여러 노드에 분산 저장" |
| YARN | 리소스 관리 | "클러스터 리소스를 관리하고 작업 스케줄링" |
| Hive | SQL on Hadoop | "HDFS 위에서 SQL로 쿼리" |
| Spark | 인메모리 처리 | "메모리 기반으로 빠른 배치/스트리밍 처리" |

### 4.2 실제로 해볼 것

```
실습 우선순위:
1. Spark (PySpark) - 직접 코딩  ⭐ 필수
2. Spark SQL - 쿼리 작성       ⭐ 필수
3. Hive - 개념 이해 + 간단 실습
4. HDFS - 개념만 이해 (클라우드에선 S3/GCS 대체)
```

---

## 5. 면접 대비 포인트

### 5.1 경험 없을 때 답변 전략

**Bad:**
> "Spark 경험 없습니다"

**Good:**
> "실무에서는 BigQuery와 Airflow로 대용량 데이터를 처리했습니다.
> 현재 개인 프로젝트에서 Kafka + Spark Streaming으로 실시간 파이프라인을 구축 중이며,
> 초당 1만 건 처리를 목표로 하고 있습니다."

### 5.2 면접 예상 질문 + 답변

**Q: Spark 경험이 부족한데요?**
> "BigQuery로 일일 수백만 건 ETL을 처리한 경험이 있어 대용량 데이터 처리 개념은 갖추고 있습니다.
> 현재 개인 프로젝트로 Spark Streaming을 학습 중이며,
> 분산 처리의 핵심인 파티셔닝, 셔플 최소화 개념을 이해하고 있습니다."

**Q: Hadoop과 Spark의 차이는?**
> "Hadoop MR은 디스크 기반으로 중간 결과를 저장해 I/O가 많고,
> Spark는 메모리 기반으로 10-100배 빠릅니다.
> 특히 반복 연산이 많은 ML이나 스트리밍에서 Spark가 유리합니다."

**Q: Spark에서 성능 최적화 방법은?**
> "파티션 수 조정, 브로드캐스트 조인으로 셔플 최소화,
> 캐싱 전략, 그리고 Catalyst 옵티마이저 활용이 핵심입니다."

---

## 6. 현실적인 목표

### 4주 후 도달 목표

```
Spark 이해도:     ★★★☆☆ (면접 가능 수준)
실제 구현 경험:    Kafka → Spark Streaming → DB
처리량 측정:      X,XXX msg/sec (숫자로 어필)
포트폴리오:       realtime-crypto-pipeline Phase 3 완료
```

### 면접에서 말할 수 있는 것

```
"Kafka와 Spark Streaming을 연동하여 실시간 암호화폐 데이터 파이프라인을 구축했습니다.
초당 X천 건의 메시지를 처리하며, 1분/5분 캔들을 실시간으로 생성합니다.
윈도우 함수와 워터마크를 활용해 지연 데이터도 처리합니다."
```

---

## 7. 액션 플랜

### 이번 주 (Week 1)
- [ ] kb/Apache-Spark 폴더 확인
- [ ] PySpark 로컬 환경 설정
- [ ] Spark DataFrame 기초 실습
- [ ] realtime-crypto-pipeline에 Spark 추가 (docker-compose)

### 다음 주 (Week 2)
- [ ] Kafka → Spark Streaming 연동
- [ ] 실시간 데이터 처리 구현
- [ ] 1분 캔들 생성 로직

### 3주차 (Week 3)
- [ ] 5분 캔들 + 윈도우 처리
- [ ] ClickHouse 저장
- [ ] 처리량 측정

### 4주차 (Week 4)
- [ ] 성능 튜닝
- [ ] README 정리
- [ ] 면접 답변 준비

---

## 8. 핵심 메시지

> **"실무 Spark 경험은 없지만, BigQuery + Airflow로 대용량 파이프라인 운영 경험이 있고,
> 현재 Spark Streaming 프로젝트를 진행하며 빠르게 역량을 쌓고 있습니다."**

이 메시지로 Gap을 강점으로 전환!

---

*마지막 업데이트: 2026-01-24*
