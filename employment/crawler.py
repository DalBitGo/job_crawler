#!/usr/bin/env python3
"""
채용공고 크롤러 - 사람인, 잡코리아, 원티드에서 데이터 엔지니어/백엔드 공고 수집
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
import warnings
warnings.filterwarnings('ignore')

# 기술스택 키워드 정의
TECH_KEYWORDS = {
    # 언어
    'Python': ['python', '파이썬'],
    'Java': ['java', '자바'],
    'Kotlin': ['kotlin', '코틀린'],
    'Go': ['golang', 'go언어'],
    'Scala': ['scala', '스칼라'],
    'TypeScript': ['typescript', 'ts'],
    'JavaScript': ['javascript', 'js'],
    'SQL': ['sql'],

    # 프레임워크
    'Spring': ['spring', 'spring boot', 'springboot', '스프링'],
    'Django': ['django', '장고'],
    'FastAPI': ['fastapi'],
    'Flask': ['flask'],
    'Express': ['express', 'express.js'],
    'NestJS': ['nestjs', 'nest.js'],

    # 데이터 처리
    'Spark': ['spark', 'pyspark', '스파크'],
    'Hadoop': ['hadoop', '하둡'],
    'Airflow': ['airflow', 'apache airflow'],
    'Kafka': ['kafka', '카프카'],
    'Flink': ['flink'],
    'Presto': ['presto', 'trino'],

    # 데이터베이스
    'MySQL': ['mysql'],
    'PostgreSQL': ['postgresql', 'postgres'],
    'MongoDB': ['mongodb', '몽고db'],
    'Redis': ['redis', '레디스'],
    'Elasticsearch': ['elasticsearch', 'elastic', 'es'],
    'DynamoDB': ['dynamodb'],
    'Redshift': ['redshift'],
    'BigQuery': ['bigquery'],

    # 클라우드
    'AWS': ['aws', 'amazon web services', 'ec2', 's3', 'lambda'],
    'GCP': ['gcp', 'google cloud', 'gce'],
    'Azure': ['azure', '애저'],

    # 컨테이너/오케스트레이션
    'Docker': ['docker', '도커'],
    'Kubernetes': ['kubernetes', 'k8s', '쿠버네티스'],

    # CI/CD
    'Jenkins': ['jenkins', '젠킨스'],
    'GitHub Actions': ['github actions'],
    'ArgoCD': ['argocd', 'argo cd'],

    # 기타
    'Linux': ['linux', '리눅스'],
    'Terraform': ['terraform', '테라폼'],
    'Git': ['git', '깃'],
    'REST API': ['rest api', 'restful', 'api'],
    'GraphQL': ['graphql'],
    'gRPC': ['grpc'],
    'MSA': ['msa', 'microservice', '마이크로서비스'],
}

class JobCrawler:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        }
        self.jobs = []

    def crawl_saramin(self, keyword: str, pages: int = 5) -> List[Dict]:
        """사람인 채용공고 크롤링"""
        print(f"\n[사람인] '{keyword}' 검색 중...")
        jobs = []

        for page in range(1, pages + 1):
            url = f"https://www.saramin.co.kr/zf_user/search/recruit?searchType=search&searchword={keyword}&recruitPage={page}"

            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code != 200:
                    print(f"  페이지 {page}: 응답 오류 ({response.status_code})")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                job_items = soup.select('.item_recruit')

                for item in job_items:
                    try:
                        title_elem = item.select_one('.job_tit a')
                        company_elem = item.select_one('.corp_name a')
                        conditions = item.select('.job_condition span')
                        sector = item.select_one('.job_sector')

                        if not title_elem:
                            continue

                        job = {
                            'source': '사람인',
                            'title': title_elem.get_text(strip=True),
                            'company': company_elem.get_text(strip=True) if company_elem else '',
                            'link': 'https://www.saramin.co.kr' + title_elem.get('href', ''),
                            'conditions': [c.get_text(strip=True) for c in conditions],
                            'sector': sector.get_text(strip=True) if sector else '',
                            'raw_text': item.get_text(' ', strip=True)
                        }
                        jobs.append(job)
                    except Exception as e:
                        continue

                print(f"  페이지 {page}: {len(job_items)}개 공고 수집")
                time.sleep(1)  # 요청 간격

            except Exception as e:
                print(f"  페이지 {page}: 오류 발생 - {e}")
                continue

        print(f"[사람인] 총 {len(jobs)}개 공고 수집 완료")
        return jobs

    def crawl_jobkorea(self, keyword: str, pages: int = 5) -> List[Dict]:
        """잡코리아 채용공고 크롤링"""
        print(f"\n[잡코리아] '{keyword}' 검색 중...")
        jobs = []

        for page in range(1, pages + 1):
            url = f"https://www.jobkorea.co.kr/Search/?stext={keyword}&tabType=recruit&Page_No={page}"

            try:
                response = requests.get(url, headers=self.headers, timeout=10)
                if response.status_code != 200:
                    print(f"  페이지 {page}: 응답 오류 ({response.status_code})")
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                job_items = soup.select('.list-default .list-post')

                for item in job_items:
                    try:
                        title_elem = item.select_one('.post-list-info a.title')
                        company_elem = item.select_one('.post-list-corp a.name')
                        options = item.select('.option span')

                        if not title_elem:
                            continue

                        job = {
                            'source': '잡코리아',
                            'title': title_elem.get_text(strip=True),
                            'company': company_elem.get_text(strip=True) if company_elem else '',
                            'link': 'https://www.jobkorea.co.kr' + title_elem.get('href', ''),
                            'conditions': [o.get_text(strip=True) for o in options],
                            'sector': '',
                            'raw_text': item.get_text(' ', strip=True)
                        }
                        jobs.append(job)
                    except Exception as e:
                        continue

                print(f"  페이지 {page}: {len(job_items)}개 공고 수집")
                time.sleep(1)

            except Exception as e:
                print(f"  페이지 {page}: 오류 발생 - {e}")
                continue

        print(f"[잡코리아] 총 {len(jobs)}개 공고 수집 완료")
        return jobs

    def crawl_wanted(self, keyword: str, limit: int = 50) -> List[Dict]:
        """원티드 채용공고 크롤링 (API 방식)"""
        print(f"\n[원티드] '{keyword}' 검색 중...")
        jobs = []

        # 원티드는 API로 데이터를 가져옴
        url = f"https://www.wanted.co.kr/api/v4/jobs?country=kr&job_sort=company.response_rate_order&years=-1&locations=all&query={keyword}&limit={limit}"

        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for item in data.get('data', []):
                    job = {
                        'source': '원티드',
                        'title': item.get('position', ''),
                        'company': item.get('company', {}).get('name', ''),
                        'link': f"https://www.wanted.co.kr/wd/{item.get('id', '')}",
                        'conditions': [],
                        'sector': '',
                        'raw_text': f"{item.get('position', '')} {item.get('company', {}).get('name', '')}"
                    }
                    jobs.append(job)
                print(f"[원티드] 총 {len(jobs)}개 공고 수집 완료")
            else:
                print(f"[원티드] API 응답 오류: {response.status_code}")
        except Exception as e:
            print(f"[원티드] 오류 발생: {e}")

        return jobs

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

    def analyze_jobs(self, jobs: List[Dict]) -> Dict:
        """수집된 공고 분석"""
        print("\n" + "="*60)
        print("📊 채용공고 분석 결과")
        print("="*60)

        # 기술스택 빈도 분석
        all_techs = []
        for job in jobs:
            techs = self.extract_tech_stack(job['raw_text'])
            job['tech_stack'] = techs
            all_techs.extend(techs)

        tech_counter = Counter(all_techs)

        # 결과 정리
        result = {
            'total_jobs': len(jobs),
            'by_source': Counter(job['source'] for job in jobs),
            'tech_frequency': dict(tech_counter.most_common(30)),
            'top_companies': Counter(job['company'] for job in jobs if job['company']).most_common(20),
        }

        # 출력
        print(f"\n총 수집 공고: {result['total_jobs']}개")
        print(f"\n출처별:")
        for source, count in result['by_source'].items():
            print(f"  - {source}: {count}개")

        print(f"\n🔧 기술스택 Top 20:")
        for i, (tech, count) in enumerate(tech_counter.most_common(20), 1):
            percentage = (count / len(jobs)) * 100
            bar = '█' * int(percentage / 2)
            print(f"  {i:2}. {tech:15} | {bar:25} {count:3}개 ({percentage:.1f}%)")

        print(f"\n🏢 채용 활발한 회사 Top 10:")
        for company, count in result['top_companies'][:10]:
            print(f"  - {company}: {count}개")

        return result

    def save_results(self, jobs: List[Dict], result: Dict, output_dir: str = '.'):
        """결과 저장"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # CSV 저장
        df = pd.DataFrame(jobs)
        csv_path = f"{output_dir}/jobs_{timestamp}.csv"
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\n📁 CSV 저장: {csv_path}")

        # JSON 저장
        json_path = f"{output_dir}/analysis_{timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': timestamp,
                'total_jobs': result['total_jobs'],
                'by_source': dict(result['by_source']),
                'tech_frequency': result['tech_frequency'],
                'top_companies': result['top_companies'],
            }, f, ensure_ascii=False, indent=2)
        print(f"📁 분석 결과 저장: {json_path}")

        # 마크다운 리포트 생성
        md_path = f"{output_dir}/report_{timestamp}.md"
        self._generate_report(result, jobs, md_path)
        print(f"📁 리포트 저장: {md_path}")

    def _generate_report(self, result: Dict, jobs: List[Dict], path: str):
        """마크다운 리포트 생성"""
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"# 채용공고 분석 리포트\n\n")
            f.write(f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"## 개요\n\n")
            f.write(f"- 총 분석 공고: {result['total_jobs']}개\n")
            for source, count in result['by_source'].items():
                f.write(f"- {source}: {count}개\n")

            f.write(f"\n## 기술스택 분석\n\n")
            f.write(f"| 순위 | 기술 | 등장 횟수 | 비율 |\n")
            f.write(f"|------|------|----------|------|\n")
            for i, (tech, count) in enumerate(result['tech_frequency'].items(), 1):
                percentage = (count / result['total_jobs']) * 100
                f.write(f"| {i} | {tech} | {count} | {percentage:.1f}% |\n")

            f.write(f"\n## 채용 활발한 회사\n\n")
            for company, count in result['top_companies'][:15]:
                f.write(f"- {company}: {count}개\n")


