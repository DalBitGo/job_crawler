#!/usr/bin/env python3
"""
채용공고 상세 크롤러 - 사람인, 원티드에서 상세 공고 내용까지 수집
자격요건, 우대사항, 기술스택, 연봉 정보 등 포함
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import json
from collections import Counter
from datetime import datetime
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
warnings.filterwarnings('ignore')

# 기술스택 키워드 정의 (더 상세하게)
TECH_KEYWORDS = {
    # 언어
    'Python': ['python', '파이썬'],
    'Java': ['java', '자바'],
    'Kotlin': ['kotlin', '코틀린'],
    'Go': ['golang', 'go언어', 'go '],
    'Scala': ['scala', '스칼라'],
    'TypeScript': ['typescript', 'ts'],
    'JavaScript': ['javascript', 'js', 'node.js', 'nodejs'],
    'SQL': ['sql'],
    'C++': ['c++', 'cpp'],
    'Rust': ['rust', '러스트'],
    'Ruby': ['ruby', '루비'],
    'PHP': ['php'],

    # 백엔드 프레임워크
    'Spring': ['spring', 'spring boot', 'springboot', '스프링'],
    'Spring Boot': ['spring boot', 'springboot', '스프링부트', '스프링 부트'],
    'Django': ['django', '장고'],
    'FastAPI': ['fastapi', 'fast api'],
    'Flask': ['flask', '플라스크'],
    'Express': ['express', 'express.js'],
    'NestJS': ['nestjs', 'nest.js'],
    'JPA': ['jpa', 'hibernate', '하이버네이트'],
    'MyBatis': ['mybatis', '마이바티스'],

    # 데이터 처리
    'Spark': ['spark', 'pyspark', '스파크', 'apache spark'],
    'Hadoop': ['hadoop', '하둡'],
    'Airflow': ['airflow', 'apache airflow', '에어플로우'],
    'Kafka': ['kafka', '카프카', 'apache kafka'],
    'Flink': ['flink', '플링크'],
    'Presto': ['presto', 'trino'],
    'Hive': ['hive', '하이브'],
    'dbt': ['dbt', 'data build tool'],
    'ETL': ['etl', 'elt'],
    'Data Pipeline': ['data pipeline', '데이터 파이프라인'],

    # 데이터베이스
    'MySQL': ['mysql', 'mariadb'],
    'PostgreSQL': ['postgresql', 'postgres', 'psql'],
    'Oracle': ['oracle', '오라클'],
    'MongoDB': ['mongodb', '몽고db', '몽고디비'],
    'Redis': ['redis', '레디스'],
    'Elasticsearch': ['elasticsearch', 'elastic search', 'elk'],
    'DynamoDB': ['dynamodb'],
    'Redshift': ['redshift', '레드시프트'],
    'BigQuery': ['bigquery', '빅쿼리'],
    'Snowflake': ['snowflake', '스노우플레이크'],
    'Cassandra': ['cassandra', '카산드라'],
    'ClickHouse': ['clickhouse', '클릭하우스'],

    # 클라우드
    'AWS': ['aws', 'amazon web services', 'ec2', 's3', 'lambda', 'ecs', 'eks', 'rds', 'emr', 'athena', 'glue'],
    'GCP': ['gcp', 'google cloud', 'gce', 'bigquery', 'dataflow'],
    'Azure': ['azure', '애저', 'microsoft azure'],
    'NCP': ['ncp', 'naver cloud', '네이버 클라우드'],

    # 컨테이너/오케스트레이션
    'Docker': ['docker', '도커'],
    'Kubernetes': ['kubernetes', 'k8s', '쿠버네티스'],
    'ECS': ['ecs', 'fargate'],
    'EKS': ['eks'],

    # CI/CD & DevOps
    'Jenkins': ['jenkins', '젠킨스'],
    'GitHub Actions': ['github actions', 'github action'],
    'GitLab CI': ['gitlab ci', 'gitlab-ci'],
    'ArgoCD': ['argocd', 'argo cd', 'argo'],
    'Terraform': ['terraform', '테라폼'],
    'Ansible': ['ansible', '앤서블'],
    'Helm': ['helm', '헬름'],

    # 모니터링/로깅
    'Prometheus': ['prometheus', '프로메테우스'],
    'Grafana': ['grafana', '그라파나'],
    'Datadog': ['datadog', '데이터독'],
    'ELK Stack': ['elk', 'logstash', 'kibana'],

    # 기타
    'Linux': ['linux', '리눅스', 'ubuntu', 'centos'],
    'Git': ['git', '깃', 'github', 'gitlab'],
    'REST API': ['rest api', 'restful', 'rest'],
    'GraphQL': ['graphql', '그래프큐엘'],
    'gRPC': ['grpc'],
    'MSA': ['msa', 'microservice', '마이크로서비스'],
    'Message Queue': ['message queue', 'mq', 'rabbitmq', 'sqs'],
    'CI/CD': ['ci/cd', 'cicd', 'ci cd', '지속적 통합'],
    'Agile': ['agile', '애자일', 'scrum', '스크럼'],
    'TDD': ['tdd', 'test driven', '테스트 주도'],
}

# 자격요건 관련 키워드
QUALIFICATION_PATTERNS = {
    'experience': [
        r'(\d+)\s*년\s*이상',
        r'경력\s*(\d+)\s*년',
        r'(\d+)\s*~\s*(\d+)\s*년',
        r'(\d+)년차',
    ],
    'education': [
        r'(대졸|학사|석사|박사|초대졸|고졸)',
        r'(컴퓨터|전산|정보|소프트웨어|IT)\s*(공학|과학|학과)',
    ],
}


class DetailedJobCrawler:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def crawl_saramin_list(self, keyword: str, pages: int = 5) -> List[Dict]:
        """사람인 채용공고 목록 크롤링"""
        print(f"\n[사람인] '{keyword}' 목록 수집 중...")
        jobs = []

        for page in range(1, pages + 1):
            url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchType=search&searchword={keyword}&recruitPage={page}"

            try:
                response = self.session.get(url, timeout=10)
                if response.status_code != 200:
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                job_items = soup.select('.item_recruit')

                for item in job_items:
                    try:
                        title_elem = item.select_one('.job_tit a')
                        company_elem = item.select_one('.corp_name a')
                        conditions = item.select('.job_condition span')

                        if not title_elem:
                            continue

                        href = title_elem.get('href', '')
                        # rec_idx 추출
                        rec_idx_match = re.search(r'rec_idx=(\d+)', href)
                        if not rec_idx_match:
                            continue

                        job = {
                            'source': '사람인',
                            'title': title_elem.get_text(strip=True),
                            'company': company_elem.get_text(strip=True) if company_elem else '',
                            'rec_idx': rec_idx_match.group(1),
                            'link': f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={rec_idx_match.group(1)}",
                            'conditions': [c.get_text(strip=True) for c in conditions],
                        }
                        jobs.append(job)
                    except Exception:
                        continue

                print(f"  페이지 {page}: {len(job_items)}개")
                time.sleep(0.5)

            except Exception as e:
                print(f"  페이지 {page}: 오류 - {e}")
                continue

        print(f"[사람인] 목록 {len(jobs)}개 수집 완료")
        return jobs

    def get_saramin_detail(self, job: Dict) -> Dict:
        """사람인 상세 공고 크롤링"""
        try:
            url = job['link']
            response = self.session.get(url, timeout=10)
            if response.status_code != 200:
                return job

            soup = BeautifulSoup(response.text, 'html.parser')

            # 상세 정보 추출
            detail = {
                'qualifications': '',      # 자격요건
                'preferred': '',           # 우대사항
                'responsibilities': '',    # 담당업무
                'benefits': '',            # 복리후생
                'salary': '',              # 연봉
                'detail_tech_stack': [],   # 상세 기술스택
                'experience_years': '',    # 경력 연차
                'education': '',           # 학력
                'full_description': '',    # 전체 설명
            }

            # 채용 상세 섹션 찾기
            detail_sections = soup.select('.jv_cont')

            for section in detail_sections:
                header = section.select_one('.jv_header, .tit_cont')
                content = section.select_one('.jv_detail, .cont')

                if not header or not content:
                    continue

                header_text = header.get_text(strip=True)
                content_text = content.get_text('\n', strip=True)

                if any(k in header_text for k in ['자격요건', '자격 요건', '필수', '지원자격']):
                    detail['qualifications'] = content_text
                elif any(k in header_text for k in ['우대', '선호', '가산점']):
                    detail['preferred'] = content_text
                elif any(k in header_text for k in ['담당업무', '업무내용', '주요업무', '담당 업무']):
                    detail['responsibilities'] = content_text
                elif any(k in header_text for k in ['복리후생', '혜택', '복지']):
                    detail['benefits'] = content_text

            # 연봉 정보
            salary_elem = soup.select_one('.salary')
            if salary_elem:
                detail['salary'] = salary_elem.get_text(strip=True)

            # 경력/학력 정보
            career_elem = soup.select_one('.career')
            if career_elem:
                detail['experience_years'] = career_elem.get_text(strip=True)

            edu_elem = soup.select_one('.education')
            if edu_elem:
                detail['education'] = edu_elem.get_text(strip=True)

            # 전체 설명 (기술스택 추출용)
            job_detail = soup.select_one('.jv_detail, .job_detail, .wrap_jv_cont')
            if job_detail:
                detail['full_description'] = job_detail.get_text('\n', strip=True)

            # 기술스택 추출
            full_text = f"{detail['qualifications']} {detail['preferred']} {detail['responsibilities']} {detail['full_description']}"
            detail['detail_tech_stack'] = self.extract_tech_stack(full_text)

            job.update(detail)
            return job

        except Exception as e:
            job['error'] = str(e)
            return job

    def crawl_wanted_list(self, keyword: str, limit: int = 50) -> List[Dict]:
        """원티드 채용공고 목록 크롤링"""
        print(f"\n[원티드] '{keyword}' 목록 수집 중...")
        jobs = []

        url = f"https://www.wanted.co.kr/api/v4/jobs?country=kr&job_sort=company.response_rate_order&years=-1&locations=all&query={keyword}&limit={limit}"

        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for item in data.get('data', []):
                    job = {
                        'source': '원티드',
                        'title': item.get('position', ''),
                        'company': item.get('company', {}).get('name', ''),
                        'job_id': item.get('id', ''),
                        'link': f"https://www.wanted.co.kr/wd/{item.get('id', '')}",
                        'conditions': [],
                    }
                    jobs.append(job)
                print(f"[원티드] 목록 {len(jobs)}개 수집 완료")
        except Exception as e:
            print(f"[원티드] 오류: {e}")

        return jobs

    def get_wanted_detail(self, job: Dict) -> Dict:
        """원티드 상세 공고 크롤링 (API)"""
        try:
            job_id = job.get('job_id', '')
            if not job_id:
                return job

            url = f"https://www.wanted.co.kr/api/v4/jobs/{job_id}"
            response = self.session.get(url, timeout=10)

            if response.status_code != 200:
                return job

            data = response.json()
            job_data = data.get('job', {})

            detail = {
                'qualifications': job_data.get('requirements', ''),
                'preferred': job_data.get('preferred', ''),
                'responsibilities': job_data.get('responsibilities', ''),
                'benefits': job_data.get('benefits', ''),
                'salary': '',
                'detail_tech_stack': [],
                'experience_years': '',
                'education': '',
                'full_description': job_data.get('detail', ''),
            }

            # 기술 태그
            skill_tags = job_data.get('skill_tags', [])
            if skill_tags:
                detail['detail_tech_stack'] = [tag.get('title', '') for tag in skill_tags]

            # 추가 기술스택 추출
            full_text = f"{detail['qualifications']} {detail['preferred']} {detail['responsibilities']} {detail['full_description']}"
            extracted_techs = self.extract_tech_stack(full_text)
            detail['detail_tech_stack'] = list(set(detail['detail_tech_stack'] + extracted_techs))

            job.update(detail)
            return job

        except Exception as e:
            job['error'] = str(e)
            return job

    def extract_tech_stack(self, text: str) -> List[str]:
        """텍스트에서 기술스택 추출"""
        found_techs = []
        text_lower = text.lower()

        for tech, keywords in TECH_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text_lower:
                    found_techs.append(tech)
                    break

        return list(set(found_techs))

    def extract_experience(self, text: str) -> str:
        """경력 연차 추출"""
        for pattern in QUALIFICATION_PATTERNS['experience']:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return ''

    def crawl_with_details(self, keywords: List[str], saramin_pages: int = 3, wanted_limit: int = 30) -> List[Dict]:
        """목록 + 상세 정보 크롤링"""
        all_jobs = []

        for keyword in keywords:
            # 사람인
            saramin_jobs = self.crawl_saramin_list(keyword, pages=saramin_pages)
            print(f"[사람인] '{keyword}' 상세 정보 수집 중... ({len(saramin_jobs)}개)")

            for i, job in enumerate(saramin_jobs):
                self.get_saramin_detail(job)
                if (i + 1) % 10 == 0:
                    print(f"  {i+1}/{len(saramin_jobs)} 완료")
                time.sleep(0.3)  # 요청 간격

            all_jobs.extend(saramin_jobs)

            # 원티드
            wanted_jobs = self.crawl_wanted_list(keyword, limit=wanted_limit)
            print(f"[원티드] '{keyword}' 상세 정보 수집 중... ({len(wanted_jobs)}개)")

            for i, job in enumerate(wanted_jobs):
                self.get_wanted_detail(job)
                if (i + 1) % 10 == 0:
                    print(f"  {i+1}/{len(wanted_jobs)} 완료")
                time.sleep(0.3)

            all_jobs.extend(wanted_jobs)
            time.sleep(1)

        return all_jobs

    def analyze_detailed_jobs(self, jobs: List[Dict]) -> Dict:
        """상세 공고 분석"""
        print("\n" + "="*70)
        print("📊 상세 채용공고 분석 결과")
        print("="*70)

        # 기술스택 빈도 분석 (상세 정보 기반)
        all_techs = []
        for job in jobs:
            techs = job.get('detail_tech_stack', [])
            all_techs.extend(techs)

        tech_counter = Counter(all_techs)

        # 자격요건 키워드 분석
        qual_keywords = []
        for job in jobs:
            qual_text = f"{job.get('qualifications', '')} {job.get('preferred', '')}"
            qual_keywords.extend(self.extract_tech_stack(qual_text))

        qual_counter = Counter(qual_keywords)

        # 경력 분석
        experience_list = []
        for job in jobs:
            exp = job.get('experience_years', '')
            if exp:
                experience_list.append(exp)

        # 결과 정리
        result = {
            'total_jobs': len(jobs),
            'jobs_with_details': len([j for j in jobs if j.get('qualifications') or j.get('full_description')]),
            'by_source': dict(Counter(job['source'] for job in jobs)),
            'tech_frequency': dict(tech_counter.most_common(40)),
            'qualification_tech_frequency': dict(qual_counter.most_common(30)),
            'top_companies': Counter(job['company'] for job in jobs if job['company']).most_common(20),
            'experience_distribution': Counter(experience_list).most_common(10),
        }

        # 출력
        print(f"\n📌 총 수집 공고: {result['total_jobs']}개")
        print(f"   상세정보 수집 성공: {result['jobs_with_details']}개")

        print(f"\n📍 출처별:")
        for source, count in result['by_source'].items():
            print(f"   - {source}: {count}개")

        print(f"\n🔧 기술스택 Top 25 (상세 공고 기반):")
        for i, (tech, count) in enumerate(tech_counter.most_common(25), 1):
            percentage = (count / len(jobs)) * 100
            bar = '█' * int(percentage / 2)
            print(f"  {i:2}. {tech:18} | {bar:25} {count:3}개 ({percentage:.1f}%)")

        print(f"\n📋 자격요건에서 많이 언급된 기술 Top 15:")
        for i, (tech, count) in enumerate(qual_counter.most_common(15), 1):
            percentage = (count / len(jobs)) * 100
            print(f"  {i:2}. {tech:18} - {count:3}개 ({percentage:.1f}%)")

        print(f"\n🏢 채용 활발한 회사 Top 10:")
        for company, count in result['top_companies'][:10]:
            print(f"   - {company}: {count}개")

        if result['experience_distribution']:
            print(f"\n📅 경력 요구사항:")
            for exp, count in result['experience_distribution']:
                print(f"   - {exp}: {count}개")

        return result

    def save_detailed_results(self, jobs: List[Dict], result: Dict, output_dir: str = '.'):
        """상세 결과 저장"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # CSV 저장 (상세 정보 포함)
        df_data = []
        for job in jobs:
            df_data.append({
                'source': job.get('source', ''),
                'company': job.get('company', ''),
                'title': job.get('title', ''),
                'link': job.get('link', ''),
                'experience_years': job.get('experience_years', ''),
                'education': job.get('education', ''),
                'salary': job.get('salary', ''),
                'tech_stack': ', '.join(job.get('detail_tech_stack', [])),
                'qualifications': job.get('qualifications', '')[:500],  # 500자 제한
                'preferred': job.get('preferred', '')[:500],
                'responsibilities': job.get('responsibilities', '')[:500],
                'benefits': job.get('benefits', '')[:300],
            })

        df = pd.DataFrame(df_data)
        csv_path = f"{output_dir}/jobs_detailed_{timestamp}.csv"
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\n📁 상세 CSV 저장: {csv_path}")

        # JSON 저장 (전체 데이터)
        json_path = f"{output_dir}/jobs_full_{timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
        print(f"📁 전체 JSON 저장: {json_path}")

        # 분석 결과 JSON
        analysis_path = f"{output_dir}/analysis_detailed_{timestamp}.json"
        with open(analysis_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"📁 분석 결과 저장: {analysis_path}")

        # 상세 마크다운 리포트
        md_path = f"{output_dir}/report_detailed_{timestamp}.md"
        self._generate_detailed_report(result, jobs, md_path)
        print(f"📁 상세 리포트 저장: {md_path}")

        return timestamp

    def _generate_detailed_report(self, result: Dict, jobs: List[Dict], path: str):
        """상세 마크다운 리포트 생성"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"# 채용공고 상세 분석 리포트\n\n")
            f.write(f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write(f"## 개요\n\n")
            f.write(f"- **총 분석 공고**: {result['total_jobs']}개\n")
            f.write(f"- **상세정보 수집 성공**: {result['jobs_with_details']}개\n")
            for source, count in result['by_source'].items():
                f.write(f"- {source}: {count}개\n")

            f.write(f"\n## 기술스택 분석 (상세 공고 기반)\n\n")
            f.write(f"| 순위 | 기술 | 등장 횟수 | 비율 |\n")
            f.write(f"|------|------|----------|------|\n")
            for i, (tech, count) in enumerate(result['tech_frequency'].items(), 1):
                if i > 30:
                    break
                percentage = (count / result['total_jobs']) * 100
                f.write(f"| {i} | {tech} | {count} | {percentage:.1f}% |\n")

            f.write(f"\n## 자격요건 필수 기술\n\n")
            f.write(f"| 순위 | 기술 | 등장 횟수 | 비율 |\n")
            f.write(f"|------|------|----------|------|\n")
            for i, (tech, count) in enumerate(result['qualification_tech_frequency'].items(), 1):
                if i > 20:
                    break
                percentage = (count / result['total_jobs']) * 100
                f.write(f"| {i} | {tech} | {count} | {percentage:.1f}% |\n")

            f.write(f"\n## 채용 활발한 회사\n\n")
            for company, count in result['top_companies'][:15]:
                f.write(f"- **{company}**: {count}개\n")

            f.write(f"\n## 주요 자격요건 샘플\n\n")
            sample_jobs = [j for j in jobs if j.get('qualifications')][:5]
            for job in sample_jobs:
                f.write(f"### {job.get('company', '')} - {job.get('title', '')[:50]}\n\n")
                f.write(f"**기술스택**: {', '.join(job.get('detail_tech_stack', []))}\n\n")
                qual = job.get('qualifications', '')[:800]
                if qual:
                    f.write(f"**자격요건**:\n```\n{qual}\n```\n\n")
                pref = job.get('preferred', '')[:500]
                if pref:
                    f.write(f"**우대사항**:\n```\n{pref}\n```\n\n")
                f.write(f"---\n\n")


def main():
    crawler = DetailedJobCrawler()

    keywords = ['데이터 엔지니어', '백엔드 개발자', 'backend developer', 'data engineer']

    print("="*70)
    print("🔍 채용공고 상세 크롤링 시작")
    print("   (각 공고의 상세 페이지를 방문하여 자격요건/우대사항 등 수집)")
    print("="*70)

    # 상세 크롤링 (시간이 좀 걸림)
    jobs = crawler.crawl_with_details(
        keywords=keywords,
        saramin_pages=3,  # 사람인 페이지 수
        wanted_limit=30   # 원티드 공고 수
    )

    # 중복 제거
    seen = set()
    unique_jobs = []
    for job in jobs:
        key = (job.get('company', ''), job.get('title', ''))
        if key not in seen and key[0]:
            seen.add(key)
            unique_jobs.append(job)

    print(f"\n중복 제거 후: {len(unique_jobs)}개 (원본: {len(jobs)}개)")

    # 분석
    result = crawler.analyze_detailed_jobs(unique_jobs)

    # 저장
    timestamp = crawler.save_detailed_results(
        unique_jobs,
        result,
        output_dir='/home/junhyun/job_crawler/employment'
    )

    print("\n" + "="*70)
    print("✅ 상세 크롤링 및 분석 완료!")
    print("="*70)


if __name__ == '__main__':
    main()
