# SQL 면접 질문 리스트

> **중요도**: ★★★★★ (DE 필수)
> **내 경험**: BigQuery, PostgreSQL
> **난이도**: ★ 쉬움 ~ ★★★★★ 어려움

---

## 1. 기본 문법 (직접 쓸 수 있어야 함)

### ★★★★★ 필수 숙지

```sql
-- 1. 기본 집계
SELECT
    customer_id,
    DATE(created_at) as order_date,
    COUNT(*) as order_count,
    SUM(amount) as total_amount,
    AVG(amount) as avg_amount
FROM orders
WHERE created_at >= '2026-01-01'
GROUP BY 1, 2
HAVING COUNT(*) > 5
ORDER BY total_amount DESC
LIMIT 100;

-- 2. JOIN
SELECT
    o.order_id,
    o.amount,
    c.name as customer_name,
    p.name as product_name
FROM orders o
LEFT JOIN customers c ON o.customer_id = c.id
INNER JOIN products p ON o.product_id = p.id
WHERE o.status = 'completed';

-- 3. 서브쿼리
SELECT *
FROM orders
WHERE customer_id IN (
    SELECT id
    FROM customers
    WHERE tier = 'premium'
);
```

---

## 2. Window Functions (자주 나옴)

### ★★★★ 자주 나오는 질문

| 함수 | 용도 | 예시 |
|------|------|------|
| ROW_NUMBER() | 순번 | 고객별 최근 주문 1개 |
| RANK() / DENSE_RANK() | 순위 | 매출 순위 |
| LAG() / LEAD() | 이전/다음 값 | 전일 대비 |
| SUM() OVER() | 누적합 | 누적 매출 |

### 코드 예시

```sql
-- 1. 고객별 최근 주문 1개
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY customer_id
            ORDER BY created_at DESC
        ) as rn
    FROM orders
)
SELECT * FROM ranked WHERE rn = 1;

-- 2. 전일 대비 매출
SELECT
    order_date,
    daily_sales,
    LAG(daily_sales) OVER (ORDER BY order_date) as prev_day,
    daily_sales - LAG(daily_sales) OVER (ORDER BY order_date) as diff
FROM daily_summary;

-- 3. 누적 합계
SELECT
    order_date,
    daily_sales,
    SUM(daily_sales) OVER (
        ORDER BY order_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) as cumulative_sales
FROM daily_summary;
```

---

## 3. CTE (Common Table Expression)

### ★★★★ 자주 나오는 질문

```sql
-- WITH 절 사용
WITH
-- 1단계: 일별 집계
daily_stats AS (
    SELECT
        DATE(created_at) as order_date,
        COUNT(*) as order_count,
        SUM(amount) as total_amount
    FROM orders
    GROUP BY 1
),
-- 2단계: 주별 집계
weekly_stats AS (
    SELECT
        DATE_TRUNC(order_date, WEEK) as week_start,
        SUM(order_count) as weekly_orders,
        SUM(total_amount) as weekly_amount
    FROM daily_stats
    GROUP BY 1
)
-- 최종 결과
SELECT * FROM weekly_stats ORDER BY week_start;
```

---

## 4. BigQuery 특화 (당근페이, 원티드랩)

### ★★★★ 자주 나오는 질문

| 질문 | 핵심 답변 |
|------|----------|
| 파티셔닝이란? | 날짜별 데이터 분할 저장 |
| 클러스터링이란? | 자주 필터링하는 컬럼으로 정렬 |
| MERGE 문? | UPSERT (INSERT or UPDATE) |
| UNNEST? | 배열 데이터 펼치기 |

### 코드 예시

```sql
-- 1. 파티션 테이블 생성
CREATE TABLE orders
PARTITION BY DATE(created_at)
CLUSTER BY customer_id
AS SELECT * FROM raw_orders;

-- 2. MERGE (멱등성 보장)
MERGE target_table t
USING source_table s
ON t.id = s.id
WHEN MATCHED THEN
    UPDATE SET t.value = s.value, t.updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
    INSERT (id, value, created_at)
    VALUES (s.id, s.value, CURRENT_TIMESTAMP());

-- 3. UNNEST (배열 펼치기)
SELECT
    order_id,
    item.product_id,
    item.quantity
FROM orders,
UNNEST(items) as item;
```

---

## 5. 성능 최적화

### ★★★★ 자주 나오는 질문

| 질문 | 핵심 답변 |
|------|----------|
| 쿼리 느릴 때? | EXPLAIN, 인덱스, 파티션 |
| SELECT * 문제? | 필요한 컬럼만 선택 |
| JOIN 최적화? | 작은 테이블 먼저, 필터 먼저 |

