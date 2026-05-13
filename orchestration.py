"""Part 3 Orchestration 3패턴 비교.

패턴 1: 싱글 에이전트       — 처음부터 끝까지 혼자
패턴 2: Planner + Executor  — 계획만 짜는 LLM + 실행하는 LLM
패턴 3: 병렬 sub-agent      — asyncio로 여러 지역을 동시 검색 후 머지
"""

import asyncio
import json
import os
import re
import time

import httpx

from facility_search_server import get_facility_detail, search_nearby_facilities

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
BASE_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "nousresearch/hermes-3-llama-3.1-70b"
QUESTION = "홍대 근처 클라이밍 시설 추천해줘"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

TOOL_DESC = """사용 가능한 도구:

1. search_nearby_facilities(sport: str, location: str, max_results: int = 5)
   - 설명: 사용자 위치 근처에서 특정 운동 종목 시설을 실시간으로 검색한다.
           운동 추천 후 주변 시설을 찾아야 할 때 반드시 호출하라.
   - 인자: sport(종목명), location(위치), max_results(결과 수)

2. get_facility_detail(url: str)
   - 설명: 시설 페이지에서 주소·전화번호·운영시간·가격 등 상세 정보를 가져온다.
   - 인자: url(시설 페이지 URL)"""

TOOL_FUNCTIONS = {
    "search_nearby_facilities": search_nearby_facilities,
    "get_facility_detail": get_facility_detail,
}


# ── 공통 유틸 ────────────────────────────────────────────────────────────────

def call_llm(messages: list) -> tuple[str, int]:
    """(응답 텍스트, 총 토큰) 반환."""
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 700,
        "temperature": 0.3,
    }
    with httpx.Client(timeout=60) as client:
        r = client.post(BASE_URL, json=payload, headers=HEADERS)
        r.raise_for_status()
    data = r.json()
    text = data["choices"][0]["message"]["content"] or ""
    tokens = data.get("usage", {}).get("total_tokens", 0)
    return text, tokens


def parse_tool_call(text: str) -> dict | None:
    m = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(
        r'\{[^{}]*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^{}]*\}[^{}]*\}',
        text, re.DOTALL,
    )
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


def run_tool(tc: dict) -> str:
    fn_name = tc.get("name", "")
    args = tc.get("arguments", {})
    try:
        result = TOOL_FUNCTIONS[fn_name](**args)
        return json.dumps(result, ensure_ascii=False) if isinstance(result, list) else str(result)
    except Exception as e:
        return f"오류: {e}"


# ── 패턴 1: 싱글 에이전트 ───────────────────────────────────────────────────

