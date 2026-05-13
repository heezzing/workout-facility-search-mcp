"""운동 시설 실시간 검색 MCP 서버.

병목: 운동 큐레이션 서비스가 DB에 하드코딩된 25개 서울 시설만 사용해
      사용자 실제 위치와 무관한 시설을 추천하는 문제를 해결한다.
"""

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("workout-facility-search")

_BLOCKED = ["youtube.com", "tiktok.com", "instagram.com", "facebook.com", "twitter.com"]


@mcp.tool()
def search_nearby_facilities(sport: str, location: str, max_results: int = 5) -> list[dict]:
    """사용자 위치 근처에서 특정 운동 종목 시설을 실시간으로 검색한다.

    운동 추천 결과가 나온 뒤 주변 시설을 찾아야 할 때 반드시 호출하라.
    DB에 등록되지 않은 시설도 실시간으로 찾아준다.

    Args:
        sport: 운동 종목 (예: "필라테스", "수영", "클라이밍", "배드민턴", "요가")
        location: 사용자 위치 (예: "강남구", "홍대", "수원", "마포구")
        max_results: 반환할 최대 시설 수 (기본 5, 최대 10)

    Returns:
        [{"name": str, "url": str, "description": str}, ...]
        상세 주소·운영시간이 필요하면 get_facility_detail을 추가 호출하라.
    """
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

        if not results:
            return [{"name": "검색 결과 없음", "url": "", "description": "다른 위치나 종목으로 다시 시도하세요."}]
        return results

    except Exception as e:
        return [{"name": "검색 오류", "url": "", "description": str(e)}]


@mcp.tool()
def get_facility_detail(url: str) -> str:
    """시설 페이지에서 주소·전화번호·운영시간·가격 등 상세 정보를 가져온다.

    search_nearby_facilities로 찾은 URL 중 유망한 곳의 상세 정보가
    필요할 때 호출하라. 한 번에 URL 하나씩만 호출하라.

    Args:
        url: 조회할 시설 페이지 URL

    Returns:
        페이지 본문 텍스트 (최대 1500자)
    """
    try:
        r = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return " ".join(soup.get_text().split())[:1500]
    except Exception as e:
        return f"페이지 가져오기 실패: {e}"


if __name__ == "__main__":
    mcp.run()
