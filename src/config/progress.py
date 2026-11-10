from time import perf_counter

# 실행 시간 측정
def spand_time(func, *args, **kwargs):
    start_time = perf_counter()
    result = func(*args, **kwargs)
    elapsed = perf_counter() - start_time
    print(f"\n[실행 완료] 소요시간: {elapsed:.2f}초")
    return result