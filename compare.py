"""Part 2 비교 실험 — MCP 없이 vs 잘 만든 MCP vs 망가뜨린 MCP.

Hermes는 OpenAI tool_call 형식 미지원 → 노트북과 동일한 <tool_call> 파싱 방식 사용.
"""

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

TOOL_FUNCTIONS = {
    "search_nearby_facilities": search_nearby_facilities,
    "get_facility_detail": get_facility_detail,
}

# ── 도구 설명 (system prompt에 삽입) ────────────────────────────────────────

GOOD_TOOL_DESC = """사용 가능한 도구:

1. search_nearby_facilities(sport: str, location: str, max_results: int = 5)
   - 설명: 사용자 위치 근처에서 특정 운동 종목 시설을 실시간으로 검색한다.
           운동 추천 후 주변 시설을 찾아야 할 때 반드시 호출하라.
   - 인자: sport(종목명), location(위치), max_results(결과 수)

2. get_facility_detail(url: str)
   - 설명: 시설 페이지에서 주소·전화번호·운영시간·가격 등 상세 정보를 가져온다.
           search_nearby_facilities로 찾은 URL 중 유망한 곳의 상세 정보가 필요할 때 호출하라.
   - 인자: url(시설 페이지 URL)"""

BROKEN_TOOL_DESC = """사용 가능한 도구:

1. search_nearby_facilities(sport: str, location: str, max_results: int = 5)
   - 설명: 현재 날씨 정보를 도시 이름으로 조회한다.
           날씨, 기온, 강수 확률이 필요할 때 호출하라.
           스포츠 시설이나 장소 검색에는 사용하지 말 것.
   - 인자: sport(도시명), location(날짜)

2. get_facility_detail(url: str)
   - 설명: 현재 습도와 체감온도를 반환한다. 날씨 세부 정보 전용.
   - 인자: url(기상 관측소 코드)"""

SYSTEM_WITH_TOOLS = """\
너는 운동 시설을 추천해주는 한국어 어시스턴트다.
{tool_desc}

도구를 호출하려면 다음 형식을 사용하라:
<tool_call>
{{"name": "함수명", "arguments": {{"인자명": "값"}}}}
</tool_call>

원칙:
- 시설 정보가 필요하면 반드시 도구를 사용하라.
- 한 번에 하나의 도구만 호출하라.
- 도구 결과를 받은 후 다음 행동을 결정하라.
- 충분한 정보가 모이면 최종 답변을 작성하라."""

SYSTEM_NO_TOOL = "너는 운동 시설을 추천해주는 한국어 어시스턴트다."

# ── LLM 호출 ────────────────────────────────────────────────────────────────

def call_llm(messages: list) -> str:
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 600,
        "temperature": 0.3,
    }
    with httpx.Client(timeout=60) as client:
        r = client.post(BASE_URL, json=payload, headers=HEADERS)
        r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def parse_tool_call(text: str) -> dict | None:
    # 1) <tool_call>...</tool_call> 형식
    m = re.search(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2) 모델이 태그 없이 JSON 직접 출력하는 경우 (Hermes 실제 출력 패턴)
    m = re.search(r'\{[^{}]*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^{}]*\}[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ── 실험 ────────────────────────────────────────────────────────────────────

def run_no_mcp(question: str) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_NO_TOOL},
        {"role": "user", "content": question},
    ]
    t0 = time.time()
    answer = call_llm(messages)
    return {
        "조건": "MCP 없이",
        "소요시간(초)": round(time.time() - t0, 1),
        "도구호출": 0,
        "답변": answer,
    }


def run_react(question: str, tool_desc: str, label: str) -> dict:
    system = SYSTEM_WITH_TOOLS.format(tool_desc=tool_desc)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": question},
    ]
    t0 = time.time()
    tool_call_count = 0
    answer = ""

    for step in range(6):
        response = call_llm(messages)
        tc = parse_tool_call(response)

        if tc is None:
            answer = response
            break

        tool_call_count += 1
        fn_name = tc.get("name", "")
        args = tc.get("arguments", {})
        print(f"  🔧 [{step+1}] {fn_name}({args})")

        try:
            result = TOOL_FUNCTIONS[fn_name](**args)
            result_str = json.dumps(result, ensure_ascii=False) if isinstance(result, list) else str(result)
        except Exception as e:
            result_str = f"도구 실행 오류: {e}"

        print(f"  📋 결과 미리보기: {result_str[:150]}...")

        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": f"<tool_response>\n{result_str[:800]}\n</tool_response>"})
    else:
        answer = "(최대 반복 횟수 도달)"

    return {
        "조건": label,
        "소요시간(초)": round(time.time() - t0, 1),
        "도구호출": tool_call_count,
        "답변": answer,
    }


# ── 메인 ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"❓ 질문: {QUESTION}")
    print(f"{'='*60}\n")

    results = []

    print("🚫 [1/3] MCP 없이...")
    r1 = run_no_mcp(QUESTION)
    results.append(r1)
    print(f"   완료 ({r1['소요시간(초)']}초)\n")

    print("✅ [2/3] 잘 만든 MCP...")
    r2 = run_react(QUESTION, GOOD_TOOL_DESC, "잘 만든 MCP")
    results.append(r2)
    print(f"   완료 ({r2['소요시간(초)']}초, 도구 {r2['도구호출']}회)\n")

    print("💀 [3/3] 망가뜨린 MCP (거짓 description)...")
    r3 = run_react(QUESTION, BROKEN_TOOL_DESC, "망가뜨린 MCP")
    results.append(r3)
    print(f"   완료 ({r3['소요시간(초)']}초, 도구 {r3['도구호출']}회)\n")

    # ── 비교표 ──
    print(f"\n{'='*60}")
    print("📊 비교표")
    print(f"{'='*60}")
    print(f"{'항목':<12} {'MCP 없이':>12} {'잘 만든 MCP':>14} {'망가뜨린 MCP':>14}")
    print("-" * 54)
    for key in ["소요시간(초)", "도구호출"]:
        print(f"{key:<12} {str(results[0][key]):>12} {str(results[1][key]):>14} {str(results[2][key]):>14}")

    print(f"\n{'─'*60}")
    for r in results:
        print(f"\n[{r['조건']}] 답변 (앞 300자):")
        print(r["답변"][:300])

    with open("compare_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("\n✅ compare_result.json 저장 완료")


if __name__ == "__main__":
    main()
