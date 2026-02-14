# SSH v2 업그레이드 상세 설계 문서

## 목차
1. [현재 아키텍처 분석](#1-현재-아키텍처-분석)
2. [문제점 분석](#2-문제점-분석)
3. [신규 아키텍처 설계](#3-신규-아키텍처-설계)
4. [구현 계획](#4-구현-계획)
5. [배포 전략](#5-배포-전략)
6. [테스트 계획](#6-테스트-계획)
7. [롤백 계획](#7-롤백-계획)

---

## 1. 현재 아키텍처 분석

### 1.1 전체 구조

```
[고객사 현장]                    [SSH Gateway]                [Hyperlounge GCP]
    └─ DB                          └─ stn.hyperlounge.dev         └─ Airflow DAG
    └─ Windows PC                      (34.64.84.46)                 └─ RPA VM Control
         │                                  │
         │ ← OpenSSH Tunnel ← crontab ─────┤
         └─→ Paramiko SSH ─────────────────→
```

### 1.2 현재 컴포넌트

#### A. SSH 터널링 (고객사 → Gateway)

**파일**: `vpc-client/create_tunnel.sh`

```bash
# 역방향 SSH 터널 생성
ssh -f -N -i $key_file -R $remote_port:$private_addr:$private_port $user_id@$ssh_server
```

**특징**:
- OpenSSH 네이티브 사용
- crontab으로 5-10분마다 실행 (연결 끊김 시 재연결)
- 역방향 터널: 고객사 DB → GCP 접근 가능

**관련 고객사**:
- c78bbf00 (매일홀딩스)
- c3a40f00 (한국카본)
- c1d66200 (GC녹십자)

#### B. SSH 명령 실행 (GCP → 고객사 RPA PC)

**파일**: `collector/common/util.py`

```python
def ssh_connect(ip, username, string_private_key=None, port=22, password=None,
                retry_num=20, sleep=10):
    # Paramiko SSHClient 사용
    # 최대 20회 재시도 (10초 간격)
    # RSA 키 또는 패스워드 인증
```

**사용 위치**:
- `collector/cloud_instance/instance_manager.py`: VM 관리
- `collector/rpa/rpa_crawler.py`: RPA 작업 실행
- `airflow-dags/dags/dependencies/task_functions.py`: DAG 태스크

**주요 기능**:
- UiPath RPA 실행
- Windows 스케줄 작업 생성/실행
- 파일 업/다운로드 (SFTP)
- VM 상태 확인

#### C. SSH 서버 설정

**파일**: `rpa_agent/server/setup_ssh_server.sh`

**서버 정보**:
- 호스트: `stn.hyperlounge.dev` (34.64.84.46)
- 사용자: 고객사별 (customer_code)
- 인증: RSA Public Key (GCS에서 로드)
- 경로: `gs://hyperlounge-collect-config/{customer_code}/pubkey`

**SSHD 설정**:
```bash
AllowTcpForwarding yes
GatewayPorts yes
TCPKeepAlive yes
```

#### D. SSH 모니터링

**파일**: `rpa_agent/main.py`

```python
def check_rpa_ssh_tunnel(request):
    # 모든 고객사 RPA 인스턴스 SSH 연결 확인
    # Paramiko로 연결 테스트 (dir 명령어 실행)
    # 실패 시 Teams 웹훅 알림
```

**스케줄**: Cloud Scheduler로 주기적 실행

---

## 2. 문제점 분석

### 2.1 터널링 계층

| 문제 | 영향도 | 설명 |
|------|--------|------|
| **수동 재연결** | 🔴 High | crontab 주기(5-10분) 동안 터널 끊김 상태 유지 |
| **연결 상태 감지 지연** | 🟡 Medium | 터널 끊김을 즉시 감지하지 못함 |
| **로그 부족** | 🟡 Medium | 터널 재연결 실패 시 디버깅 어려움 |

### 2.2 Python SSH 계층

| 문제 | 영향도 | 설명 |
|------|--------|------|
| **장시간 연결 불안정** | 🟡 Medium | Paramiko 세션이 오래 유지되면 끊김 |
| **복잡한 재시도 로직** | 🟡 Medium | 20회 재시도 (최대 3분+ 대기) |
| **에러 핸들링 불명확** | 🟢 Low | 어떤 에러에서 재시도할지 명확하지 않음 |

### 2.3 모니터링 계층

| 문제 | 영향도 | 설명 |
|------|--------|------|
| **사후 감지** | 🟡 Medium | 이미 실패한 후 알림 (사전 방지 불가) |
| **알림 지연** | 🟢 Low | 스케줄러 주기에 따라 감지 지연 |

---

## 3. 신규 아키텍처 설계

### 3.1 개선 방향

```
┌─────────────────────────────────────────────────────────────────┐
│                   SSH v2 3-Layer Architecture                    │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: Tunneling (autossh + systemd)                          │
│   - 즉시 자동 재연결 (30초 간격 keepalive)                      │
│   - systemd로 프로세스 관리 및 자동 재시작                      │
│   - 구조화된 로깅 (journalctl)                                  │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: Command Execution (Paramiko 유지 or AsyncSSH)          │
│   - 기존 Paramiko 유지 (안정성 문제 없으면)                     │
│   - 또는 AsyncSSH로 교체 (비동기 지원 필요 시)                  │
├─────────────────────────────────────────────────────────────────┤
│ Layer 3: Monitoring (기존 유지 + 로그 개선)                     │
│   - check_rpa_ssh_tunnel 유지                                   │
│   - autossh/systemd 로그 통합                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 autossh 도입

#### 변경 전

```bash
#!/bin/sh
# vpc-client/create_tunnel.sh

ssh -f -N -i $key_file -R $remote_port:$private_addr:$private_port $user_id@$ssh_server
```

#### 변경 후

```bash
#!/bin/sh
# vpc-client/create_tunnel_v2.sh

autossh -M 0 \
  -f -N \
  -i $key_file \
  -R $remote_port:$private_addr:$private_port \
  $user_id@$ssh_server \
  -o "ServerAliveInterval=30" \
  -o "ServerAliveCountMax=3" \
  -o "ExitOnForwardFailure=yes" \
  -o "StrictHostKeyChecking=no"
```

**옵션 설명**:
- `-M 0`: 모니터링 포트 비활성화 (ServerAlive 옵션 사용)
- `ServerAliveInterval=30`: 30초마다 keepalive 패킷 전송
- `ServerAliveCountMax=3`: 3회 실패 시 연결 종료 후 재연결
- `ExitOnForwardFailure=yes`: 포트 포워딩 실패 시 즉시 종료
- `StrictHostKeyChecking=no`: 호스트 키 검증 스킵 (자동화를 위해)

### 3.3 systemd 서비스 관리

#### 서비스 파일

**파일**: `/etc/systemd/system/ssh-tunnel@.service`

```ini
[Unit]
Description=SSH Tunnel for %I
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={customer_code}
Environment="AUTOSSH_GATETIME=0"
Environment="AUTOSSH_LOGFILE=/var/log/ssh-tunnel-%I.log"
ExecStart=/usr/bin/autossh -M 0 -N \
  -o "ServerAliveInterval=30" \
  -o "ServerAliveCountMax=3" \
  -o "ExitOnForwardFailure=yes" \
  -R {remote_port}:{private_addr}:{private_port} \
  {user_id}@{ssh_server} \
  -i /home/{customer_code}/.ssh/id_rsa
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**사용법**:
```bash
# 서비스 시작
systemctl start ssh-tunnel@c78bbf00

# 서비스 활성화 (부팅 시 자동 시작)
systemctl enable ssh-tunnel@c78bbf00

# 상태 확인
systemctl status ssh-tunnel@c78bbf00

# 로그 확인
journalctl -u ssh-tunnel@c78bbf00 -f
```

### 3.4 Python SSH 개선 (선택사항)

**현재 상태**: Paramiko가 특별한 문제를 일으키지 않으면 유지

**개선 옵션**:

#### Option 1: Paramiko 유지 + 연결 풀 추가

```python
# collector/common/ssh_pool.py (신규)

from paramiko import SSHClient
from queue import Queue, Empty
import threading

class SSHConnectionPool:
    def __init__(self, host, username, key, pool_size=5):
        self.host = host
        self.username = username
        self.key = key
        self.pool = Queue(maxsize=pool_size)
        self._lock = threading.Lock()

        for _ in range(pool_size):
            self.pool.put(self._create_connection())

    def _create_connection(self):
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(self.host, username=self.username, pkey=self.key)
        return ssh

    def get_connection(self, timeout=10):
        try:
            conn = self.pool.get(timeout=timeout)
            if not self._is_active(conn):
                conn = self._create_connection()
            return conn
        except Empty:
            return self._create_connection()

    def return_connection(self, conn):
        if self._is_active(conn):
            self.pool.put(conn)
        else:
            conn.close()

    @staticmethod
    def _is_active(conn):
        transport = conn.get_transport()
        return transport and transport.is_active()
```

#### Option 2: AsyncSSH 교체 (비동기 필요 시)

```python
# collector/common/async_ssh.py (신규)

import asyncssh
import asyncio

class AsyncSSHClient:
    def __init__(self, host, username, key):
        self.host = host
        self.username = username
        self.key = key
        self._conn = None

    async def connect(self):
        self._conn = await asyncssh.connect(
            self.host,
            username=self.username,
            client_keys=[self.key],
            known_hosts=None
        )
        return self._conn

    async def exec_command(self, command):
        result = await self._conn.run(command)
        return result.stdout, result.stderr, result.exit_status

    async def close(self):
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
```

**추천**: **Option 1 (Paramiko + 연결 풀)**
- 기존 코드 호환성 유지
- 연결 재사용으로 성능 향상
- 안정성 개선

---

## 4. 구현 계획

### Phase 1: autossh 도입 (우선순위 고객사)

#### Step 1.1: 인프라 준비 (1일)

**작업 내용**:
- [ ] 대상 고객사 현장 PC에 autossh 설치
  - 매일홀딩스 (c78bbf00)
  - 한국카본 (c3a40f00)
  - GC녹십자 (c1d66200)

**설치 스크립트**:
```bash
# install_autossh.sh
#!/bin/bash

# Ubuntu/Debian
if command -v apt-get &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y autossh
fi

# CentOS/RHEL
if command -v yum &> /dev/null; then
    sudo yum install -y autossh
fi

# 설치 확인
autossh -V
```

#### Step 1.2: 스크립트 업데이트 (1일)

**작업 내용**:
- [ ] `vpc-client/create_tunnel.sh` → `vpc-client/create_tunnel_v2.sh` 생성
- [ ] autossh 옵션 추가
- [ ] 로그 경로 설정

**파일**: `vpc-client/create_tunnel_v2.sh`

```bash
#!/bin/sh
# Copyright (C) 2025 Hyperlounge, All rights reserved.
#
# @file     create_tunnel_v2.sh
# @brief    make autossh tunnel between private service and remote ssh server
# @author   [Your Name]
# @since    2025.01.20

set -x

BASE_DIR="$( cd "$( dirname "$0" )" && pwd -P )"
LOG_DIR="${BASE_DIR}/logs"
mkdir -p ${LOG_DIR}

exit_with_usage() {
    cat << EOF

Usage$ $0 [OPTIONS] REMOTE_PORT

OPTIONS:
    -h, --help          show this help message and exit
    -s, --ssh-server    remote ssh server
    -l, --private-addr  private service address (ex: DB)
    -p, --private-port  private service port
    -u, --user-id       user ID for SSH client
    -k, --key-file      private key of SSH client
    --no-systemd        don't create systemd service (use autossh directly)
EOF
    exit 1
}

###########################
######## Arguments ########
###########################
ssh_server="stn.hyperlounge.dev"
private_addr=
private_port=
key_file=
user_id=
use_systemd=true

while [ 1 ]; do
    cnt=$#
    case $1 in
        (-h|--help)             exit_with_usage;;
        (-s|--ssh-server)       shift; ssh_server=$1; shift;;
        (-l|--private-addr)     shift; private_addr=$1; shift;;
        (-p|--private-port)     shift; private_port=$1; shift;;
        (-u|--user-id)          shift; user_id=$1; shift;;
        (-k|--key-file)         shift; key_file=$1; shift;;
        (--no-systemd)          use_systemd=false; shift;;
        (--)                    shift; break;;
    esac
    [ $# -eq $cnt ] && { break; }
done
[ $# -lt 1 ] && { exit_with_usage; }
[ -z "$ssh_server" ] || [ -z "$private_addr" ] || [ -z "$private_port" ] || [ -z "$user_id" ] || [ -z "$key_file" ] && { exit_with_usage; }
remote_port=$1

# Check if autossh is installed
if ! command -v autossh &> /dev/null; then
    echo "Error: autossh is not installed"
    echo "Please install it with: apt install autossh (Ubuntu/Debian) or yum install autossh (CentOS/RHEL)"
    exit 1
fi

# Kill existing tunnel if exists
pkill -f "autossh.*${remote_port}:${private_addr}:${private_port}"
sleep 2

# Start autossh tunnel
echo "Starting autossh tunnel: ${remote_port} -> ${private_addr}:${private_port}"
export AUTOSSH_GATETIME=0
export AUTOSSH_LOGFILE="${LOG_DIR}/autossh_${user_id}_${remote_port}.log"

autossh -M 0 \
    -f -N \
    -i ${key_file} \
    -R ${remote_port}:${private_addr}:${private_port} \
    ${user_id}@${ssh_server} \
    -o "ServerAliveInterval=30" \
    -o "ServerAliveCountMax=3" \
    -o "ExitOnForwardFailure=yes" \
    -o "StrictHostKeyChecking=no"

# Check if tunnel is running
sleep 3
if pgrep -f "autossh.*${remote_port}:${private_addr}:${private_port}" > /dev/null; then
    echo "✓ autossh tunnel started successfully"
    echo "Log file: ${AUTOSSH_LOGFILE}"
    exit 0
else
    echo "✗ Failed to start autossh tunnel"
    exit 1
fi
```

#### Step 1.3: systemd 서비스 생성 (선택사항, 1일)

**작업 내용**:
- [ ] systemd 서비스 템플릿 작성
- [ ] 고객사별 서비스 파일 생성
- [ ] 서비스 활성화 및 테스트

**파일**: `vpc-client/install_systemd_service.sh`

```bash
#!/bin/bash
# install_systemd_service.sh

CUSTOMER_CODE=$1
REMOTE_PORT=$2
PRIVATE_ADDR=$3
PRIVATE_PORT=$4
SSH_SERVER="stn.hyperlounge.dev"
KEY_FILE="/home/${CUSTOMER_CODE}/.ssh/id_rsa"

if [ -z "$CUSTOMER_CODE" ] || [ -z "$REMOTE_PORT" ] || [ -z "$PRIVATE_ADDR" ] || [ -z "$PRIVATE_PORT" ]; then
    echo "Usage: $0 <customer_code> <remote_port> <private_addr> <private_port>"
    exit 1
fi

SERVICE_FILE="/etc/systemd/system/ssh-tunnel-${CUSTOMER_CODE}.service"

cat > ${SERVICE_FILE} <<EOF
[Unit]
Description=SSH Tunnel for ${CUSTOMER_CODE}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CUSTOMER_CODE}
Environment="AUTOSSH_GATETIME=0"
Environment="AUTOSSH_LOGFILE=/var/log/ssh-tunnel-${CUSTOMER_CODE}.log"
ExecStart=/usr/bin/autossh -M 0 -N \\
  -o "ServerAliveInterval=30" \\
  -o "ServerAliveCountMax=3" \\
  -o "ExitOnForwardFailure=yes" \\
  -o "StrictHostKeyChecking=no" \\
  -R ${REMOTE_PORT}:${PRIVATE_ADDR}:${PRIVATE_PORT} \\
  ${CUSTOMER_CODE}@${SSH_SERVER} \\
  -i ${KEY_FILE}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload

# Enable and start service
systemctl enable ssh-tunnel-${CUSTOMER_CODE}.service
systemctl start ssh-tunnel-${CUSTOMER_CODE}.service

# Check status
systemctl status ssh-tunnel-${CUSTOMER_CODE}.service

echo "✓ systemd service installed: ssh-tunnel-${CUSTOMER_CODE}.service"
echo "  Start:   systemctl start ssh-tunnel-${CUSTOMER_CODE}"
echo "  Stop:    systemctl stop ssh-tunnel-${CUSTOMER_CODE}"
echo "  Status:  systemctl status ssh-tunnel-${CUSTOMER_CODE}"
echo "  Logs:    journalctl -u ssh-tunnel-${CUSTOMER_CODE} -f"
```

#### Step 1.4: 테스트 (1일)

**테스트 항목**:
- [ ] 정상 연결 확인
- [ ] 네트워크 끊김 시 자동 재연결 테스트
- [ ] SSH 서버 재시작 시 재연결 테스트
- [ ] 로그 확인 및 모니터링

**테스트 스크립트**:
```bash
# test_autossh.sh
#!/bin/bash

CUSTOMER_CODE=$1
REMOTE_PORT=$2

echo "=== Test 1: Check tunnel is running ==="
ps aux | grep autossh | grep ${CUSTOMER_CODE}

echo ""
echo "=== Test 2: Check connection from gateway ==="
ssh stn.hyperlounge.dev -l ${CUSTOMER_CODE} "netstat -an | grep ${REMOTE_PORT}"

echo ""
echo "=== Test 3: Simulate network failure ==="
echo "Killing autossh process..."
pkill -f "autossh.*${CUSTOMER_CODE}"
sleep 35
echo "Checking if autossh restarted..."
ps aux | grep autossh | grep ${CUSTOMER_CODE}

echo ""
echo "=== Test 4: Check logs ==="
tail -20 /var/log/ssh-tunnel-${CUSTOMER_CODE}.log
```

### Phase 2: Python SSH 개선 (선택사항)

#### Step 2.1: 연결 풀 구현 (2일)

**작업 내용**:
- [ ] `collector/common/ssh_pool.py` 구현
- [ ] 기존 `ssh_connect` 래핑
- [ ] 단위 테스트 작성

#### Step 2.2: 기존 코드 마이그레이션 (3일)

**작업 내용**:
- [ ] `collector/cloud_instance/instance_manager.py` 업데이트
- [ ] `collector/rpa/rpa_crawler.py` 업데이트
- [ ] 통합 테스트

### Phase 3: 모니터링 강화 (1일)

**작업 내용**:
- [ ] `rpa_agent/main.py`에 autossh 로그 체크 추가
- [ ] systemd 상태 확인 추가
- [ ] Teams 알림 메시지 개선

**파일**: `rpa_agent/check_autossh_status.py` (신규)

```python
import subprocess
import requests

def check_autossh_status(customer_code):
    """Check if autossh service is running"""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", f"ssh-tunnel-{customer_code}"],
            capture_output=True,
            text=True
        )
        return result.stdout.strip() == "active"
    except Exception as e:
        return False

def check_tunnel_connectivity(customer_code, port):
    """Check if tunnel port is listening on gateway"""
    try:
        result = subprocess.run(
            ["ssh", f"{customer_code}@stn.hyperlounge.dev",
             f"netstat -an | grep {port}"],
            capture_output=True,
            text=True
        )
        return str(port) in result.stdout
    except Exception as e:
        return False

def send_teams_alert(customer_code, issue):
    """Send alert to Teams"""
    webhook_url = "https://your-teams-webhook-url"
    message = {
        "title": f"SSH Tunnel Alert: {customer_code}",
        "text": f"Issue detected: {issue}",
        "themeColor": "ff0000"
    }
    requests.post(webhook_url, json=message)
```

---

## 5. 배포 전략

### 5.1 단계별 배포 (Phased Rollout)

| Phase | 대상 | 기간 | 목표 |
|-------|------|------|------|
| **Pilot** | 매일홀딩스 (c78bbf00) | 1주 | 안정성 검증 |
| **Expansion** | 한국카본 (c3a40f00)<br>GC녹십자 (c1d66200) | 1주 | 확장 가능성 검증 |
| **Full Rollout** | 나머지 SSH 터널 고객사 | 2주 | 전체 적용 |

### 5.2 배포 체크리스트

#### Pilot Phase (매일홀딩스)

**사전 준비**:
- [ ] 고객사 담당자에게 업그레이드 공지 (3일 전)
- [ ] 롤백 계획 수립 및 공유
- [ ] 백업 스크립트 준비

**배포 당일**:
1. [ ] 기존 터널 상태 확인 및 로그 백업
2. [ ] autossh 설치
3. [ ] create_tunnel_v2.sh 배포
4. [ ] 기존 터널 중지
5. [ ] autossh 터널 시작
6. [ ] 연결 테스트 (DB 쿼리, RPA 실행)
7. [ ] 1시간 동안 모니터링

**사후 모니터링** (1주일):
- [ ] 매일 아침 터널 상태 확인
- [ ] 로그 분석 (재연결 빈도, 에러)
- [ ] 고객사 피드백 수집

#### Expansion Phase

**매 고객사마다 Pilot Phase 체크리스트 반복**

### 5.3 배포 시간대

- **권장 시간**: 업무 시간 외 (오후 6시 이후)
- **요일**: 화요일 또는 수요일 (문제 발생 시 대응 시간 확보)
- **예상 다운타임**: 5-10분

---

## 6. 테스트 계획

### 6.1 단위 테스트

#### Test Case 1: autossh 설치 확인

```bash
#!/bin/bash
# test_autossh_installed.sh

if command -v autossh &> /dev/null; then
    echo "✓ autossh is installed"
    autossh -V
    exit 0
else
    echo "✗ autossh is not installed"
    exit 1
fi
```

#### Test Case 2: 터널 연결 확인

```bash
#!/bin/bash
# test_tunnel_connection.sh

CUSTOMER_CODE=$1
REMOTE_PORT=$2

# Check if autossh is running
if pgrep -f "autossh.*${CUSTOMER_CODE}" > /dev/null; then
    echo "✓ autossh process is running"
else
    echo "✗ autossh process is not running"
    exit 1
fi

# Check if port is listening on gateway
ssh ${CUSTOMER_CODE}@stn.hyperlounge.dev "netstat -an | grep ${REMOTE_PORT}" > /dev/null
if [ $? -eq 0 ]; then
    echo "✓ Port ${REMOTE_PORT} is listening on gateway"
else
    echo "✗ Port ${REMOTE_PORT} is NOT listening on gateway"
    exit 1
fi
```

#### Test Case 3: 자동 재연결 테스트

```bash
#!/bin/bash
# test_auto_reconnect.sh

CUSTOMER_CODE=$1

echo "=== Killing autossh process ==="
pkill -f "autossh.*${CUSTOMER_CODE}"

echo "Waiting 40 seconds for reconnection..."
sleep 40

echo "=== Checking if autossh restarted ==="
if pgrep -f "autossh.*${CUSTOMER_CODE}" > /dev/null; then
    echo "✓ autossh successfully reconnected"
    exit 0
else
    echo "✗ autossh did NOT reconnect"
    exit 1
fi
```

### 6.2 통합 테스트

#### Test Case 4: RPA 실행 테스트

```python
# test_rpa_via_tunnel.py

from collector.common.util import ssh_connect, ssh_exec_command

def test_rpa_execution(customer_code, ip, username, key):
    """Test RPA execution over SSH tunnel"""
    ssh = ssh_connect(ip, username, string_private_key=key)

    # Test 1: Basic connection
    stdout = ssh_exec_command(ssh, "echo test", return_type="stdout")
    assert "test" in stdout.read().decode()

    # Test 2: List files
    stdout = ssh_exec_command(ssh, "dir", return_type="stdout")
    assert len(stdout.read()) > 0

    # Test 3: Check UiPath
    stdout = ssh_exec_command(ssh,
        "schtasks /query /tn RPA_Test",
        return_type="stdout")
    assert "RPA_Test" in stdout.read().decode('cp949')

    ssh.close()
    print(f"✓ All RPA tests passed for {customer_code}")

if __name__ == "__main__":
    test_rpa_execution("c78bbf00", "10.0.0.1", "Administrator", "...")
```

#### Test Case 5: DB 터널 테스트

```python
# test_db_via_tunnel.py

import pymssql

def test_db_connection(customer_code, db_host, db_port, db_user, db_pass):
    """Test DB connection over SSH tunnel"""
    try:
        conn = pymssql.connect(
            server=f"{db_host}:{db_port}",
            user=db_user,
            password=db_pass,
            database="master",
            timeout=10
        )
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        version = cursor.fetchone()[0]
        conn.close()

        print(f"✓ DB connection successful for {customer_code}")
        print(f"  Version: {version[:50]}...")
        return True
    except Exception as e:
        print(f"✗ DB connection failed: {e}")
        return False

if __name__ == "__main__":
    test_db_connection("c78bbf00", "stn.hyperlounge.dev", 50001, "sa", "...")
```

### 6.3 부하 테스트

#### Test Case 6: 장시간 연결 안정성

```bash
#!/bin/bash
# test_long_connection.sh

CUSTOMER_CODE=$1
DURATION_HOURS=${2:-24}

echo "=== Starting ${DURATION_HOURS}h stability test for ${CUSTOMER_CODE} ==="

END_TIME=$(($(date +%s) + ${DURATION_HOURS} * 3600))

while [ $(date +%s) -lt ${END_TIME} ]; do
    # Check every 5 minutes
    if pgrep -f "autossh.*${CUSTOMER_CODE}" > /dev/null; then
        echo "[$(date)] ✓ Tunnel is up"
    else
        echo "[$(date)] ✗ Tunnel is DOWN!"
    fi

    sleep 300
done

echo "=== Test completed ==="
```

### 6.4 성능 테스트

#### Test Case 7: 처리량 테스트

```python
# test_throughput.py

import time
from collector.common.util import ssh_connect, ssh_exec_command

def test_command_throughput(customer_code, ip, username, key, iterations=100):
    """Test command execution throughput"""
    ssh = ssh_connect(ip, username, string_private_key=key)

    start_time = time.time()

    for i in range(iterations):
        ssh_exec_command(ssh, "echo test", return_type="stdout")
        if (i + 1) % 10 == 0:
            print(f"Completed {i + 1}/{iterations} commands")

    end_time = time.time()
    duration = end_time - start_time
    throughput = iterations / duration

    ssh.close()

    print(f"\n=== Throughput Test Results ===")
    print(f"Total commands: {iterations}")
    print(f"Total time: {duration:.2f}s")
    print(f"Throughput: {throughput:.2f} commands/sec")

    return throughput

if __name__ == "__main__":
    test_command_throughput("c78bbf00", "10.0.0.1", "Administrator", "...")
```

---

## 7. 롤백 계획

### 7.1 롤백 시나리오

| 시나리오 | 증상 | 롤백 방법 |
|----------|------|-----------|
| **autossh 연결 불가** | 터널이 전혀 생성되지 않음 | 기존 create_tunnel.sh로 복구 |
| **잦은 재연결** | 30초마다 재연결 반복 | autossh 설정 조정 또는 롤백 |
| **RPA 실행 실패** | SSH 명령 실행 안됨 | Paramiko 설정 원복 |
| **성능 저하** | 응답 시간 2배 이상 증가 | 즉시 롤백 |

### 7.2 롤백 스크립트

```bash
#!/bin/bash
# rollback_to_v1.sh

CUSTOMER_CODE=$1

echo "=== Rolling back SSH tunnel to v1 (OpenSSH) ==="

# Stop autossh
echo "Stopping autossh..."
pkill -f "autossh.*${CUSTOMER_CODE}"

# Stop systemd service if exists
if systemctl list-units --full --all | grep -q "ssh-tunnel-${CUSTOMER_CODE}"; then
    echo "Stopping systemd service..."
    systemctl stop ssh-tunnel-${CUSTOMER_CODE}
    systemctl disable ssh-tunnel-${CUSTOMER_CODE}
fi

# Start v1 tunnel
echo "Starting v1 tunnel..."
/path/to/vpc-client/create_tunnel.sh \
    --ssh-server stn.hyperlounge.dev \
    --private-addr {DB_ADDR} \
    --private-port {DB_PORT} \
    --user-id ${CUSTOMER_CODE} \
    --key-file /home/${CUSTOMER_CODE}/.ssh/id_rsa \
    {REMOTE_PORT}

# Verify
sleep 3
ps aux | grep ssh | grep ${CUSTOMER_CODE}

echo "=== Rollback completed ==="
```

### 7.3 롤백 체크리스트

**즉시 롤백 조건** (15분 내 결정):
- [ ] 터널 연결 3회 이상 실패
- [ ] RPA 작업 실패율 50% 이상
- [ ] DB 쿼리 타임아웃 발생
- [ ] 고객사 업무 중단

**롤백 실행 순서**:
1. [ ] 고객사 담당자에게 통보
2. [ ] autossh 프로세스/서비스 중지
3. [ ] 기존 OpenSSH 터널 재시작
4. [ ] 연결 테스트 (DB, RPA)
5. [ ] 고객사에 복구 완료 통보
6. [ ] 사후 분석 회의 소집

### 7.4 백업 및 복구

**배포 전 백업**:
```bash
#!/bin/bash
# backup_before_deploy.sh

CUSTOMER_CODE=$1
BACKUP_DIR="/backup/ssh_v2_migration/$(date +%Y%m%d_%H%M%S)"

mkdir -p ${BACKUP_DIR}

# Backup scripts
cp /path/to/vpc-client/create_tunnel.sh ${BACKUP_DIR}/
cp /path/to/collector/common/util.py ${BACKUP_DIR}/

# Backup logs
cp /var/log/ssh-tunnel-*.log ${BACKUP_DIR}/ 2>/dev/null

# Backup crontab
crontab -l > ${BACKUP_DIR}/crontab_backup.txt

echo "Backup completed: ${BACKUP_DIR}"
```

---

## 8. 문서 및 교육

### 8.1 운영 매뉴얼

**파일**: `SSH_V2_OPERATION_MANUAL.md`

내용:
- autossh 명령어 사용법
- systemd 서비스 관리
- 로그 확인 방법
- 트러블슈팅 가이드

### 8.2 트러블슈팅 가이드

| 문제 | 원인 | 해결 방법 |
|------|------|-----------|
| autossh 프로세스 없음 | 크래시 또는 수동 종료 | `systemctl restart ssh-tunnel-{code}` |
| 포트가 gateway에 없음 | 방화벽 또는 네트워크 문제 | 방화벽 규칙 확인, SSH 서버 로그 확인 |
| 인증 실패 | 키 파일 문제 | `~/.ssh/authorized_keys` 확인 |
| 잦은 재연결 | 네트워크 불안정 | ServerAliveInterval 증가 (60초) |

### 8.3 교육 자료

**대상**: 플랫폼팀, 인프라팀

**교육 내용**:
1. SSH v2 아키텍처 개요
2. autossh vs OpenSSH 비교
3. systemd 서비스 관리
4. 로그 분석 및 모니터링
5. 장애 대응 시나리오

---

## 9. 성공 지표 (KPI)

| 지표 | 현재 (v1) | 목표 (v2) | 측정 방법 |
|------|-----------|-----------|-----------|
| **터널 다운타임** | 5-10분/일 | < 1분/일 | 모니터링 로그 분석 |
| **재연결 시간** | 5-10분 (crontab 주기) | < 90초 (3회 재시도) | autossh 로그 |
| **RPA 성공률** | 95% | > 98% | Airflow DAG 로그 |
| **SSH 명령 실패율** | 5% | < 2% | Python 로그 분석 |
| **장애 알림 시간** | 10-30분 | < 5분 | 모니터링 시스템 |

---

## 10. 일정 및 리소스

### 10.1 전체 일정

| Phase | 기간 | 담당자 | 비고 |
|-------|------|--------|------|
| **Phase 1: 준비** | 2일 | 인프라팀 | 스크립트 개발, 테스트 환경 구축 |
| **Phase 2: Pilot** | 1주 | 인프라팀 + 플랫폼팀 | 매일홀딩스 적용 |
| **Phase 3: 검증** | 1주 | 플랫폼팀 | 안정성 모니터링 |
| **Phase 4: 확장** | 2주 | 인프라팀 | 한국카본, GC녹십자 |
| **Phase 5: 전사 적용** | 2주 | 인프라팀 | 나머지 고객사 |
| **총 기간** | **6주** | | |

### 10.2 리소스

| 역할 | 인원 | 투입 시간 |
|------|------|-----------|
| **인프라 엔지니어** | 1명 | 30% (6주) |
| **플랫폼 엔지니어** | 1명 | 20% (6주) |
| **QA** | 1명 | 10% (2주) |

---

## 11. 리스크 관리

| 리스크 | 확률 | 영향도 | 완화 전략 |
|--------|------|--------|-----------|
| autossh 설치 실패 | Low | Medium | 수동 설치 가이드 준비 |
| 고객사 방화벽 차단 | Low | High | 사전 테스트, 고객사 협의 |
| 성능 저하 | Low | High | 부하 테스트, 즉시 롤백 |
| 기존 스크립트 호환성 | Medium | Medium | 충분한 테스트, 단계적 배포 |
| 팀원 역량 부족 | Low | Low | 사전 교육, 문서화 |

---

## 12. 체크포인트

### Pilot 완료 후 체크포인트 (1주 후)

- [ ] 터널 안정성: 다운타임 < 5분/주
- [ ] RPA 성공률: > 95%
- [ ] 고객사 피드백: 부정적 의견 없음
- [ ] 로그 분석: 심각한 에러 없음

**Go/No-Go 결정**:
- **Go**: 위 4개 조건 모두 만족 → Phase 4 진행
- **No-Go**: 1개 이상 미달 → 문제 해결 후 재검증

---

## 부록

### A. 참조 문서

- [autossh 공식 문서](https://www.harding.motd.ca/autossh/)
- [systemd 서비스 가이드](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [Paramiko 문서](https://docs.paramiko.org/)
- [SSH 터널링 Best Practices](https://www.ssh.com/academy/ssh/tunneling)

### B. 관련 파일 경로

| 파일 | 경로 |
|------|------|
| 기존 터널 스크립트 | `vpc-client/create_tunnel.sh` |
| SSH 연결 함수 | `collector/common/util.py` |
| VM 관리 | `collector/cloud_instance/instance_manager.py` |
| SSH 모니터링 | `rpa_agent/main.py` |
| 고객사 DAG | `airflow-dags/dags/c78bbf00.py` |

### C. 담당자 연락처

| 역할 | 담당자 | 이메일 | 전화 |
|------|--------|--------|------|
| 프로젝트 리드 | [이름] | [email] | [번호] |
| 인프라 엔지니어 | [이름] | [email] | [번호] |
| 플랫폼 엔지니어 | [이름] | [email] | [번호] |
| QA 엔지니어 | [이름] | [email] | [번호] |

---

**문서 버전**: 1.0
**최종 수정일**: 2025-01-20
**작성자**: Platform Team
**검토자**: [검토자 이름]
**승인자**: [승인자 이름]
