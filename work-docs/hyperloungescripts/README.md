# Documentation

## Structure

```
docs/
├── architecture/    # 시스템 설계 및 아키텍처 문서
├── guides/          # 사용 가이드 및 마이그레이션 문서
├── issues/          # 이슈 해결 및 인시던트 리포트
└── monitoring/      # 모니터링 시스템 관련 문서
```

## Folder Descriptions

### architecture/
시스템 설계, 아키텍처 결정, 기술 스펙 문서
- Cloud Run Job 아키텍처
- SSH V2 설계

### guides/
개발/운영 가이드, 마이그레이션 절차
- Airflow Backfill 가이드
- LLM Convert 사용법

### issues/
이슈 해결 과정, 인시던트 리포트, 트러블슈팅
- HAI Renamer 중복 문제 해결
- TCP Timeout 이슈

### monitoring/
모니터링 시스템 설정, 알림 관련 문서
- Converter 실패 모니터링
- 모니터링 Quick Reference

## Recent Updates

| 날짜 | 문서 | 내용 |
|------|------|------|
| 2026-01-22 | HAI_RENAMER_HISTORY_DUPLICATE_FIX.md | HAI renamer history 중복 문제 해결 |
