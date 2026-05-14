# workout-facility-search MCP Server

**1차 과제 프로젝트** → https://github.com/heezzing/Hz-Exercise-Bot  
이 레포는 위 프로젝트의 시설 검색 병목을 해결하기 위해 추가로 구현한 MCP 서버입니다.

## 해결한 병목

**Before**: DB에 하드코딩된 25개 서울 시설 중에서만 매칭 → 사용자 위치 무관한 결과  
**After**: 사용자 위치 + 추천 종목으로 실시간 웹 검색 → 실제 주변 시설 반환

## 도구 2개

| 도구 | 설명 |
|------|------|
| `search_nearby_facilities(sport, location)` | 위치 + 종목으로 주변 시설 검색 |
| `get_facility_detail(url)` | 시설 페이지에서 주소·운영시간·가격 추출 |

## 설치

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY="your_key_here"
```

## 실행

### MCP 서버 단독 실행
```bash
python3 facility_search_server.py
```

### Part 2 — 성공/실패 비교 실험 (MCP 없이 vs 잘 만든 MCP vs 망가뜨린 MCP)
```bash
python3 compare.py
# 결과: compare_result.json
```

### Part 3 — Orchestration 3패턴 벤치마크 (싱글 / Planner+Executor / 병렬 sub-agent)
```bash
python3 orchestration.py
# 결과: orchestration_result.json
```

### Hermes에 MCP 서버 등록
```bash
hermes mcp add facility-search "python3 /path/to/facility_search_server.py"
hermes mcp list
```

## 사용 예시

Hermes에서:
> "강남구 근처 클라이밍 시설 찾아줘"  
> "홍대 근처 수영장 알려줘"
