# workout-facility-search MCP Server

운동 큐레이션 서비스의 시설 검색 병목을 해결하는 MCP 서버.

## 해결한 병목

**Before**: DB에 하드코딩된 25개 서울 시설 중에서만 매칭 → 사용자 위치 무관한 결과  
**After**: 사용자 위치 + 추천 종목으로 실시간 웹 검색 → 실제 주변 시설 반환

## 도구 2개

| 도구 | 설명 |
|------|------|
| `search_nearby_facilities(sport, location)` | 위치 + 종목으로 주변 시설 검색 |
| `get_facility_detail(url)` | 시설 페이지에서 주소·운영시간·가격 추출 |

## 설치 및 실행

```bash
pip install -r requirements.txt

# Hermes에 등록
hermes mcp add facility-search "python3 /path/to/facility_search_server.py"
hermes mcp list
```

## 사용 예시

Hermes에서:
> "강남구 근처 클라이밍 시설 찾아줘"  
> "홍대 근처 수영장 알려줘"
