# 우아한블로그 스튜디오 (Uahan Studio)

네이버 블로그 검색 → 상위 글 본문 분석(Firecrawl) → 작가형 초안 생성 → 이미지 삽입까지 지원합니다.

## Vercel 배포

1. GitHub 저장소를 Vercel에 연결합니다.
2. **환경 변수** (Project → Settings → Environment Variables):

   - `NAVER_CLIENT_ID`
   - `NAVER_CLIENT_SECRET`
   - `FIRECRAWL_API_KEY`
   - `OPENAI_API_KEY` (선택, 없으면 로컬 고도화 생성기 사용)
   - `REPLICATE_API_TOKEN` (선택, 없거나 402 시 Pollinations 대체)

3. 배포 후 루트 URL에서 `public/index.html` UI를 사용합니다. API는 `/api/*` (예: `/api/search`, `/api/health`)입니다.

### API 요약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/health` | 헬스 체크 |
| POST | `/api/search` | `{ "keyword", "sort": "sim" \| "date" }` |
| POST | `/api/analyze` | `{ "results": [ 검색 결과 배열 ] }` |
| POST | `/api/generate` | `{ "keyword", "tone", "analyzed" }` |
| POST | `/api/summarize` | `{ "keyword", "analyzed" }` |
| POST | `/api/images` | `{ "keyword", "markdown" }` |

## 로컬 Streamlit UI

```powershell
cd uahanStudio
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
streamlit run app.py
```

## 로컬 API만 실행 (선택)

```powershell
pip install -r requirements.txt
uvicorn api.index:app --reload --port 8000
```

`public/index.html`의 `fetch("/api/...")`는 동일 출처가 아니면 실패하므로, 이때는 프록시를 쓰거나 `app.js`의 API base URL을 수정하세요.

네이버 검색은 `mcp-naver` 대신 **공식 Open API**를 `httpx`로 직접 호출합니다. `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET`이 비어 있으면 검색 전에 안내 메시지가 반환됩니다.
