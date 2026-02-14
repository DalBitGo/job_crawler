# [Tech] SendGrid Inbound Parse 용량 제한 문제 (30MB)

**작성일**: 2025-12-19
**카테고리**: Tech
**상태**: 검토 중

---

## 증상

- 고객사에서 35MB 이상 첨부파일이 포함된 이메일 발송 시 수집 실패
- SendGrid Inbound Parse의 최대 용량 제한: **30MB** (메시지 + 첨부파일 합계)
- 현재 일부 고객사에서 30MB 초과 파일 전송 케이스 발생 중

---

## 현재 구조

```
[외부 이메일] → [SendGrid] → [Cloud Run: inbound-mail-parser] → [GCS 업로드]
```

- **서비스 URL**: `inbound-mail-parser-l27zak4z4q-du.a.run.app`
- **수신 주소**: `crawler-{customer_code}@agent.hyperlounge.ai`
- **소스 코드**: `C:\Users\박준현\Desktop\email-collector`

---

## 제한 사항

| 항목 | 값 |
|------|-----|
| SendGrid 최대 제한 | 30MB |
| SendGrid 권장 크기 | 10~20MB |
| 실제 수신 필요 크기 | 35MB+ |

**참고 문서**:
- [Inbound Email Parse Webhook | SendGrid Docs](https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/inbound-email)
- [SendGrid Inbound Parse Size Limit Issue #6304](https://github.com/sendgrid/docs/issues/6304)

---

## 대안 검토

| 방안 | 설명 | 장점 | 단점 |
|------|------|------|------|
| **Google Workspace API** | Gmail API로 메일함 직접 접근 | 용량 제한 없음 | 구현 복잡, 인증 필요 |
| **Microsoft Graph API** | Outlook/365 메일함 접근 | 용량 제한 없음 | 구현 복잡 |
| **IMAP 직접 수집** | 메일서버 폴링 방식 | 150MB까지 가능 | 실시간성 낮음 |
| **파일 분할 요청** | 고객에게 분할 전송 안내 | 구현 불필요 | 운영 부담 |
| **별도 채널 (SFTP/GDrive)** | 대용량 고객사만 분리 | 확실한 해결 | 고객사 협조 필요 |

---

## 조치 계획

1. **영향 범위 파악**: 30MB 초과 파일 발송 고객사 목록 확인
2. **대안 선정**: 고객사 수, 빈도에 따라 적합한 방안 결정
3. **구현/적용**: 선정된 방안 개발 및 배포

---

## 비고

- SendGrid 자체 제한이므로 설정 변경으로 해결 불가
- 대용량 파일 발생 빈도 및 고객사 파악 후 결정 필요

---

## 예상 완료 일정

**2025-12-27** (조사 및 방안 결정)
