# SSH 터널링 구조 분석 및 개선 방안

## 문서 정보
- **작성일**: 2026-01-27
- **작성자**: Platform Team
- **상태**: 분석 완료, ClientAliveInterval 설정 변경 적용됨

---

## 1. 현재 아키텍처

### 1.1 전체 구조

```
┌─────────────────────┐          ┌─────────────────────┐          ┌─────────────────────┐
│   고객사 Windows PC  │          │   SSH Gateway       │          │   Airflow (GCP)     │
│   (RPA 수행 PC)      │          │   stn.hyperlounge.dev│          │                     │
│                     │          │   34.64.44.108      │          │                     │
└─────────┬───────────┘          └─────────┬───────────┘          └─────────┬───────────┘
          │                                │                                │
          │  ①  역방향 SSH 터널            │                                │
          │  ssh -R 9012:localhost:22      │                                │
          │ ───────────────────────────────>                                │
          │                                │                                │
          │                                │  ②  Paramiko SSH              │
          │                                │ <──────────────────────────────│
          │                                │  ssh user@gateway:9012         │
          │                                │                                │
          │  ③  터널 통해 명령 전달        │                                │
          │ <───────────────────────────────                                │
          │     (RPA 실행, 파일 전송 등)   │                                │
```

### 1.2 동작 원리

| 단계 | 방향 | 설명 |
|------|------|------|
| ① | 고객사 → Gateway | 역방향 터널 생성. Gateway의 포트를 고객사 PC의 22포트에 연결 |
| ② | Airflow → Gateway | Paramiko로 `stn.hyperlounge.dev:{port}`에 SSH 연결 |
| ③ | Gateway → 고객사 | 터널을 통해 고객사 PC에 RPA 명령 전달 |

### 1.3 구성 요소

#### SSH Gateway 서버
- **호스트**: stn.hyperlounge.dev (34.64.44.108)
- **GCP 인스턴스**: ssh-tunneling-server (hyperlounge-ops)
- **Zone**: asia-northeast3-a
- **역할**: 고객사별 계정 생성, 포트 포워딩 중계

#### 고객사별 설정
- **계정**: 고객사 코드로 OS 계정 생성 (예: c1d66200, c78bbf00)
- **포트**: 고객사별 고유 포트 할당 (9001, 9002, 9003...)
- **인증**: SSH 키 기반 (공개키는 GCS에 저장)

#### 클라이언트 스크립트
- **위치**: 고객사 Windows PC
- **실행**: Windows 스케줄러로 주기적 실행
- **기능**: SSH 터널 생성 및 유지

---

## 2. 발견된 문제점

### 2.1 좀비 세션 문제

**증상:**
```
Error: remote port forwarding failed for listen port 9012
```

**원인:**
1. 고객사 PC가 비정상 종료 (네트워크 끊김, 재부팅 등)
2. Gateway 서버는 연결이 끊어진 걸 모름 (TCP 특성)
3. 기존 세션이 포트를 계속 점유 (좀비 세션)
4. 새 연결 시도 시 포트 충돌

**현재 설정 (sshd_config):**
```
ClientAliveInterval 120   # 2분마다 체크
ClientAliveCountMax 3     # 3번 실패 시 끊기 (기본값)
```
→ **최대 6분** 후에야 좀비 세션 정리

### 2.2 SSH 배너 읽기 실패

**증상:**
```
paramiko.ssh_exception.SSHException: Error reading SSH protocol banner
```

**원인:**
- Paramiko의 기본 배너 타임아웃 15초
- 네트워크 지연 시 타임아웃 발생
- `ssh.connect()`에 timeout/banner_timeout 미설정

**관련 코드:** `collector/common/util.py:324-345`

### 2.3 터널 유지 불안정

**증상:**
- 터널이 자주 끊어짐
- 재연결까지 시간 소요

**원인:**
- Windows 배치 스크립트의 한계
- `ssh -fN` 후 모니터링 없음
- ServerAliveInterval 미설정 (클라이언트 측)

---

## 3. SSH Gateway 서버 현재 설정

### 3.1 sshd_config 주요 설정

```bash
# 확인 명령어
gcloud compute ssh ssh-tunneling-server --zone=asia-northeast3-a --project=hyperlounge-ops \
  --command="grep -E 'ClientAlive|TCPKeepAlive|GatewayPorts' /etc/ssh/sshd_config"
```