def run_single(question: str) -> dict:
    """에이전트 1명이 계획·검색·답변을 혼자 처리."""
    system = (
        "너는 운동 시설을 추천해주는 한국어 어시스턴트다.\n"
        + TOOL_DESC
        + "\n\n도구 호출 형식: {\"name\": \"함수명\", \"arguments\": {\"인자\": \"값\"}}\n"
        "원칙: 시설 정보가 필요하면 도구를 사용하라. 충분한 정보가 모이면 최종 답변."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    t0 = time.time()
    total_tokens = 0
    tool_calls = 0
    answer = ""

    for _ in range(6):
        text, tokens = call_llm(messages)
        total_tokens += tokens
        tc = parse_tool_call(text)
        if tc is None:
            answer = text
            break
        tool_calls += 1
        print(f"    🔧 싱글 → {tc['name']}({tc.get('arguments', {})})")
        result = run_tool(tc)
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": f"<tool_response>\n{result[:800]}\n</tool_response>"})
    else:
        answer = "(최대 반복 도달)"

    return {
        "패턴": "싱글 에이전트",
        "소요시간(초)": round(time.time() - t0, 1),
        "총 토큰": total_tokens,
        "LLM 호출 수": 1 + tool_calls,
        "도구 호출 수": tool_calls,
        "답변": answer,
    }


# ── 패턴 2: Planner + Executor ───────────────────────────────────────────────

def run_planner_executor(question: str) -> dict:
    """Planner가 계획을 세우고, Executor가 도구를 써서 실행."""
    t0 = time.time()
    total_tokens = 0

    # --- Planner ---
    planner_system = (
        "너는 계획 전문가다. 다음 요청을 수행하기 위한 단계를 3개 이내로 적어라.\n"
        "도구를 직접 호출하지 말고 단계만 텍스트로 나열하라.\n"
        "예시:\n"
        "1. search_nearby_facilities로 홍대 클라이밍 시설 검색\n"
        "2. 결과 중 상위 1곳의 URL로 get_facility_detail 호출\n"
        "3. 수집된 정보로 추천 답변 작성"
    )
    plan_msg = [
        {"role": "system", "content": planner_system},
        {"role": "user", "content": question},
    ]
    plan, tokens = call_llm(plan_msg)
    total_tokens += tokens
    print(f"    📋 Planner 계획:\n{plan[:200]}")

    # --- Executor ---
    executor_system = (
        "너는 실행 전문가다. 아래 계획을 순서대로 실행하라.\n"
        + TOOL_DESC
        + "\n\n도구 호출 형식: {\"name\": \"함수명\", \"arguments\": {\"인자\": \"값\"}}\n"
        "계획을 따라 도구를 호출하고, 모든 단계가 완료되면 최종 답변을 작성하라."
    )
    exec_messages = [
        {"role": "system", "content": executor_system},
        {"role": "user", "content": f"질문: {question}\n\n실행할 계획:\n{plan}"},
    ]
    tool_calls = 0
    answer = ""

    for _ in range(6):
        text, tokens = call_llm(exec_messages)
        total_tokens += tokens
        tc = parse_tool_call(text)
        if tc is None:
            answer = text
            break
        tool_calls += 1
        print(f"    🔧 Executor → {tc['name']}({tc.get('arguments', {})})")
        result = run_tool(tc)
        exec_messages.append({"role": "assistant", "content": text})
        exec_messages.append({"role": "user", "content": f"<tool_response>\n{result[:800]}\n</tool_response>"})
    else:
        answer = "(최대 반복 도달)"

    return {
        "패턴": "Planner+Executor",
        "소요시간(초)": round(time.time() - t0, 1),
        "총 토큰": total_tokens,
        "LLM 호출 수": 2 + tool_calls,
        "도구 호출 수": tool_calls,
        "답변": answer,
    }


# ── 패턴 3: 병렬 sub-agent ──────────────────────────────────────────────────

async def _search_area(sport: str, location: str) -> str:
    """단일 지역 검색 (비동기 래퍼)."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, lambda: search_nearby_facilities(sport, location, 3)
    )
    return json.dumps(result, ensure_ascii=False)


async def _parallel_search(sport: str, locations: list[str]) -> list[str]:
    """여러 지역을 동시에 검색."""
    tasks = [_search_area(sport, loc) for loc in locations]
    return await asyncio.gather(*tasks)


def run_parallel_subagent(question: str) -> dict:
    """여러 지역을 asyncio로 동시 검색 → 메인 LLM이 결과 머지."""
    t0 = time.time()
    total_tokens = 0
    locations = ["홍대", "합정", "연남동"]
    sport = "클라이밍"

    # 병렬 검색 실행
    print(f"    ⚡ 병렬 검색: {locations}")
    raw_results = asyncio.run(_parallel_search(sport, locations))
    search_time = round(time.time() - t0, 1)
    print(f"    ⚡ 검색 완료 ({search_time}초, {len(locations)}개 지역 동시)")

    # 결과 머지 — 메인 LLM 호출
    merged_context = "\n\n".join(
        f"[{loc} 검색 결과]\n{res[:400]}"
        for loc, res in zip(locations, raw_results)
    )
    merge_messages = [
        {
            "role": "system",
            "content": "너는 운동 시설 추천 전문가다. 여러 지역의 검색 결과를 종합해서 최선의 추천 답변을 한국어로 작성하라.",
        },
        {
            "role": "user",
            "content": f"질문: {question}\n\n수집된 시설 정보:\n{merged_context}",
        },
    ]
    answer, tokens = call_llm(merge_messages)
    total_tokens += tokens

    return {
        "패턴": "병렬 sub-agent",
        "소요시간(초)": round(time.time() - t0, 1),
        "총 토큰": total_tokens,
        "LLM 호출 수": 1,
        "도구 호출 수": len(locations),
        "답변": answer,
    }


# ── 메인 ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"❓ 질문: {QUESTION}")
    print(f"{'='*60}\n")

    results = []

    print("1️⃣  싱글 에이전트...")
    r1 = run_single(QUESTION)
    results.append(r1)
    print(f"   완료 ({r1['소요시간(초)']}초, 토큰 {r1['총 토큰']})\n")

    print("2️⃣  Planner + Executor...")
    r2 = run_planner_executor(QUESTION)
    results.append(r2)
    print(f"   완료 ({r2['소요시간(초)']}초, 토큰 {r2['총 토큰']})\n")

    print("3️⃣  병렬 sub-agent...")
    r3 = run_parallel_subagent(QUESTION)
    results.append(r3)
    print(f"   완료 ({r3['소요시간(초)']}초, 토큰 {r3['총 토큰']})\n")

    # ── 벤치마크 표 ──
    print(f"\n{'='*60}")
    print("📊 Orchestration 벤치마크 표")
    print(f"{'='*60}")
    headers = ["소요시간(초)", "총 토큰", "LLM 호출 수", "도구 호출 수"]
    print(f"{'항목':<14} {'싱글':>10} {'Planner+Exec':>14} {'병렬 sub':>10}")
    print("-" * 52)
    for key in headers:
        print(f"{key:<14} {str(r1[key]):>10} {str(r2[key]):>14} {str(r3[key]):>10}")

    print(f"\n{'─'*60}")
    for r in results:
        print(f"\n[{r['패턴']}] 답변 (앞 250자):")
        print(r["답변"][:250])

    with open("orchestration_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n✅ orchestration_result.json 저장 완료")


if __name__ == "__main__":
    main()
