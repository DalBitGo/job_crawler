# 이메일 첨부파일 수집 시스템 - 모범 사례 & 벤치마킹

**조사일**: 2026-01-30
**목적**: 프로덕션 수준의 이메일 첨부파일 수집 시스템 구축을 위한 참고 문서

---

## 목차

1. [프로덕션 이메일 처리 시스템](#1-프로덕션-이메일-처리-시스템)
2. [이메일 첨부파일 처리 모범 사례](#2-이메일-첨부파일-처리-모범-사례)
3. [모니터링 및 관측성](#3-모니터링-및-관측성)
4. [파일 크기 처리](#4-파일-크기-처리)
5. [미등록 발신자 처리](#5-미등록-발신자-처리)
6. [이메일 처리 시 흔한 실수](#6-이메일-처리-시-흔한-실수)
7. [구현 체크리스트](#7-구현-체크리스트)

---

## 1. 프로덕션 이메일 처리 시스템

### 1.1 SendGrid Inbound Parse Webhook

**아키텍처**: MX 레코드 → SendGrid → Webhook POST → 사용자 엔드포인트

**주요 기능**:
- 수신 이메일을 구조화된 JSON으로 파싱
- 헤더, 본문(텍스트 + HTML), 첨부파일 추출
- **크기 제한**: 전체 메시지 30MB (첨부파일 포함)
- **재시도 로직**: 5xx 응답 시 자동 재시도, 403 시 중단
- **재시도 기간**: 최대 3일간 재시도 후 메시지 폐기
- **스팸 검사**: 2.5MB 이하 이메일에 대해 선택적 적용

**설정 요구사항**:
- MX 레코드를 `mx.sendgrid.net`으로 지정
- 공개 접근 가능한 웹훅 URL 설정
- 도메인 인증 필요

**AWS 서버리스 참조 아키텍처** (2025):
```
Email → SendGrid → API Gateway/ALB → Lambda (보안 검사)
  → S3 (원본 저장) → SQS 큐 → Lambda (파서)
  → S3 (파싱 데이터) → SNS (알림)
```

**중요 제한사항**:
- AWS API Gateway는 10MB 페이로드 제한이 있음
- 10MB 초과 첨부파일은 Application Load Balancer 사용 필요
- 전체 메시지 크기에는 MIME 인코딩 오버헤드(~33% 증가) 포함됨

**출처**:
- [SendGrid Inbound Parse Webhook](https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/inbound-email)
- [Inbound Parse Webhook 설정](https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/setting-up-the-inbound-parse-webhook)

---

### 1.2 AWS SES → S3 → Lambda 파이프라인

**아키텍처**: MX 레코드 → SES → S3 + Lambda (병렬 처리)

**두 가지 처리 패턴**:

**패턴 A - Lambda 직접 호출**:
- 이메일이 Lambda를 직접 트리거
- 이벤트 파라미터에 이메일 메타데이터 포함
- **제한**: 본문과 첨부파일은 이벤트에 미포함
- 적합 용도: 메타데이터만 필요한 처리 (발신자 검증, 라우팅)

**패턴 B - S3 + Lambda (권장)**:
- SES가 완전한 이메일을 S3에 저장
- S3 이벤트가 Lambda를 트리거하여 처리
- Lambda가 S3에서 이메일을 읽고 첨부파일 추출
- 적합 용도: 이메일 전체 및 첨부파일 처리

**모범 사례**:
- **호출 유형**: 동기 처리가 필요하지 않으면 비동기(Event) 호출 사용
- **타임아웃**: RequestResponse 기본 30초, 필요 시 증가
- **메일 흐름 제어**: STOP_RULE 제어를 위해 콜백과 함께 동기 호출 사용
- **IAM 권한**: 최소 필요 권한만 부여
- **S3 암호화**: 민감 데이터에 KMS 사용
- **버킷 정책**: Lambda 실행 역할에 S3 읽기 권한 부여 (루트뿐 아니라)
- **리전 일관성**: SES, S3, Lambda, SNS는 같은 리전이어야 함

**확장을 위한 분리 아키텍처**:
```
SES → S3 → Lambda → SQS → Lambda (처리 풀) → 결과
```
- SQS로 트래픽 급증 시 안정적 큐잉 보장
- Lambda가 병렬 처리를 위해 자동 스케일링
- 각 컴포넌트가 독립적으로 확장

**활용 사례**:
- 이메일 첨부파일에서 자동 주문 처리
- 송장 처리 및 데이터 추출
- 첨부파일 포함 지원 티켓 생성
- 피싱/보안 분석

**출처**:
- [AWS SES Lambda 함수 호출](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda.html)
- [AWS SES Lambda 예제 함수](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-action-lambda-example-functions.html)

---

### 1.3 Postmark Inbound Webhook

**아키텍처**: 이메일 → Postmark → Webhook POST (JSON) → 사용자 엔드포인트

**주요 기능**:
- 이메일을 구조화된 JSON으로 자동 변환
- 깔끔한 텍스트 답장 추출 (인용문 제거)
- Inbound Message Stream당 단일 웹훅 URL
- 자동 생성 주소(`123xyz@inbound.postmarkapp.com`) 또는 커스텀 도메인 사용 가능

**재시도 로직**:
- **총 재시도**: 점진적 간격으로 10회 시도
- **중단 코드**: 403 (Forbidden) 시 즉시 재시도 중단
- **성공 코드**: 200 응답 필요

**보안**:
- 웹훅 URL에 Basic HTTP 인증 지원
- 형식: `https://username:password@yourapp.com/webhook`

**출처**:
- [Postmark Inbound Webhook](https://postmarkapp.com/developer/webhooks/inbound-webhook)
- [Postmark으로 인바운드 이메일 처리 설정](https://curiousmints.com/setting-up-inbound-email-processing-with-postmark-aj-guide/)

---

### 1.4 Mailgun 라우팅 & 인바운드 처리

**아키텍처**: 이메일 → Mailgun 라우팅 (패턴 매칭) → HTTP/이메일/저장 → 사용자 엔드포인트

**주요 기능**:
- **라우트 표현식**: Regex 및 JSONPath 기반 필터링
- **다중 액션**: HTTP 전달, 이메일 전달, 저장 (3일)
- **파싱**: 주문번호, 고객 ID 등 추출을 위한 커스텀 규칙
- **데이터 형식**: UTF-8 인코딩 JSON (헤더, 본문, 첨부파일 별도 필드)
- **첨부파일**: 웹훅 페이로드에 Base64 인코딩

**재시도 로직**:
- **성공 코드**: 200 (재시도 없음)
- **중단 코드**: 406 (Not Acceptable) - 재시도 없음
- **재시도 스케줄**: 10분, 10분, 15분, 30분, 1시간, 2시간, 4시간 (총 7회)

**Postmark vs Mailgun 비교**:

| 기능 | Postmark | Mailgun |
|------|----------|---------|
| 웹훅 URL | 스트림당 1개 | 이벤트 타입/도메인당 최대 3개 |
| 재시도 횟수 | 10회 (점진적 간격) | 7회 (10분 → 4시간) |
| 재시도 중단 코드 | 403 | 406 |
| 라우팅 | 단순 포워딩 | Regex/JSONPath 라우트 표현식 |
| 설정 | 대시보드만 | 대시보드 또는 API |
| 메시지 저장 | Activity 탭 | 3일 임시 저장 |

**출처**:
- [Mailgun 인바운드 이메일 라우팅](https://www.mailgun.com/features/inbound-email-routing/)
- [Mailgun Webhooks 가이드](https://www.mailgun.com/blog/product/a-guide-to-using-mailguns-webhooks/)

---

### 1.5 엔터프라이즈 시스템: Salesforce Email-to-Case & Zendesk

#### Salesforce Email-to-Case

**동작 방식**:
- 고객 이메일을 자동으로 지원 케이스로 변환
- 발신자, 제목, 본문, 첨부파일 추출 → 케이스 필드 채움
- 라우팅 규칙으로 케이스 할당 및 처리 결정

**장점**:
- 중간 규모 이메일 볼륨 조직에 적합
- 템플릿, 케이스 필드, 워크플로우 자동화 커스터마이징 내장

**단점**:
- 비고객 이메일이 케이스 관리를 어지럽힐 수 있음
- 다수 첨부파일 업로드가 번거로움

#### Zendesk 이메일 처리

**동작 방식**:
- 이메일이 자동으로 지원 티켓으로 변환
- Salesforce와 통합하여 통합 고객 뷰 제공

**보안 고려사항**:
- 암호화된 파일 전송
- 안전한 프로토콜을 통한 데이터 교환
- ISO 27001 인증 권장
- GDPR 준수 지원

---

## 2. 이메일 첨부파일 처리 모범 사례

### 2.1 재시도 정책

**핵심 원칙**:

**재시도 가능 vs 불가능 에러**:
- **재시도 가능**: 네트워크 타임아웃, 5xx HTTP 코드, 연결 거부, 일시적 서비스 불가
- **재시도 불가**: 4xx 코드 (400 Bad Request, 401 Unauthorized, 404 Not Found, 403 Forbidden)
- **규칙**: 재시도 불가 에러는 절대 재시도하지 않음 - 리소스 낭비

**최대 재시도 횟수**:
- 항상 최대 재시도 한도를 정의
- 무제한 재시도 → 리소스 고갈 및 시스템 불안정
- 최대 재시도 후: 우아하게 실패하거나 폴백 메커니즘 트리거 (DLQ)

**권장 설정**:
```python
MAX_RETRIES = 4
INITIAL_DELAY = 1  # 초
MULTIPLIER = 2
MAX_BACKOFF = 300  # 5분 상한
```

---

### 2.2 지수 백오프 + 지터 (Exponential Backoff with Jitter)

**공식**:
```
대기_시간_i = min(b * r^i, MAX_BACKOFF)
```
각 변수:
- `b` = 0~1 사이의 랜덤 숫자 (지터)
- `r` = 배수 (보통 2)
- `i` = 재시도 횟수
- `MAX_BACKOFF` = 과도한 대기를 방지하는 상한값

**지터를 쓰는 이유**:
- 우뢰 무리 문제(thundering herd) 방지 - 동시에 모든 클라이언트가 재시도하는 것을 방지
- 재시도를 시간적으로 분산
- 복구 중인 서비스의 부하 감소

**백오프 시퀀스 예시** (지터 없이):
```
시도 1: 1초
시도 2: 2초
시도 3: 4초
시도 4: 8초
시도 5: 16초 (또는 MAX_BACKOFF로 제한)
```

**적합한 사용처**:
- O 백그라운드 프로세스 (알림, 이메일, 웹훅)
- O 비동기 작업 처리
- X 사용자 대면 요청 (UI 응답성에 비해 너무 느림)

---

### 2.3 서킷 브레이커 패턴 (Circuit Breaker)

**동작 방식**:
- 재시도 로직을 감싸서 연쇄 장애를 방지
- 서비스가 지속적으로 실패하면 서킷이 "트립"됨 (열림)
- 복구 기간 동안 추가 호출을 차단
- 타임아웃 후 테스트 호출을 허용하여 복구 확인

**상태**:
- **CLOSED (닫힘)**: 정상 운영, 호출이 통과됨
- **OPEN (열림)**: 너무 많은 실패, 모든 호출이 즉시 거부됨 (폴백 반환)
- **HALF-OPEN (반열림)**: 타임아웃 후 제한된 테스트 호출을 허용하여 서비스 상태 확인

**설정 예시**:
```python
FAILURE_THRESHOLD = 3  # 서킷을 트립하기 위한 연속 실패 횟수
TIMEOUT = 60  # 테스트 전 열린 상태 유지 시간 (초)
SUCCESS_THRESHOLD = 2  # 서킷을 닫기 위한 연속 성공 횟수
```

**재시도와 결합**:
```
재시도 (지수 백오프 + 지터) → 서킷 브레이커 (지속 실패 시 트립)
```

예시: 지수 백오프로 최대 4회 재시도. 여전히 실패하면, 3회 연속 실패 후 서킷 브레이커가 트립되어 1분간 열린 상태 유지.

**주요 라이브러리**:
- **Tenacity** (Python): 재시도 전략, 지수 백오프, 필터
- **Resilience4j** (Java): 재시도, 서킷 브레이커, 속도 제한, 벌크헤드
- **Polly** (.NET): 재시도, 서킷 브레이커, 타임아웃, 벌크헤드 정책

---

### 2.4 Dead Letter Queue (DLQ, 실패 메시지 격리 큐)

**목적**:
- 여러 번 재시도 후에도 처리에 실패한 메시지를 저장
- 실패한 메시지가 메인 큐를 차단하는 것을 방지
- 실패 원인 조사 및 재처리 가능

**DLQ가 필수인 이유**:
- **장애 격리**: 실패 메시지가 정상 처리를 방해하지 않음
- **디버깅 지원**: 실패 메시지를 분석하여 패턴 파악
- **안정성 유지**: 실패에도 시스템이 계속 운영됨

**실제 사례**:
> 큐 + SendGrid API로 환영 이메일을 보내는 시스템에서, 소비자가 이벤트를 확인(ack)하지 않는 버그가 있었음. 큐가 계속 재전달하면서 수십 통의 중복 이메일이 발송되고 파이프라인이 완전히 막힘.

**모범 사례**:

1. **적절한 재시도 한도 설정**:
   - DLQ로 이동하기 전 최대 재시도 횟수 설정
   - 시스템이 멱등성을 보장하여 중복 방지

2. **맹목적으로 재처리하지 않기**:
   - DLQ 메시지 재처리 전 근본 원인 조사
   - 근본 문제를 먼저 해결

3. **DLQ 보존 기간을 더 길게 설정**:
   - DLQ 보존 기간 > 소스 큐 보존 기간
   - 조사 및 해결에 충분한 시간 확보

4. **멱등성 구현**:
   - DLQ 재처리도 반드시 멱등해야 함
   - 멱등성 키로 중복 부작용 방지

5. **DLQ 메트릭 모니터링**:
   - DLQ 진입 비율 vs 메인 큐 = 시스템 건강 지표
   - 절대 수량 = 마지막 정리 이후 총 실패 건수
   - DLQ 깊이가 임계값 초과 시 알림

---

### 2.5 멱등성 (Idempotency)

**정의**: 같은 작업을 여러 번 수행해도 한 번 수행한 것과 동일한 결과를 보장.

**이메일 처리에서 중요한 이유**:
- 네트워크 장애로 중복 전달 발생 가능
- 재시도 로직이 같은 메시지를 재처리할 수 있음
- 중복 이메일, 중복 DB 항목, 중복 처리 방지

**구현 전략**:

**1. 멱등성 키**:
```python
# 메시지별 고유 키 생성
idempotency_key = f"{email_message_id}_{attachment_hash}"

# 이미 처리되었는지 확인
if already_processed(idempotency_key):
    return SUCCESS  # 처리 건너뛰기

# 처리 및 기록
process_attachment(attachment)
record_processed(idempotency_key)
```

**2. 데이터베이스 제약조건**:
- 메시지 ID + 첨부파일 ID에 유니크 제약조건 사용
- 중복 시 삽입 실패 (안전하게 무시 가능)

**3. 모든 부작용을 멱등하게 만들기**:
- X 안티패턴: DB 작업만 멱등하고, 외부 호출은 무시
- O 올바른 방식: 모든 부작용 멱등 (이메일 발송, API 호출, 파일 쓰기)

**4. 수동 확인(Acknowledgment)**:
- 완전한 처리 후에만 메시지 확인
- 처리 실패 시 메시지가 큐로 돌아가 재시도

---

### 2.6 파일 명명 전략

**프로덕션 모범 사례**:

**1. UUID로 고유성 보장**:
- **UUIDv4**: 랜덤, 높은 고유성 (가장 일반적)
- **UUIDv7**: 시간 기반 + 정렬 가능 (신규 시스템에 권장)

**비교**:
```
UUIDv4: 3f7a8c2d-9e1b-4f6d-a5c3-2b8e9d7f1a6c (랜덤)
UUIDv7: 018d3e9a-7b2c-7a1d-9e8f-3c4b5d6e7f8a (시간순 정렬 가능)
```

**2. 타임스탬프 + UUID 조합**:
```
형식: YYYYMMDD_HHmmss_UUID.확장자
예시: 20260130_143045_018d3e9a-7b2c-7a1d-9e8f-3c4b5d6e7f8a.pdf
```

**장점**:
- 사람이 읽을 수 있는 시간 순서
- 쉬운 디버깅 및 탐색
- UUID로 고유성 보장
- 타임스탬프로 맥락 제공

**3. 일반 명명 규칙**:
- X 공백 사용 금지 (대시 `-` 또는 밑줄 `_` 사용)
- X 특수문자 금지 (영숫자, 대시, 밑줄만 허용)
- O 파일명 최대 40-50자
- O 카운터에 앞에 0 붙이기 (`001`, `002`, `1`, `2` 아님)

**4. 원본 파일명 보존**:
```python
# 둘 다 저장
stored_filename = f"{timestamp}_{uuid}.{ext}"
original_filename = attachment.filename  # 메타데이터/DB에 저장
```

---

### 2.7 배치 vs 개별 처리

**순서 보장**:

**FIFO 큐**:
- 메시지가 순차적으로 처리됨을 보장
- **제한**: 한 번에 하나의 소비자만 처리 가능 (병렬 불가)
- **트레이드오프**: 순서 보장 vs 처리량

**순서 보장 기법**:
1. **시퀀스 번호**: 각 메시지에 고유 번호 부여, 오름차순 처리
2. **단일 스레드 소비자**: 본질적으로 순서대로 처리, 확장성 제한
3. **메시지 그룹핑**: 관련 메시지를 그룹화, 그룹 내 순서 보장, 다른 그룹은 병렬 처리

**배치 처리**:
- 장점: 효율적 (대량 DB 삽입), 오버헤드 감소, 리소스 활용도 향상
- 단점: 배치 중 42번째 항목에서 실패 시 전체 배치 실패, 개별 실패 추적 어려움

**개별 처리**:
- 장점: 격리된 실패 (하나 실패해도 나머지 계속), 쉬운 재시도 로직, 메시지별 관측성 향상
- 단점: 오버헤드 증가, 대량 처리 시 느릴 수 있음

**하이브리드 접근 (이메일 처리에 권장)**:
```
마이크로 배치를 포함한 개별 메시지 처리:
- 큐에서 메시지를 개별로 처리
- DB 쓰기는 배치 (100건 누적 후 대량 삽입)
- 업로드는 병렬 (여러 파일 버퍼링 후 병렬 업로드)
```

---

## 3. 모니터링 및 관측성

### 3.1 추적해야 할 핵심 메트릭

**이메일 처리 메트릭**:

| 메트릭 | 설명 | 업계 기준 |
|--------|------|----------|
| **처리율** | 초/분당 처리된 메시지 수 | 볼륨에 따라 기준선 설정 |
| **실패율** | 처리 실패한 메시지 비율 | < 2% |
| **지연시간** | 이메일 수신부터 처리 완료까지 시간 | p50, p95, p99 지연시간 |
| **큐 깊이** | 큐에서 대기 중인 메시지 수 | 임계값 초과 시 알림 |
| **DLQ 깊이** | Dead Letter Queue의 메시지 수 | 0 초과(또는 임계값) 시 알림 |
| **전달율** | 성공적으로 처리된 이메일 비율 | 95-99% |
| **반송율** | 반송된 이메일 비율 | < 2% |
| **스팸 신고율** | 스팸으로 표시된 이메일 비율 | < 0.1% |

**4가지 골든 시그널** (Google SRE):
1. **지연시간(Latency)**: 메시지 처리에 걸리는 시간
2. **트래픽(Traffic)**: 요청/메시지 수
3. **에러(Errors)**: 실패한 요청 비율
4. **포화도(Saturation)**: 시스템 부하 수준 (큐 깊이, CPU, 메모리)

---

### 3.2 대시보드 모범 사례

**구조**:
- 사용자 여정 기준으로 구성: 인지 → 관심 → 행동
- 대시보드는 이야기 중심으로, 단순 메트릭 나열이 아닌
- 현재 값만이 아닌 시간에 따른 추세 표시
- 세그먼트별 성능 비교 포함

**효과성**:
- "대시보드는 도구이지 예술품이 아니다" - 문제 해결에 집중
- 최고의 대시보드는 볼 필요가 없는 것 (알림이 제대로 작동하면)
- 한눈에 고수준 개요 제공
- 상세 조사를 위한 드릴다운 허용

**포함할 내용**:

1. **시스템 상태 개요**:
   - 처리율 (최근 1시간, 24시간)
   - 에러율 추세
   - 큐 깊이 그래프
   - DLQ 깊이 (0 초과 시 알림)

2. **리소스 사용량**:
   - CPU 사용률
   - 메모리 사용량
   - 스토리지 사용량
   - 네트워크 대역폭

3. **비즈니스 메트릭**:
   - 처리된 총 이메일 (오늘, 이번 주, 이번 달)
   - 추출된 총 첨부파일
   - 처리된 총 파일 크기
   - 볼륨별 상위 발신자

4. **에러 분석**:
   - 유형별 에러 분류 (네트워크, 파싱, 스토리지, 검증)
   - 발신자 도메인별 실패 메시지
   - 재시도 횟수 히스토그램

---

### 3.3 알림 모범 사례

**알림을 보낼 때**:
- **핵심 컴포넌트**: DB 가용성, 큐 서비스 상태
- **임계값 초과**: 에러율 > 5%, 지연시간 p95 > 10초, 큐 깊이 > 1000
- **이상 감지**: 처리율 급감, 실패 급증

**알림을 보내지 않을 때**:
- 대시보드에 더 적합한 정보성 메트릭
- 나중에 조사해도 되는 저우선순위 이벤트

**알림 피로(Alert Fatigue) 방지**:
- **알림 피로**: 팀이 알림에 둔감해지는 상태
- **원인**: 너무 빈번, 오탐, 실행 불가능한 알림
- **위험**: 중요한 알림이 무시됨

**해결책**:
1. **중복 알림 제거**: 5개 서비스가 DB에 의존하면, DB 장애 1건만 알림 (5건 아님)
2. **기준선 사용**: 며칠간 정상 행동을 모니터링하여 이상 임계값 정의
3. **알림에 행동 지침 포함**: 각 알림에 명확한 다음 단계 포함
4. **적절한 임계값 설정**: 너무 민감 → 노이즈, 너무 높음 → 이슈 놓침
5. **관련 알림 그룹화**: 같은 근본 원인의 여러 증상 통합

**알림 설정 예시**:
```yaml
alerts:
  high_error_rate:
    condition: error_rate > 5%
    window: 5분
    severity: critical
    action: 당직 엔지니어 호출

  queue_depth_high:
    condition: queue_depth > 1000
    window: 10분
    severity: warning
    action: Slack 알림 발송

  dlq_not_empty:
    condition: dlq_depth > 0
    window: 1분
    severity: warning
    action: 팀에 이메일 발송
```

---

### 3.4 감사 추적 & 컴플라이언스 (GDPR)

**법적 요구사항**:

**GDPR 제30조**: 조직은 개인정보 사용 방법을 감사하고 기록해야 함.

**GDPR 제5조 2항 - 책임 원칙**: 데이터 관리자는 데이터 보호 원칙 준수를 입증해야 함.

**반드시 로깅해야 할 내용**:

1. **데이터 접근**: 누가 이메일/첨부파일 데이터에 접근했는지, 언제, 왜
2. **데이터 변경**: 어떤 변경이 이루어졌는지, 누가, 언제
3. **데이터 삭제**: 무엇이 삭제되었는지, 누가 시작했는지, 언제

**메타 로깅**:
- 로그에 접근한 사람도 기록
- 로그에 대한 작업도 기록
- 안전한 감사 추적 유지

**로그에서의 데이터 최소화**:
- 불필요한 개인정보 로깅 금지
- 이메일 주소, 전화번호, 민감 내용 마스킹
- 운영/법적 목적에 필요한 것만 로깅

**감사 추적 예시**:
```python
audit_log = {
    "timestamp": "2026-01-30T14:30:45Z",
    "event_type": "email_processed",
    "actor": "system/email-processor",
    "email_id": "msg-123456",
    "sender": "sender@example.com (해시됨)",  # PII 해싱 고려
    "attachment_count": 3,
    "attachments": [
        {
            "filename": "invoice.pdf",
            "size": 245678,
            "stored_as": "20260130_143045_uuid.pdf",
            "hash": "sha256:abc123..."
        }
    ],
    "processing_status": "success",
    "storage_location": "gs://bucket/path/",
    "retention_until": "2029-01-30T00:00:00Z"  # 3년 보존
}
```

**위반 시 제재**: 최대 2천만 유로 또는 연간 매출액의 4% (더 큰 쪽)

---

## 4. 파일 크기 처리

### 4.1 이메일 첨부파일 크기 제한

**주요 제공업체**:

| 제공업체 | 크기 제한 | 비고 |
|----------|----------|------|
| **Gmail** | 25MB | 메시지 + 모든 첨부파일 포함 |
| **Outlook** | 20MB | 대부분 계정 기본값 |
| **Outlook (Office 365)** | 150MB | OneDrive 통합 (유료) |
| **Outlook (Exchange)** | 10MB | 기본 Exchange 설정 |
| **Yahoo Mail** | 25MB | - |
| **SendGrid** | 30MB | Inbound Parse 전체 메시지 크기 |

**범용 안전 범위**: 10-20MB (대부분의 제공업체와 호환)

---

### 4.2 크기 제한이 존재하는 이유

**기술적 이유**:

1. **SMTP 프로토콜 한계**: 수십 년 된 프로토콜, 대용량 파일 전송에 최적화되지 않음
2. **서버 성능**: 대용량 첨부파일이 처리 시간, 대역폭, 스토리지 소모
3. **MIME 인코딩 오버헤드**: **MIME 인코딩으로 크기가 ~33% 증가** (예: 20MB 파일 → ~27MB)
4. **보안**: 스팸, 바이러스 등 악의적 공격 방지

**수신측 제한**:
- 보내는 쪽이 25MB를 허용해도, 받는 쪽이 10MB 제한이면 반송됨

---

### 4.3 프로덕션에서 대용량 파일 처리

**방법 1: 클라우드 스토리지 통합 (권장)**:
```
파일 첨부 대신 → 클라우드에 업로드 → 이메일에 링크 포함
```

**장점**:
- 크기 제한 없음 (클라우드 스토리지 한도가 훨씬 큼)
- 빠른 이메일 전달
- 조회/다운로드 분석 가능
- 여러 수신자에게 쉽게 공유

**방법 2: 청크/이어받기 업로드**:
- 프로그래밍 방식 접근용 (일반 이메일이 아님)
- **Gmail API**: 이어받기 업로드 지원
- **Microsoft Graph API**: 3MB 초과 첨부파일에 청크 업로드 세션 지원

**방법 3: 스트리밍 업로드**:
- 수신하면서 청크 단위로 업로드
- 전체 파일을 메모리에 버퍼링하지 않음
- 서버리스 환경(제한된 메모리)에 적합

---

### 4.4 설정 기반 크기 제한

**제한을 설정하는 위치**:

**1. 애플리케이션 레벨 (주요 제어 권장)**:
```python
MAX_ATTACHMENT_SIZE = 25_000_000  # 25MB
MAX_TOTAL_EMAIL_SIZE = 30_000_000  # 30MB

def validate_email(email):
    total_size = email.body_size
    for attachment in email.attachments:
        if attachment.size > MAX_ATTACHMENT_SIZE:
            raise AttachmentTooLarge(attachment.filename)
        total_size += attachment.size

    if total_size > MAX_TOTAL_EMAIL_SIZE:
        raise EmailTooLarge(total_size)
```

**2. 인프라 레벨**: 로드밸런서 요청 크기, 서버리스 페이로드 크기, 큐 메시지 크기
**3. API/웹훅 레벨**: Content-Length 헤더 검증, 초과 시 413 Payload Too Large 반환
**4. 이메일 제공업체 레벨**: SES, SendGrid 등 서비스 설정

**일반적인 크기 제한 값**:

| 사용 사례 | 권장 제한 | 이유 |
|----------|----------|------|
| **넓은 호환성** | 10MB | 대부분 이메일 제공업체와 호환 |
| **최신 제공업체** | 20-25MB | Gmail/Yahoo 표준 |
| **기업 내부** | 50-100MB | 통제된 환경, 서버 설정 가능 |
| **클라우드 스토리지 필요** | > 25MB | 클라우드 스토리지 + 링크 사용 |

---

## 5. 미등록 발신자 처리

### 5.1 발신자 분류 전략

**Cisco Secure Email Gateway 접근**:

| 발신자 그룹 | 처리 | 스팸 방지 | 속도 제한 |
|------------|------|----------|----------|
| **ALLOWED_LIST** | 신뢰 발신자 | 없음 | 없음 |
| **BLOCKED_LIST** | 스패머 | 즉시 거부 | 해당없음 |
| **SUSPECTLIST** | 의심 | 전체 검사 | 제한됨 |
| **UNKNOWNLIST** | 미확인 | 일반 검사 | 일반 |

**Microsoft Defender 접근**:
- **허용 발신자/도메인**: 스팸 필터링 건너뜀
- **차단 발신자/도메인**: 자동으로 정크/거부
- **격리**: 의심스러운 이메일을 14일간 보관
- **스팸 방지 정책**: 임계값 기반 필터링

---

### 5.2 격리(Quarantine) 접근

**동작 방식**:
1. 미확인/의심 발신자의 수신 이메일
2. 이메일이 격리됨 (받은편지함에 전달되지 않음)
3. 수신자에게 알림 발송 (선택)
4. 수신자/관리자가 검토하고 결정:
   - 받은편지함으로 해제
   - 삭제
   - 발신자를 허용/차단 목록에 추가

**격리 정책**:
- **보존 기간**: 14일 (Microsoft 365 기본값)
- **사용자 액션**: 미리보기, 해제, 발신자 차단
- **관리자 액션**: 대량 해제, 삭제, 내보내기

**모범 사례**:
- 사용자가 자체 격리를 관리할 수 있도록 허용
- 일별/주별 격리 요약 발송
- 쉬운 "스팸 아님" 신고 메커니즘 제공
- 모든 격리 액션을 감사용으로 로깅

---

### 5.3 자동 회신 전략

**자동 회신을 보낼 때**:
- O 알려진/등록된 발신자 (수신 확인)
- O 발신자가 정보를 요청한 경우 (문의 양식)
- X 미확인 발신자 (스팸 위험 높음)
- X 의심스러운 내용 감지

**자동 회신의 위험**:
1. **활성 이메일 확인**: 스패머에게 이메일이 활성화되고 모니터링되고 있음을 알림
2. **회신 루프**: 자동 회신 → 자동 회신 → 무한 루프
3. **백스캐터**: 위조된 발신자 주소로 회신
4. **오픈 릴레이 위험**: 스팸 발송에 악용될 수 있음

**안전한 자동 회신 구현**:
```python
def should_send_auto_reply(email):
    # 메일링 리스트에 회신하지 않음
    if email.headers.get('List-Unsubscribe'):
        return False

    # 자동 생성 이메일에 회신하지 않음
    if email.headers.get('Auto-Submitted') == 'auto-generated':
        return False

    # 반송 메시지에 회신하지 않음
    if email.headers.get('Return-Path') == '<>':
        return False

    # 발신자 평판 확인
    if is_sender_suspicious(email.from_address):
        return False

    # 발신자별 자동 회신 속도 제한
    if recent_auto_reply_sent(email.from_address):
        return False

    return True
```

**모범 사례**: 미확인 발신자에게 자동 회신하지 않는다. 대신:
1. 이메일을 묵시적으로 수락 (확인 없이)
2. 규칙에 따라 처리/격리
3. 내부 팀에 알림 (발신자가 아닌)

---

### 5.4 허용/차단 목록 관리

**허용 목록 (Safe Senders)**:
- 허용된 주소/도메인의 이메일 자동 전달
- 스팸 필터링 우회
- 용도: 알려진 파트너, 벤더, 고객

**차단 목록 (Blocked Senders)**:
- 차단된 주소/도메인의 이메일 자동 거부 또는 정크 처리
- 용도: 알려진 스패머, 악의적 발신자

**처리 순서** (중요):
```
1. 필터 규칙 (최고 우선순위)
2. 차단 목록
3. 허용 목록
4. 스팸 방지 정책
5. 받은편지함 전달
```

**예시**: 필터 규칙이 발신자를 스팸으로 보내면, 허용 목록이 이를 무시할 수 없음.

**모범 사례**:

1. **도메인 레벨 vs 이메일 레벨**:
   - 도메인 허용: `@company.com` (도메인의 모든 이메일)
   - 이메일 허용: `john@company.com` (특정 발신자)

2. **검증 (중요)**:
   - 허용 목록에 있더라도 발신자 인증 검증
   - SPF, DKIM, DMARC 확인
   - 검증 실패 시 전체 검사 수행

3. **정기 검토**:
   - 허용/차단 목록을 주기적으로 검토
   - 오래된 항목 제거
   - 허용 목록의 손상된 계정 확인

---

### 5.5 발신자 검증 워크플로우

**이메일 인증 메커니즘**:

**1. SPF (Sender Policy Framework)**:
- 인증된 발송 서버를 나열하는 DNS TXT 레코드
- 수신 서버가 발신자 IP가 인증되었는지 확인
- 위조된 발신자 주소 방지

**2. DKIM (DomainKeys Identified Mail)**:
- 이메일 헤더의 디지털 서명
- 이메일이 전송 중 변경되지 않았음을 검증
- 이메일이 주장된 도메인에서 왔음을 증명

**3. DMARC (Domain-based Message Authentication)**:
- SPF + DKIM을 사용하는 정책 프레임워크
- SPF/DKIM 실패 시 수신 서버에게 무엇을 할지 지시
- 정책: none, quarantine, reject

**검증 워크플로우**:
```
1. 미확인 발신자로부터 이메일 도착
2. SPF 확인: 발송 IP가 인증되었는가?
3. DKIM 확인: 서명이 유효한가?
4. DMARC 확인: 도메인 정책은 무엇인가?
5. 평판 점수 계산
6. 결정: 수락, 격리, 또는 거부
```

**프로덕션 권장 접근**:
- SPF/DKIM/DMARC 검증을 자동으로 수행
- 검증 통과한 미확인 발신자 → "외부 발신자" 경고와 함께 전달
- 검증 실패한 미확인 발신자 → 격리
- 미확인 발신자에게 절대 자동 회신하지 않음
- 허용/차단 목록 관리를 위한 쉬운 인터페이스 제공

---

## 6. 이메일 처리 시 흔한 실수

### 6.1 winmail.dat 파일 (TNEF 인코딩)

**정의**:
- Microsoft 독점 형식 (Transport Neutral Encapsulation Format)
- 서식 있는 텍스트 형식, 일정 초대, 투표 버튼 등을 보존
- Outlook에서만 읽을 수 있음

**문제점**:
- Outlook이 아닌 클라이언트(Gmail, Apple Mail, Thunderbird)는 `winmail.dat` 첨부파일을 받음
- 원본 첨부파일이 `winmail.dat` 안에 내장됨
- 수신자가 실제 첨부파일에 접근 불가

**발생 원인**:
- Outlook이 서식 있는 텍스트(RTF) 형식으로 이메일을 보냄
- RTF는 표준 MIME 이메일에서 지원되지 않음
- Outlook이 모든 것을 TNEF(winmail.dat)로 감쌈

**winmail.dat 내부 내용**:
- 원본 서식 메시지 (글꼴, 색상, 크기)
- OLE 객체 (내장 이미지, Office 문서)
- Outlook 특수 기능 (양식, 투표 버튼, 회의 요청)
- **일반 첨부파일** (실제로 필요한 파일들)

**코드로 추출**:
```python
import tnefparse

def extract_winmail_dat(winmail_file):
    tnef_obj = tnefparse.TNEF(winmail_file.read())

    attachments = []
    for attachment in tnef_obj.attachments:
        attachments.append({
            'name': attachment.name,
            'data': attachment.data,
            'mimetype': attachment.mimetype
        })

    return attachments
```

**감지**:
```python
def is_winmail_dat(attachment):
    return (
        attachment.filename.lower() == 'winmail.dat' or
        attachment.content_type == 'application/ms-tnef'
    )
```

**권장 처리 방법**:
1. `winmail.dat` 첨부파일 감지
2. TNEF 파서로 실제 첨부파일 추출
3. 추출된 첨부파일을 정상적으로 처리
4. 문제 발신자 식별을 위해 발생 로깅
5. 발신자에게 Outlook 설정 변경 안내

---

### 6.2 문자 인코딩 & 파일명 문제

**문제점**:
- 원본 이메일이 파일명에 비ASCII 문자를 사용할 수 있음 (한국어, 일본어, 중국어, 이모지)
- 악센트 문자가 있는 파일명 (é, ñ, ü)
- 적절히 인코딩하지 않으면 파일명이 깨지거나 에러 발생

**표준**:
- **기존**: 이메일 헤더에 US-ASCII만 지원
- **현재**: RFC 5987로 적절한 인코딩으로 전체 유니코드 허용

**문제 예시**:
```
원본 파일명: "보고서_2026년_1월.xlsx" (한국어)
잘못된 처리: "___2026__1_.xlsx" 또는 "?.xlsx"
올바른 인코딩: "=?UTF-8?B?67O07rO87IScXzIwMjblubRfMeyblC54bHN4?="
```

**해결책**:

**1. MIME 인코딩된 파일명 디코딩**:
```python
import email.header

def decode_filename(raw_filename):
    decoded = email.header.decode_header(raw_filename)
    filename = ''
    for part, encoding in decoded:
        if isinstance(part, bytes):
            filename += part.decode(encoding or 'utf-8')
        else:
            filename += part
    return filename
```

**2. 파일명 정제**:
```python
import re
import unicodedata

def sanitize_filename(filename):
    # 유니코드 정규화 (NFD -> NFC)
    filename = unicodedata.normalize('NFC', filename)

    # 파일시스템에 안전하지 않은 문자 제거/치환
    # 유지: 영숫자, 한글, 대시, 밑줄, 점
    filename = re.sub(r'[^\w\s\-\.]', '_', filename)

    # 여러 공백/밑줄 축소
    filename = re.sub(r'[-_\s]+', '_', filename)

    # 길이 제한 (파일시스템 제한: 255바이트)
    max_bytes = 200  # UUID 접두사를 위한 여유
    while len(filename.encode('utf-8')) > max_bytes:
        filename = filename[:-1]

    return filename
```

**3. 원본 + 안전한 파일명 모두 저장**:
```python
attachment_metadata = {
    'original_filename': '보고서_2026년_1월.xlsx',  # 원본 보존
    'stored_filename': '20260130_143045_uuid.xlsx',  # 파일시스템에 안전
    'display_name': '보고서_2026년_1월.xlsx'  # UI 표시용
}
```

**보안 고려사항**:
- **파일명을 직접 신뢰하지 않기** - 항상 검증 및 정제
- **경로 탐색**: `../`, `..\\`, 절대 경로 차단
- **위험한 확장자**: `.exe`, `.bat`, `.sh`, 이중 확장자 (`.pdf.exe`) 차단
- **널 바이트**: `\x00` 문자 제거 (확장자 검사를 우회할 수 있음)

---

### 6.3 인라인 이미지 vs 실제 첨부파일

**Content-Disposition 헤더**:
- **`attachment`**: 파일을 다운로드/저장해야 함
- **`inline`**: 메시지 본문 내에 표시되는 내용 (예: 내장 이미지)

**문제점**:
- HTML 이메일은 종종 인라인 이미지를 포함 (로고, 서명)
- 모든 첨부파일을 처리하면 수십 개의 서명 이미지를 받게 됨
- 구분 필요:
  - **실제 첨부파일**: 사용자가 업로드한 파일
  - **인라인 첨부파일**: 이메일 서식/서명

**감지**:
```python
def is_real_attachment(part):
    content_disposition = part.get('Content-Disposition', '')

    # Disposition 확인
    if content_disposition.startswith('attachment'):
        return True

    if content_disposition.startswith('inline'):
        # 인라인 이미지는 보통 HTML에서 참조됨
        content_id = part.get('Content-ID')
        if content_id:
            # 내장 이미지일 가능성 높음
            return False
        else:
            # 인라인이지만 Content-ID 없음 - 실제 첨부파일일 수 있음
            return True

    # Disposition 헤더 없음 - 콘텐츠 타입 확인
    content_type = part.get_content_type()
    if content_type.startswith('image/'):
        # 내장 이미지일 가능성 높음
        return False

    return True
```

**Content-ID (CID)**:
- 인라인 이미지가 HTML에서 참조: `<img src="cid:image123@mail.com">`
- `Content-ID: <image123@mail.com>` 첨부파일과 매칭됨

**모범 사례**:
```python
def process_attachments(email_message):
    real_attachments = []
    inline_images = []

    for part in email_message.walk():
        if part.get_content_maintype() == 'multipart':
            continue

        filename = part.get_filename()
        if not filename:
            continue

        disposition = part.get('Content-Disposition', '').lower()
        content_id = part.get('Content-ID')

        if 'attachment' in disposition:
            real_attachments.append(part)
        elif 'inline' in disposition and content_id:
            inline_images.append(part)
        else:
            # 애매한 경우 - 휴리스틱 사용
            if part.get_content_type().startswith('image/'):
                inline_images.append(part)
            else:
                real_attachments.append(part)

    return real_attachments, inline_images
```

---

### 6.4 캘린더 초대 (.ics 파일)

**정의**:
- iCalendar 형식 (RFC 5545)
- 회의/이벤트 정보 포함
- Content-Type: `text/calendar`
- 보통 `calendar.ics` 또는 `invite.ics`로 표시

**문제점**:

1. **콘텐츠 억제**: .ics 첨부파일이 있으면 Outlook이 이메일 본문을 숨길 수 있음
2. **자동 처리**: 일부 클라이언트가 자동으로 캘린더에 추가 (사용자 검토 우회) → 보안 위험
3. **중첩 회의 초대**: 전달된 이메일의 .ics 첨부파일로 인한 혼동

**감지**:
```python
def is_calendar_invite(attachment):
    return (
        attachment.get_content_type() == 'text/calendar' or
        attachment.filename.lower().endswith('.ics')
    )
```

**보안 모범 사례**:
1. 미확인 발신자의 자동 처리 금지
2. 주최자가 허용 목록에 있는지 확인
3. 위치/설명 필드의 URL 검사
4. .ics 파일은 다른 첨부파일과 별도로 처리

---

### 6.5 전달된 이메일 & 중첩 첨부파일

**문제점**:
- 원본 이메일에 첨부파일이 있음
- 사용자가 이메일을 전달
- 전달된 이메일에 포함되는 것:
  - 중첩 메시지로서의 원본 이메일
  - 원본 첨부파일
  - 추가 첨부파일 (가능)

**구조**:
```
전달된 이메일
├── 본문: "참고하세요"
├── 첨부파일: "Report.pdf" (새로 추가)
└── 중첩 메시지 (message/rfc822)
    ├── 원본 본문
    ├── 첨부파일: "Invoice.pdf" (원본에서)
    └── 인라인 이미지: "logo.png" (원본에서)
```

**감지 및 추출**:
```python
def extract_all_attachments(email_message, include_nested=True):
    attachments = []

    for part in email_message.walk():
        # 중첩된 이메일 메시지 확인
        if part.get_content_type() == 'message/rfc822':
            if include_nested:
                # 중첩 메시지 파싱
                nested_msg = email.message_from_bytes(part.get_payload(decode=True))
                # 재귀적으로 중첩 메시지에서 추출
                nested_attachments = extract_all_attachments(nested_msg, include_nested=True)
                attachments.extend(nested_attachments)
            continue

        # 일반 첨부파일 처리
        if part.get_filename():
            attachments.append({
                'filename': part.get_filename(),
                'content': part.get_payload(decode=True),
                'content_type': part.get_content_type(),
            })

    return attachments
```

**중복 제거**:
```python
import hashlib

def deduplicate_attachments(attachments):
    seen_hashes = set()
    unique_attachments = []

    for attachment in attachments:
        content_hash = hashlib.sha256(attachment['content']).hexdigest()

        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            unique_attachments.append(attachment)
        else:
            print(f"중복 첨부파일: {attachment['filename']}")

    return unique_attachments
```

**모범 사례**:
1. 중첩 메시지 처리: `message/rfc822` 콘텐츠 타입 파싱
2. 중복 제거: 전달 체인에서 같은 첨부파일이 여러 번 나타날 수 있음
3. 출처 추적: 최상위 또는 중첩 메시지의 첨부파일인지 기록
4. 맥락 보존: 첨부파일과 메시지 레벨 간의 연관 유지

---

### 6.6 이메일 스레드 & 같은 첨부파일 반복

**문제점**:
- 사용자가 첨부파일이 있는 이메일을 보냄
- 수신자가 답장 (원본 이메일과 첨부파일 포함)
- 각 답장이 첨부파일을 다시 포함
- 이메일 스레드가 커지며 같은 첨부파일이 N번 중복

**예시**:
```
이메일 1: "보고서입니다" [report.pdf - 5MB]
└─ 이메일 2: "Re: 감사합니다!" [이메일1 포함 + report.pdf - 5MB]
   └─ 이메일 3: "Re: Re: 천만에요" [이메일1-2 포함 + report.pdf x2 - 10MB]
```

**감지 전략**:
```python
def extract_thread_attachments(email_thread):
    """
    이메일 스레드에서 고유 첨부파일 추출,
    답장 체인의 중복 방지
    """
    seen_hashes = {}

    # 날짜순 정렬 (가장 오래된 것 먼저)
    sorted_emails = sorted(email_thread, key=lambda e: e.date)

    for email in sorted_emails:
        for attachment in email.attachments:
            content_hash = hashlib.sha256(attachment.content).hexdigest()

            if content_hash not in seen_hashes:
                seen_hashes[content_hash] = {
                    'first_seen': email.date,
                    'first_sender': email.from_address,
                    'attachment': attachment
                }
            # else: 스레드 이전에서 온 중복

    return list(seen_hashes.values())
```

**스레드 감지**:
```python
def is_part_of_thread(email):
    """이메일이 스레드의 답장인지 확인"""
    if email.get('In-Reply-To'):
        return True
    if email.get('References'):
        return True
    subject = email.get('Subject', '')
    if subject.startswith('Re:') or subject.startswith('Fwd:'):
        return True
    return False
```

**모범 사례**:
- Message-ID와 In-Reply-To 헤더 저장
- References 헤더로 스레드별 이메일 그룹화
- 전체 스레드를 단위로 처리
- 스레드 내 첨부파일 중복 제거
- 각 첨부파일의 첫 번째 발생만 유지

---

## 7. 구현 체크리스트

### 7.1 핵심 인프라

- [ ] **이메일 수신**
  - [ ] 제공업체 선택 (SendGrid, AWS SES, Postmark, Mailgun 또는 자체 호스팅)
  - [ ] MX 레코드 설정
  - [ ] 웹훅 엔드포인트 설정 (공개 접근, HTTPS)
  - [ ] 웹훅 인증/검증 구현

- [ ] **메시지 큐**
  - [ ] 큐 서비스 선택 (AWS SQS, Azure Service Bus, RabbitMQ 등)
  - [ ] 큐 설정 (FIFO vs 표준, 메시지 보존, 가시성 타임아웃)
  - [ ] Dead Letter Queue (DLQ) 설정
  - [ ] 메시지 중복 제거 구현 (필요 시)

- [ ] **스토리지**
  - [ ] 이메일 및 첨부파일용 S3/GCS/Blob Storage 설정
  - [ ] 버킷 정책 및 접근 제어 설정
  - [ ] 암호화 구현 (저장 시 + 전송 시)
  - [ ] 수명 주기 정책 정의 (보존, 만료, 아카이빙)

### 7.2 처리 로직

- [ ] **이메일 파서**
  - [ ] 헤더, 본문(텍스트 + HTML), 첨부파일 추출
  - [ ] MIME 인코딩/디코딩 처리
  - [ ] winmail.dat 추출 지원 (TNEF 파싱)
  - [ ] 중첩 메시지 파싱 (전달된 이메일)
  - [ ] 인라인 이미지와 실제 첨부파일 구분

- [ ] **첨부파일 처리**
  - [ ] 파일 크기 검증 (제한 초과 시 거부)
  - [ ] 대용량 파일 처리 (청크 업로드, 스트리밍)
  - [ ] 문자 인코딩 처리 (유니코드 파일명)
  - [ ] 파일명 정제 (위험 문자 제거)
  - [ ] 파일 타입 검증 (MIME 타입 + magic bytes)
  - [ ] 바이러스/악성코드 검사

- [ ] **발신자 처리**
  - [ ] 허용/차단 목록 구현
  - [ ] SPF/DKIM/DMARC 검증
  - [ ] 미확인 발신자 워크플로우 (격리, 수동 검토)
  - [ ] 발신자별 속도 제한

### 7.3 안정성 & 복원력

- [ ] **재시도 정책**
  - [ ] 지수 백오프 + 지터 구현
  - [ ] 최대 재시도 한도 설정
  - [ ] 재시도 가능 vs 불가 에러 구분
  - [ ] 외부 의존성에 서킷 브레이커 패턴

- [ ] **멱등성**
  - [ ] 멱등성 키 사용 (메시지 ID + 첨부파일 해시)
  - [ ] 중복 방지를 위한 DB 제약조건
  - [ ] 처리된 메시지를 DB에 기록
  - [ ] DLQ에서의 재처리를 안전하게 처리

- [ ] **에러 처리**
  - [ ] Dead Letter Queue 설정
  - [ ] 에러 분류 (네트워크, 파싱, 검증, 스토리지)
  - [ ] 우아한 성능 저하 (부분 성공 처리)
  - [ ] 실패율 임계값에 대한 알림

### 7.4 모니터링 & 관측성

- [ ] **메트릭 수집**
  - [ ] 처리율 (메시지/초)
  - [ ] 실패율 (%)
  - [ ] 지연시간 (p50, p95, p99)
  - [ ] 큐 깊이
  - [ ] DLQ 깊이
  - [ ] 첨부파일 크기 분포

- [ ] **대시보드**
  - [ ] 시스템 상태 개요
  - [ ] 리소스 사용량 (CPU, 메모리, 스토리지)
  - [ ] 비즈니스 메트릭 (총 처리량, 상위 발신자)
  - [ ] 에러 분석 (유형별 분류)

- [ ] **알림**
  - [ ] 에러율 > 임계값
  - [ ] 지연시간 > 임계값
  - [ ] 큐 깊이 > 임계값
  - [ ] DLQ 비어있지 않음
  - [ ] 서비스 상태 점검

- [ ] **감사 추적 & 컴플라이언스**
  - [ ] 모든 이메일 처리 이벤트 로깅
  - [ ] 누가 무엇에 언제 접근했는지 추적
  - [ ] GDPR 준수 (데이터 최소화, 보존 정책)
  - [ ] 데이터 주체 접근 요청(DSAR) 지원

### 7.5 보안

- [ ] **인증 & 인가**
  - [ ] 웹훅 서명 검증
  - [ ] API 키/토큰 관리
  - [ ] IAM 역할 및 정책 (최소 권한)

- [ ] **데이터 보호**
  - [ ] 저장 시 암호화 (S3/GCS, 데이터베이스)
  - [ ] 전송 시 암호화 (HTTPS, TLS)
  - [ ] 로그에서 PII 마스킹
  - [ ] 안전한 삭제 (삭제 마커가 아닌 덮어쓰기)

- [ ] **위협 방지**
  - [ ] 이메일 인증 (SPF, DKIM, DMARC)
  - [ ] 첨부파일 검사 (안티바이러스, 악성코드)
  - [ ] 속도 제한 (남용 방지)
  - [ ] 입력 검증 (인젝션 공격 방지)

### 7.6 테스트

- [ ] **단위 테스트**
  - [ ] 이메일 파싱 (다양한 형식, 인코딩)
  - [ ] 첨부파일 추출 (winmail.dat 포함)
  - [ ] 파일명 정제
  - [ ] 재시도 로직
  - [ ] 멱등성 키 생성

- [ ] **통합 테스트**
  - [ ] 엔드투엔드 이메일 처리
  - [ ] 큐 통합
  - [ ] 스토리지 통합
  - [ ] DLQ 처리

- [ ] **부하 테스트**
  - [ ] 지속 부하 (X 메시지/초)
  - [ ] 버스트 트래픽 (갑작스러운 급증)
  - [ ] 대용량 첨부파일 처리
  - [ ] 큐 백로그 처리

- [ ] **엣지 케이스**
  - [ ] 본문 없는 이메일
  - [ ] 인라인 이미지만 있는 이메일
  - [ ] 깊게 중첩된 전달 이메일
  - [ ] 잘못된 MIME 구조
  - [ ] 극대형 첨부파일
  - [ ] 비UTF-8 문자 인코딩

### 7.7 문서화

- [ ] **시스템 문서**
  - [ ] 아키텍처 다이어그램
  - [ ] 데이터 흐름
  - [ ] 통합 포인트
  - [ ] 설정 항목

- [ ] **운영 문서**
  - [ ] 배포 프로세스
  - [ ] 모니터링 및 알림 런북
  - [ ] DLQ 조사 및 재처리 가이드
  - [ ] 인시던트 대응 절차

---

## 요약: 핵심 포인트

### 프로덕션 수준 이메일 처리 체크리스트:

1. **적절한 제공업체 선택**:
   - AWS SES + Lambda: AWS 네이티브 스택에 적합
   - SendGrid Inbound Parse: 단순함과 안정성
   - Postmark: 깔끔한 API와 우수한 지원
   - Mailgun: 고급 라우팅과 파싱

2. **견고한 재시도 구현**:
   - 지수 백오프 + 지터
   - 최대 4-7회 재시도
   - 실패 메시지용 Dead Letter Queue
   - 지속 실패용 서킷 브레이커

3. **멱등성 보장**:
   - 멱등성 키 사용 (메시지 ID + 첨부파일 해시)
   - 모든 작업을 멱등하게 (DB + 외부 호출)
   - DLQ에서의 재처리도 안전하게

4. **크기 제한 처리**:
   - 넓은 호환성을 위해 10-20MB 안전 제한
   - MIME 인코딩 오버헤드(~33%) 고려
   - 25MB 초과 파일은 클라우드 스토리지 사용

5. **미확인 발신자 보안**:
   - SPF/DKIM/DMARC 검증
   - 의심 이메일 격리
   - 미확인 발신자에게 자동 회신 금지
   - 허용/차단 목록 구현

6. **흔한 실수 방지**:
   - winmail.dat (TNEF) 파일 파싱
   - 유니코드 파일명 올바르게 처리
   - 인라인 이미지와 실제 첨부파일 구분
   - 캘린더 초대 (.ics) 별도 처리
   - 이메일 스레드에서 첨부파일 중복 제거

7. **모든 것을 모니터링**:
   - 처리율, 실패율, 지연시간, 큐 깊이 추적
   - 알림 설정 (대시보드만으로 의존하지 않기)
   - 컴플라이언스를 위한 포괄적 감사 추적 구현

---

**문서 버전**: 1.0
**최종 업데이트**: 2026-01-30
**관리**: Hyperlounge 데이터 엔지니어링 팀