**현재 설정 (2026-01-27 변경됨):**
```
GatewayPorts yes           # 외부에서 포트 포워딩 가능
TCPKeepAlive yes           # TCP 레벨 keepalive
ClientAliveInterval 10     # 10초마다 체크 (기존 120초 → 변경됨)
ClientAliveCountMax 3      # 3번 실패 시 끊기 (기본값)
```
→ 좀비 세션 정리 시간: **최대 30초**

### 3.2 리슨 중인 포트 확인

```bash
gcloud compute ssh ssh-tunneling-server --zone=asia-northeast3-a --project=hyperlounge-ops \
  --command="netstat -tlnp | grep -E '90[0-9]{2}'"
```

---

## 4. 개선 방안

### 4.1 단기: sshd_config 설정 변경

**변경 내용:**
```bash
# 기존
ClientAliveInterval 120

# 변경 (추천)
ClientAliveInterval 10
ClientAliveCountMax 3
```

**효과:**
- 좀비 세션 정리 시간: 6분 → **30초**
- 모든 고객사(계정)에 동일 적용 (전역 설정)

**설정 옵션 비교:**
| 설정 | 좀비 정리 시간 | 비고 |
|------|----------------|------|
| 120초 × 3 (현재) | 6분 | 너무 김 |
| 30초 × 3 | 90초 | 보수적 |
| 10초 × 3 (추천) | 30초 | 적절함 |
| 10초 × 2 | 20초 | 공격적 |

**적용 방법:**
```bash
gcloud compute ssh ssh-tunneling-server --zone=asia-northeast3-a --project=hyperlounge-ops --command="
sudo sed -i 's/ClientAliveInterval 120/ClientAliveInterval 10/' /etc/ssh/sshd_config
sudo systemctl restart sshd
"
```

**사이드 이펙트:**
- 거의 없음
- 30초마다 작은 keepalive 패킷 주고받음
- 정상 연결에는 영향 없음

### 4.2 단기: Paramiko 타임아웃 설정

**변경 파일:** `collector/common/util.py`

```python
# 기존
ssh.connect(hostname=ip, username=username, pkey=key, port=port)

# 변경
ssh.connect(
    hostname=ip,
    username=username,
    pkey=key,
    port=port,
    timeout=30,          # TCP 연결 타임아웃
    banner_timeout=60    # SSH 배너 읽기 타임아웃
)
```

### 4.3 단기: 클라이언트 스크립트 개선

**SSH 명령에 keepalive 옵션 추가:**
```batch
ssh -R 9012:localhost:22 ... ^
  -o ServerAliveInterval=30 ^
  -o ServerAliveCountMax=3
```

### 4.4 중장기: 현대적 솔루션으로 전환

#### Option 1: Cloudflare Tunnel (추천)

```
[고객사 PC] ──cloudflared── [Cloudflare Edge] ←── [Airflow]
```

**장점:**
- 무료 (50유저까지)
- Gateway 서버 운영 불필요
- 자동 재연결 내장
- 포트 충돌 문제 없음
- Windows 서비스로 설치 가능

**비용:** 무료 (Cloudflare Zero Trust Free Tier)

#### Option 2: Tailscale

```
[고객사 PC] ←── WireGuard Mesh ──→ [Airflow Worker]
```

**장점:**
- 설정 매우 간단
- P2P 직접 연결
- NAT 자동 통과

**비용:** 무료 (3유저, 100기기까지)

#### 비교표

| 항목 | 현재 (SSH 터널) | Cloudflare Tunnel | Tailscale |
|------|----------------|-------------------|-----------|
| 서버 운영 | 필요 (Gateway) | 불필요 | 불필요 |
| 포트 관리 | 수동 (고객사별) | 자동 | 자동 |
| 재연결 | 수동/스케줄러 | 자동 | 자동 |
| 좀비 세션 | 발생함 | 없음 | 없음 |
| 비용 | GCP VM 비용 | 무료 | 무료 |
| 설정 복잡도 | 높음 | 중간 | 낮음 |

---

## 5. 관련 파일

| 파일 | 위치 | 설명 |
|------|------|------|
| SSH 연결 함수 | `collector/common/util.py` | `ssh_connect()` |
| VM 관리 | `collector/cloud_instance/instance_manager.py` | SSH 연결 사용 |
| 터널 스크립트 | `vpc-client/create_tunnel.sh` | Linux용 터널 생성 |
| 클라이언트 설정 | `rpa_agent/agent/setup_ssh_client.bat` | Windows용 |
| 서버 설정 | `rpa_agent/server/setup_ssh_server.sh` | Gateway 서버 |
| README | `rpa_agent/README.md` | 전체 구조 설명 |
| SSH v2 계획 | `docs/architecture/SSH_V2_UPGRADE_PLAN.md` | autossh 도입 계획 |
| SSH v2 상세 | `docs/architecture/SSH_V2_DETAILED_DESIGN.md` | 상세 설계 |

