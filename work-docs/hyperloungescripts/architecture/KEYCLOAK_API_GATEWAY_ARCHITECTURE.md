# Keycloak + API Gateway 아키텍처

## 개요

Hyperlounge의 인증/인가 시스템은 **Keycloak**(인증 서버)과 **API Gateway**(Apigee)로 구성되어 있다.

- **Keycloak**: 사용자 로그인 및 JWT 토큰 발급 (누구인지 확인)
- **API Gateway (Apigee)**: 토큰 검증 + 요청 라우팅 (어디로 보낼지 결정)

---

## 도입 배경

### Before: Django 내장 인증

각 서비스마다 Django User 모델로 로그인을 처리하고 있었다.

```
CIM 서버 → "로그인 해" → DB 조회 → OK
MIM 서버 → "로그인 해" → DB 조회 → OK
HR 서버  → "로그인 해" → DB 조회 → OK
```

| 문제 | 구체적으로 |
|------|-----------|
| 인증 분산 | CIM, MIM, HR, API 서버마다 각각 로그인 처리 |
| 비밀번호 관리 | Django `pbkdf2_sha256` 해싱에 묶여있음 |
| 권한 관리 어려움 | 서비스별로 누가 뭘 할 수 있는지 제각각 |
| 토큰 없음 | JWT 기반 API 인증 불가 |
| 모바일 지원 어려움 | 오프라인 세션, 리프레시 토큰 없음 |

### After: Keycloak 중앙 인증

```
Keycloak → "로그인 해" → 토큰 발급
CIM 서버 → 토큰만 확인 → OK
MIM 서버 → 토큰만 확인 → OK
HR 서버  → 토큰만 확인 → OK
```

한 번 로그인하면 JWT 토큰을 받고, 그 토큰으로 모든 서비스에 접근한다.

---

## 전체 아키텍처

```
사용자
  │
  │ 1. 로그인 (ID/PW)
  ▼
Keycloak (GKE Private Cluster)
  │
  │ 2. JWT 토큰 발급
  ▼
사용자 (토큰 보관)
  │
  │ 3. API 호출 (토큰 첨부)
  ▼
API Gateway (Apigee)
  │
  │ 4. 토큰 검증 + 역할 체크 + 라우팅
  │
  ├──→ CIM 서비스 (HR 역할 필요)
  ├──→ MIM 서비스 (PVCT/ADMIN 역할 필요)
  ├──→ HR 서비스  (로그인만 되면 OK)
  └──→ API 서버   (로그인만 되면 OK)
```

---

## Keycloak (인증 서버)

### 역할

사용자 관리와 토큰 발급을 담당한다. 모든 서비스가 공유하는 **단일 유저 저장소**이다.

### 사용자 데이터

User 테이블은 Keycloak DB(PostgreSQL) 안에 있다. 각 서비스가 따로 가지고 있지 않다.

```
Keycloak (PostgreSQL DB)
├── user_entity         ← 사용자 정보 (ID, 이름, 이메일)
├── credential          ← 비밀번호 (해싱된)
├── user_role_mapping   ← 이 사람이 무슨 역할인지
└── user_group_membership ← 이 사람이 무슨 그룹인지
```

기존 Django DB의 유저는 `keycloak_migration/` 스크립트로 이관했다. Django의 `pbkdf2_sha256` 비밀번호 해싱을 Keycloak이 그대로 지원하므로 사용자 비밀번호 재설정 없이 마이그레이션이 가능했다.

### 배포 정보

| 항목 | 값 |
|------|-----|
| 버전 | 21.1.1 |
| 위치 | GKE Private Cluster (VPC 내부) |
| DB | PostgreSQL (Cloud SQL) |
| Realm | `hl_ops` (prod) / `hl_ops_qa` (QA) |
| 내부 주소 | `10.188.8.26` (prod) / `10.178.0.66` (dev) |
| 접근 방식 | SSH 터널 (bastion host) |

외부 인터넷에서 직접 접근 불가. VPC 내부에서만 동작한다.

### 세션 설정

| 항목 | 값 |
|------|-----|
| SSO Session Idle | 7일 |
| SSO Session Max | 30일 |
| Offline Session (모바일) | 365일 |
| Refresh Token Revoke | 활성화 |

### JWT 토큰 구조

로그인 시 Keycloak이 발급하는 토큰 내용:

```json
{
  "sub": "user-uuid",
  "preferred_username": "김철수",
  "email": "kim@company.com",
  "realm_access": {
    "roles": ["HR"]
  },
  "exp": 1706000000
}
+ 서명 (Keycloak 개인키로 암호화)
```

### 토큰 검증 방식

**Keycloak DB에 매번 확인하지 않는다.** JWT는 자체 검증이 가능하다.

```
로그인 시 (1번만):
  사용자 → Keycloak: ID/PW
  Keycloak → 사용자: JWT 토큰 발급 (개인키로 서명)

API 호출 시 (매번):
  API Gateway가 공개키로 서명만 검증
  → Keycloak에 안 물어봄
  → 공개키는 JWKS 엔드포인트에서 한 번만 가져오면 됨
```

여권에 비유하면:
- 여권청(Keycloak)이 여권(토큰)을 발급
- 공항(API Gateway)은 여권의 위조 여부만 확인
- 매번 여권청에 전화하지 않음

---

## API Gateway (Apigee)

### 역할

모든 API 요청이 거쳐가는 **관문(프록시)**이다. 두 가지를 한다:

1. **검문**: 토큰 유효한지, 역할 맞는지 확인
2. **라우팅**: 경로 보고 올바른 내부 서비스로 전달

### 프록시 개념

사용자는 실제 서비스 주소를 모른다. `api.hyperlounge.dev` 하나만 알면 된다.

