# Python 면접 질문 리스트

> **학습 자료**: `/home/junhyun/kb/languages/Python-Fundamentals/`
> **난이도**: ★ 쉬움 ~ ★★★★★ 어려움

---

## 1. 기초 문법 (면접 빈출)

### ★★ 자주 나오는 질문

| 질문 | 핵심 키워드 |
|------|------------|
| List vs Tuple 차이? | mutable vs immutable |
| `*args`와 `**kwargs` 설명? | 가변 인자, 언패킹 |
| List comprehension 예시? | `[x for x in items if cond]` |
| `is` vs `==` 차이? | 객체 동일성 vs 값 동등성 |
| mutable vs immutable 예시? | list(mutable) vs tuple(immutable) |

### 답변 준비

```python
# 1. *args, **kwargs
def example(*args, **kwargs):
    print(args)    # tuple: (1, 2, 3)
    print(kwargs)  # dict: {'a': 1, 'b': 2}

example(1, 2, 3, a=1, b=2)

# 2. List comprehension
squares = [x**2 for x in range(10) if x % 2 == 0]
# [0, 4, 16, 36, 64]

# 3. is vs ==
a = [1, 2, 3]
b = [1, 2, 3]
a == b  # True (값이 같음)
a is b  # False (다른 객체)
```

---

## 2. 자료구조

### ★★★ 자주 나오는 질문

| 질문 | 핵심 답변 |
|------|----------|
| Dict 내부 구조? | Hash table |
| Set은 언제 쓰나? | 중복 제거, 집합 연산 |
| defaultdict vs dict? | 없는 키 접근 시 기본값 |
| Counter 사용법? | 빈도수 계산 |
| deque vs list? | 양쪽 끝 O(1) 연산 |

### 답변 준비

```python
from collections import defaultdict, Counter, deque

# 1. defaultdict
dd = defaultdict(list)
dd['key'].append(1)  # KeyError 안 남

# 2. Counter
words = ['a', 'b', 'a', 'c', 'a']
Counter(words)  # Counter({'a': 3, 'b': 1, 'c': 1})

# 3. deque (양쪽 끝 O(1))
dq = deque([1, 2, 3])
dq.appendleft(0)  # O(1)
dq.popleft()      # O(1)
```

---

## 3. 함수 & 스코프

### ★★★ 자주 나오는 질문

| 질문 | 핵심 답변 |
|------|----------|
| 클로저(Closure)란? | 외부 변수를 기억하는 함수 |
| 데코레이터 설명? | 함수를 감싸서 기능 추가 |
| lambda 함수란? | 익명 함수 |
| GIL이 뭐예요? | Global Interpreter Lock |

### 답변 준비

```python
# 1. 클로저
def outer(x):
    def inner(y):
        return x + y  # x를 기억
    return inner

add_5 = outer(5)
add_5(3)  # 8

# 2. 데코레이터
def timer(func):
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        print(f"실행시간: {time.time() - start}")
        return result
    return wrapper

@timer
def my_func():
    pass

# 3. GIL
# - Python 인터프리터가 한 번에 하나의 스레드만 실행
# - CPU-bound는 multiprocessing 사용
# - I/O-bound는 threading/asyncio 사용
```

---

## 4. 클래스 & OOP

### ★★★ 자주 나오는 질문

| 질문 | 핵심 답변 |
|------|----------|
| `__init__` vs `__new__`? | new가 먼저, 객체 생성 |
| @property 용도? | getter/setter |
| @classmethod vs @staticmethod? | cls 받음 vs 아무것도 안 받음 |
| 다중 상속 MRO? | Method Resolution Order |

### 답변 준비

```python
class Example:
    class_var = 0  # 클래스 변수

    def __init__(self, value):
        self.instance_var = value  # 인스턴스 변수

    @property
    def computed(self):
        return self.instance_var * 2

    @classmethod
    def from_string(cls, s):
        return cls(int(s))

    @staticmethod
    def helper():
        return "유틸 함수"
```

---

## 5. 비동기 (async/await)

### ★★★★ 자주 나오는 질문 (DE 필수)

| 질문 | 핵심 답변 |
|------|----------|
| async/await 동작 원리? | 이벤트 루프, 코루틴 |
| asyncio vs threading? | 단일 스레드 vs 멀티 스레드 |
| 언제 asyncio 쓰나? | I/O-bound 작업 |

### 답변 준비