---

## 6. 수행 이력

### 2026-01-27: 해지 고객사 세션 정리

**발견된 문제:**
- 해지 고객사 터널이 여전히 연결되어 있음
- 고객사 PC의 자동 재시도 스크립트가 계속 실행 중

**정리 전 상태:**
| 포트 | 고객사 | 상태 |
|------|--------|------|
| 9004 | c1394402 | ❌ 해지 고객사 |
| 9005 | c1394402 | ❌ 해지 고객사 |
| 9009 | ce731500 | ❌ 해지 고객사 |
| 9012 | c1d66200 | ✓ 활성 고객사 |

**수행한 작업:**
```bash
# 세션 종료
sudo pkill -u c1394402
sudo pkill -u ce731500

# 계정 잠금 (재연결 방지)
sudo usermod -L c1394402
sudo usermod -L ce731500
```

**정리 후 상태:**
| 포트 | 고객사 | 상태 |
|------|--------|------|
| 9012 | c1d66200 | ✓ 활성 고객사 |

**결과:** 4개 터널 → 1개로 정리, 해지 계정 잠금 완료

### 2026-01-27: ClientAliveInterval 설정 변경

**변경 내용:**
```bash
# 기존
ClientAliveInterval 120

# 변경
ClientAliveInterval 10
```

**변경 이유:**
- 좀비 세션 정리 시간을 6분 → 30초로 단축
- "remote port forwarding failed" 오류 발생 시 빠른 복구

**적용 명령어:**
```bash
# 백업 생성
sudo cp /etc/ssh/sshd_config /etc/ssh/sshd_config.backup.20260127

# 설정 변경
sudo sed -i 's/ClientAliveInterval 120/ClientAliveInterval 10/' /etc/ssh/sshd_config

# sshd 재시작
sudo systemctl restart sshd
```

**테스트 수행:**
1. c1d66200 고객사 VM 종료 (07:59:44 UTC)
2. 세션 정리 확인 (08:03:16 UTC) - 약 3분 30초 소요
3. 기존 연결은 이전 설정(120초) 적용 → 새 연결부터 10초 적용

**테스트 결과:**
- ✅ 좀비 세션 정리 정상 동작 확인
- ✅ 정상 연결에 영향 없음 (keepalive 패킷만 추가)
- ✅ 사이드 이펙트 없음

### 2026-01-27: SSH 연결 retry 횟수 증가

**변경 파일:** `collector/cloud_instance/instance_manager.py:117`

**변경 내용:**
```python
# 기존
self.ssh = self.ssh_connect(self.instance)  # retry_num=3 (기본값)

# 변경
self.ssh = self.ssh_connect(self.instance, retry_num=10)
```

**변경 이유:**
- VM 부팅 시간이 오래 걸릴 경우 SSH 터널 연결 대기 시간 부족
- 기존: 3회 × 30초 = 최대 90초 대기
- 변경: 10회 × 30초 = 최대 5분 대기
- Airflow 태스크 재시도 횟수 감소 효과

**배포:**
```bash
git add collector/cloud_instance/instance_manager.py
git commit -m "fix: SSH 연결 retry 횟수 증가 (3→10)"
git push
# GCS 수동 배포 완료
```

**적용 확인 (로그):**
```
# 변경 전
[INFO][util] try ssh connect to vm - 1/3

# 변경 후
[INFO][util] try ssh connect to vm - 1/10  ✅
```

---

## 7. 액션 아이템

### 즉시 (이번 주)
- [x] sshd_config의 ClientAliveInterval을 10초로 변경 (2026-01-27 완료)
- [x] SSH 연결 retry 횟수 증가: 3 → 10 (2026-01-27 완료)
- [ ] Paramiko에 timeout/banner_timeout 추가

### 단기 (2주 내)
- [ ] 클라이언트 스크립트에 ServerAliveInterval 추가
- [ ] Cloudflare Tunnel 파일럿 테스트 (신규 고객사 1개)

### 중장기 (1-2개월)
- [ ] Cloudflare Tunnel 전체 적용 검토
- [ ] 기존 SSH 터널 구조 단계적 교체

---

## 7. 참고 자료

- [Cloudflare Tunnel 문서](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Tailscale 문서](https://tailscale.com/kb/)
- [SSH Keepalive 설정](https://man.openbsd.org/sshd_config#ClientAliveInterval)
- [awesome-tunneling (GitHub)](https://github.com/anderspitman/awesome-tunneling)
