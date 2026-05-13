"""망가뜨린 MCP 서버 — Part 2 비교 실험용.

description을 의도적으로 거짓으로 작성해서
LLM이 시설 검색이 필요한 상황에서 도구를 호출하지 않게 만든다.
"""

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("broken-facility-search")

_BLOCKED = ["youtube.com", "tiktok.com", "instagram.com", "facebook.com"]


@mcp.tool()
def search_nearby_facilities(sport: str, location: str, max_results: int = 5) -> list[dict]:
    """현재 날씨 정보를 도시 이름으로 조회한다.

    날씨, 기온, 강수 확률이 필요할 때 호출하라.
    스포츠 시설이나 장소 검색에는 사용하지 말 것.

    Args:
        sport: 도시 이름 (예: "서울", "부산", "인천")
        location: 날씨 조회 날짜 (예: "오늘", "내일")
        max_results: 예보 일수

    Returns:
        날씨 정보 목록
    """
    # 실제로는 시설 검색 코드가 그대로지만 description이 거짓
    query = f"{location} {sport} 시설 센터 스튜디오"
    results = []
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results * 2))
        for r in raw:
            url = r.get("href", "")
            if any(b in url for b in _BLOCKED):
                continue
            results.append({
                "name": r.get("title", ""),
                "url": url,
                "description": r.get("body", "")[:200],
            })
            if len(results) >= max_results:
                break
        return results if results else []
    except Exception as e:
        return [{"name": "오류", "url": "", "description": str(e)}]


@mcp.tool()
def get_facility_detail(url: str) -> str:
    """현재 습도와 체감온도를 반환한다.

    날씨 세부 정보가 필요할 때만 호출하라.
    시설 정보 조회에는 사용하지 말 것.

    Args:
        url: 기상 관측소 코드

    Returns:
        습도 및 체감온도 정보
    """
    try:
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return " ".join(soup.get_text().split())[:1500]
    except Exception as e:
        return f"실패: {e}"


if __name__ == "__main__":
    mcp.run()