### 최적화 체크리스트

```sql
-- ❌ 나쁜 예
SELECT *
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE DATE(o.created_at) = '2026-01-01';

-- ✅ 좋은 예
SELECT
    o.order_id,
    o.amount,
    c.name
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE o.created_at >= '2026-01-01'
  AND o.created_at < '2026-01-02';  -- 파티션 활용
```

---

## 6. 실전 문제 (면접에서 나올 수 있는 수준)

### 문제 1: 연속 로그인 일수

```sql
-- 7일 연속 로그인한 유저 찾기
WITH login_groups AS (
    SELECT
        user_id,
        login_date,
        login_date - ROW_NUMBER() OVER (
            PARTITION BY user_id
            ORDER BY login_date
        ) * INTERVAL 1 DAY as grp
    FROM daily_logins
)
SELECT
    user_id,
    MIN(login_date) as streak_start,
    COUNT(*) as streak_days
FROM login_groups
GROUP BY user_id, grp
HAVING COUNT(*) >= 7;
```

### 문제 2: 월별 신규/재구매 비율

```sql
WITH first_orders AS (
    SELECT
        customer_id,
        MIN(DATE(created_at)) as first_order_date
    FROM orders
    GROUP BY 1
)
SELECT
    DATE_TRUNC(o.created_at, MONTH) as month,
    COUNT(CASE WHEN DATE(o.created_at) = f.first_order_date
          THEN 1 END) as new_customers,
    COUNT(CASE WHEN DATE(o.created_at) > f.first_order_date
          THEN 1 END) as returning_customers
FROM orders o
JOIN first_orders f ON o.customer_id = f.customer_id
GROUP BY 1
ORDER BY 1;
```

---

## 7. 내 경험 기반 예상 질문

### Q: "데이터 품질 어떻게 관리했어요?"

```sql
-- 1. 중복 체크
SELECT file_id, COUNT(*)
FROM processed_files
GROUP BY file_id
HAVING COUNT(*) > 1;

-- 2. NULL 체크
SELECT
    COUNT(*) as total,
    COUNT(customer_id) as with_customer,
    COUNT(*) - COUNT(customer_id) as null_customer
FROM orders;

-- 3. 범위 체크
SELECT *
FROM orders
WHERE amount < 0 OR amount > 10000000;
```

### Q: "BigQuery 비용 최적화?"

```
1. 파티션 프루닝
   - WHERE 절에 파티션 컬럼 사용

2. 클러스터링
   - 자주 필터링하는 컬럼으로 클러스터

3. 쿼리 최적화
   - SELECT * 피하기
   - 필요한 데이터만 스캔

4. 슬롯 관리
   - 피크 시간 외 배치 실행
```

---

## 8. 면접 라이브 코딩 대비

### 자주 나오는 패턴

```sql
-- 1. Top N per group
-- 각 카테고리별 매출 상위 3개 상품
WITH ranked AS (
    SELECT
        category,
        product_name,
        sales,
        ROW_NUMBER() OVER (
            PARTITION BY category
            ORDER BY sales DESC
        ) as rn
    FROM products
)
SELECT * FROM ranked WHERE rn <= 3;

-- 2. Running total
-- 일별 누적 매출
SELECT
    date,
    daily_sales,
    SUM(daily_sales) OVER (ORDER BY date) as cumulative
FROM daily_summary;

-- 3. Gap detection
-- 빠진 날짜 찾기
SELECT
    date,
    LEAD(date) OVER (ORDER BY date) as next_date,
    DATE_DIFF(LEAD(date) OVER (ORDER BY date), date, DAY) as gap
FROM daily_data
HAVING gap > 1;
```

---

## 학습 우선순위

### 반드시 알아야 함 (★★★★★)
1. SELECT, JOIN, GROUP BY, HAVING
2. Window Functions (ROW_NUMBER, LAG, SUM OVER)
3. CTE (WITH 절)
4. 집계 함수 (COUNT, SUM, AVG)

### 알면 좋음 (★★★☆☆)
1. MERGE (UPSERT)
2. 파티셔닝/클러스터링 개념
3. EXPLAIN 읽는 법
4. 재귀 CTE

### DE 면접에서 안 나옴 (★☆☆☆☆)
1. 복잡한 알고리즘 문제
2. 저장 프로시저 작성
3. DB 관리 (DBA 영역)

---

*마지막 업데이트: 2026-02-13*