```
프록시 없을 때:
  사용자 → cim.internal.server:8080/customers     (직접 접근)
  사용자 → mim.internal.server:3000/menus          (직접 접근)
  사용자 → hr.internal.server:5000/employees        (직접 접근)
  → 주소 다 알아야 하고, 각각 인증도 따로

프록시 있을 때:
  사용자 → api.hyperlounge.dev/cim/customers       (프록시가 대신 전달)
  사용자 → api.hyperlounge.dev/mim/menus           (프록시가 대신 전달)
  사용자 → api.hyperlounge.dev/hr/employees         (프록시가 대신 전달)
  → 주소 하나, 인증도 한 번
```

내부 서비스 주소(`10.188.x.x`)가 외부에 노출되지 않는다.

### 요청 처리 흐름

`/cim/customers` 호출 시:

```
Step 1: Validate-Auth-Header    ← Authorization 헤더 있나?
Step 2: Extract-Bearer-Token    ← "Bearer xxx"에서 토큰 추출
Step 3: Verify-Keycloak-JWT     ← 토큰 서명 검증 (공개키로)
Step 4: RBAC-Check-HR           ← HR 역할 있나 확인
Step 5: Route to cim-service    ← CIM 서비스로 전달
```

### 경로별 접근 규칙

```
┌─────────────┬──────────────────┬────────────────┐
│ 경로        │ 토큰 검증        │ 필요한 역할    │
├─────────────┼──────────────────┼────────────────┤
│ /auth/**    │ 안 함            │ 없음           │
│ /cim/**     │ 함               │ HR             │
│ /mim/**     │ 함               │ PVCT or ADMIN  │
│ /hr/**      │ 함               │ 로그인만       │
│ /api/**     │ 함               │ 로그인만       │
└─────────────┴──────────────────┴────────────────┘
```

### 라우팅 설정

```
apigee/apiproxy/
├── proxies/default.xml    ← 입구 규칙 (검증 + 라우팅)
└── targets/               ← 출구 주소 (실제 서비스)
    ├── keycloak.xml       → /auth/** → Keycloak 내부 주소
    ├── cim-service.xml    → /cim/**  → CIM 내부 주소
    ├── mim-service.xml    → /mim/**  → MIM 내부 주소
    ├── hr-service.xml     → /hr/**   → HR 내부 주소
    └── api-server.xml     → /api/**  → API 내부 주소
```

proxy = 입구 규칙, target = 출구 주소.

---

## 권한 체크: 2단계 구조

### API Gateway 레벨 (거친 필터)

서비스 접근 가능 여부를 판단한다. XML 설정으로 정의:

```xml
<!-- HR 역할 체크: realm_access에 "HR"이 없으면 403 -->
<Condition>
  (jwt.realm_access = null) or NOT (jwt.realm_access ~~ ".*HR.*")
</Condition>

<!-- PVCT 역할 체크: PVCT도 없고 ADMIN도 없으면 403 -->
<Condition>
  (jwt.realm_access = null) or
  (NOT (jwt.realm_access ~~ ".*PVCT.*") and NOT (jwt.realm_access ~~ ".*ADMIN.*"))
</Condition>
```

### 서비스 내부 레벨 (세밀한 필터)

기능별 세부 권한은 각 서비스 내부에서 체크한다.

```
예시:
  /cim/고객목록 → HR이면 볼 수 있음
  /cim/고객삭제 → HR 중에서도 매니저만 가능
  /cim/설정변경 → ADMIN만 가능
```

| 체크 위치 | 뭘 체크하나 | 비유 |
|-----------|------------|------|
| API Gateway | 서비스 접근 가능 여부 | 건물 출입증 |
| 서비스 내부 | 기능별 세부 권한 | 각 부서 담당자 확인 |

API Gateway는 **문지기**, 서비스는 **담당자**. 문지기는 출입증(역할)만 보고 건물에 들여보내고, 안에서 담당자가 세부 업무 권한을 판단한다.

---

## API Gateway 변천사: KrakenD → Apigee

### KrakenD (이전) - 오픈소스, 직접 운영

```
- 무료 (오픈소스)
- Docker로 빌드해서 Cloud Run에 배포
- Go 플러그인 직접 개발 (google-auth-header.go)
- 관련 파일: krakend/ 디렉토리
```

### Apigee (현재) - Google 유료 관리형 서비스

```
- 유료 (BASE 환경 월 ~$365)
- XML 설정만 올리면 Google이 운영
- Rate Limiting, 모니터링 기본 제공
- 관련 파일: apigee/ 디렉토리
```

### 전환 이유

| | KrakenD | Apigee |
|---|---|---|
| 비용 | 서버비만 | 월 $365+ |
| 운영 | 직접 배포, 모니터링, 장애 대응 | Google이 해줌 |
| 기능 | 직접 플러그인 개발 필요 | Rate Limiting 등 기본 제공 |
| 안정성 | 직접 책임 | Google SLA |

돈을 내는 대신 운영 부담을 줄인 것.

---

## 관련 파일

| 구성 요소 | 경로 |
|-----------|------|
| Keycloak 배포 | `keycloak/` |
| 유저 마이그레이션 | `keycloak_migration/` |
| API Gateway (현재) | `apigee/` |
| API Gateway (이전) | `krakend/` |
| API 스펙 문서 | `api-gateway/openapi-spec.yaml` |

## 환경별 정보

| 환경 | 프로젝트 | Keycloak IP | API URL |
|------|----------|-------------|---------|
| Dev | hyperlounge-dev | 10.178.0.66 | api-dev.hyperlounge.dev |
| QA | hyperlounge-dev | 10.178.0.66 | api-qa.hyperlounge.dev |
| Prod | hyperlounge-ops | 10.188.8.26 | api.hyperlounge.dev |