def main():
    crawler = JobCrawler()
    all_jobs = []

    # 검색 키워드
    keywords = ['데이터 엔지니어', '백엔드 개발자', 'backend developer', 'data engineer']

    print("="*60)
    print("🔍 채용공고 크롤링 시작")
    print("="*60)

    for keyword in keywords:
        # 사람인 크롤링
        saramin_jobs = crawler.crawl_saramin(keyword, pages=3)
        all_jobs.extend(saramin_jobs)

        # 잡코리아 크롤링
        jobkorea_jobs = crawler.crawl_jobkorea(keyword, pages=3)
        all_jobs.extend(jobkorea_jobs)

        # 원티드 크롤링
        wanted_jobs = crawler.crawl_wanted(keyword, limit=30)
        all_jobs.extend(wanted_jobs)

        time.sleep(2)  # 키워드 간 간격

    # 중복 제거 (회사명+제목 기준)
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        key = (job['company'], job['title'])
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    print(f"\n중복 제거 후: {len(unique_jobs)}개 (원본: {len(all_jobs)}개)")

    # 분석
    result = crawler.analyze_jobs(unique_jobs)

    # 저장
    crawler.save_results(unique_jobs, result, output_dir='/home/junhyun/job_crawler')

    print("\n" + "="*60)
    print("✅ 크롤링 및 분석 완료!")
    print("="*60)


if __name__ == '__main__':
    main()