```python
import asyncio

# 비동기 함수 (코루틴)
async def fetch_data(url):
    await asyncio.sleep(1)  # I/O 대기
    return f"data from {url}"

# 여러 작업 동시 실행
async def main():
    results = await asyncio.gather(
        fetch_data("url1"),
        fetch_data("url2"),
        fetch_data("url3"),
    )
    # 3초가 아니라 1초 걸림 (동시 실행)

asyncio.run(main())
```

### 내 프로젝트에서의 활용

```python
# aiokafka - 비동기 Kafka Producer
async def produce():
    producer = AIOKafkaProducer(bootstrap_servers='localhost:9092')
    await producer.start()
    await producer.send('topic', b'message')
    await producer.stop()

# asyncpg - 비동기 PostgreSQL
async def query():
    conn = await asyncpg.connect(...)
    result = await conn.fetch("SELECT * FROM table")
```

---

## 6. 에러 처리

### ★★ 자주 나오는 질문

| 질문 | 핵심 답변 |
|------|----------|
| try-except-else-finally? | else=성공시, finally=항상 |
| 커스텀 예외 만들기? | Exception 상속 |
| EAFP vs LBYL? | 허락보다 용서가 쉽다 |

### 답변 준비

```python
# 1. 전체 구조
try:
    result = risky_operation()
except ValueError as e:
    print(f"값 에러: {e}")
except Exception as e:
    print(f"기타 에러: {e}")
else:
    print("성공!")  # 예외 없을 때만
finally:
    cleanup()  # 항상 실행

# 2. 커스텀 예외
class DataProcessingError(Exception):
    def __init__(self, message, error_code):
        super().__init__(message)
        self.error_code = error_code

# 3. EAFP (Pythonic)
try:
    value = my_dict['key']
except KeyError:
    value = default

# vs LBYL (비-Pythonic)
if 'key' in my_dict:
    value = my_dict['key']
else:
    value = default
```

---

## 7. 실전 코딩 문제 (간단한 것만)

### DE 면접에서 나올 수 있는 수준

```python
# 1. 리스트에서 중복 제거 (순서 유지)
def remove_duplicates(items):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result

# 2. 딕셔너리 뒤집기 (key-value swap)
def invert_dict(d):
    return {v: k for k, v in d.items()}

# 3. 두 리스트를 딕셔너리로
keys = ['a', 'b', 'c']
values = [1, 2, 3]
dict(zip(keys, values))  # {'a': 1, 'b': 2, 'c': 3}

# 4. 파일 읽고 처리
from pathlib import Path
import json

data = json.loads(Path('data.json').read_text())
```

---

## 8. 내 경험 기반 예상 질문

### unified-converter 관련

```
Q: "타입 변환 어떻게 처리했어요?"
A: pandas 기반으로 처리.
   - astype()으로 타입 변환
   - 에러 시 coerce 옵션으로 NaN 처리
   - 커스텀 변환 함수 작성

Q: "대용량 파일 처리 어떻게?"
A: - chunksize 파라미터로 분할 읽기
   - generator로 메모리 효율화
   - 배치 단위로 처리
```

### email-collector-v2 관련

```
Q: "비동기 처리 왜 썼어요?"
A: - 이메일 API 호출이 I/O-bound
   - asyncio + aiohttp로 동시 요청
   - GCS 업로드도 비동기로 처리

Q: "재시도 로직 어떻게?"
A: - 지수 백오프 + 지터
   - tenacity 라이브러리 활용 가능
   - 멱등성 보장 (같은 요청 여러번 해도 OK)
```

---

## 학습 우선순위

### 반드시 알아야 함 (★★★★★)
1. `*args, **kwargs`
2. List/Dict comprehension
3. 데코레이터 기본
4. async/await 기본
5. try-except 구조

### 알면 좋음 (★★★☆☆)
1. 클로저
2. Generator (yield)
3. Context manager (with)
4. GIL 개념
5. collections 모듈

### 깊게 안 물어봄 (★★☆☆☆)
1. 메타클래스
2. 복잡한 디스크립터
3. C 확장

---

## 참고 자료

- **kb 문서**: `/home/junhyun/kb/languages/Python-Fundamentals/`
- **Chapter 3**: 함수, *args/**kwargs
- **Chapter 5**: Generator, yield
- **Chapter 7**: 데코레이터
- **Chapter 11**: asyncio

---

*마지막 업데이트: 2026-02-13*
