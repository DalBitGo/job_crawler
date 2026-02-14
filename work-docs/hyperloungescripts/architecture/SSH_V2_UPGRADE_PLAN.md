# SSH v2 업그레이드 계획

## 개요

SSH 터널링 안정성 강화를 위한 autossh 도입

## 변경 사항

| 구분 | 기존 | 신규 |
|------|------|------|
| **터널링** | OpenSSH (`ssh -R`) | autossh + OpenSSH |
| **재연결** | crontab 주기적 체크 | 즉시 자동 재연결 |
| **Python 명령 실행** | Paramiko | Paramiko (유지) |

## 적용 대상 고객사

- 매일홀딩스 (c78bbf00)
- 한국카본 (c3a40f00)
- GC녹십자 (c1d66200)

## 코드 변경

### 기존 (create_tunnel.sh)

```bash
ssh -f -N -i $key_file -R $remote_port:$private_addr:$private_port $user_id@$ssh_server
```

### 신규 (autossh 적용)

```bash
autossh -M 0 -f -N -i $key_file \
  -R $remote_port:$private_addr:$private_port \
  $user_id@$ssh_server \
  -o "ServerAliveInterval=30" \
  -o "ServerAliveCountMax=3"
```

## autossh 옵션 설명

| 옵션 | 설명 |
|------|------|
| `-M 0` | 모니터링 포트 비활성화 (ServerAlive 사용) |
| `ServerAliveInterval=30` | 30초마다 keepalive 체크 |
| `ServerAliveCountMax=3` | 3회 실패 시 자동 재연결 |

## 설치

```bash
# Ubuntu/Debian
apt install autossh

# CentOS/RHEL
yum install autossh
```

## 비용

- **무료** (BSD 라이선스, 상업적 사용 가능)
