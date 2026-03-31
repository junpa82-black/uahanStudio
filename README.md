# Naver MCP Blog Studio

키워드를 입력하면 네이버 블로그를 관련도순으로 상위 10개 검색하고, 상위 5개 글을 Firecrawl로 분석해 핵심 키워드/요약을 제공합니다.  
분석 결과를 벤치마킹해 완전히 새로운 블로그 초안을 생성하고, Replicate로 어울리는 이미지를 자동 생성/삽입한 뒤 바탕화면에 저장할 수 있습니다.

## 실행 방법

```powershell
cd C:\Users\user\cursorstudy\naver-mcp-blog-studio
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

## 필수 환경변수

- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `FIRECRAWL_API_KEY` (Firecrawl 분석용)
- `OPENAI_API_KEY` (신규 글 생성 품질 향상용, 없으면 로컬 고도화 생성)
- `REPLICATE_API_TOKEN` (Replicate 이미지 생성용)

## 주요 기능

- `검색 실행`: Naver MCP(`mcp_naver.server.search_blog`)로 상위 10개 검색
- `Firecrawl로 상위 5개 분석`: 본문 수집 후 키워드/요약 생성
- `생성하기`: 5개 분석 결과를 참고해 창의적인 신규 블로그 글 생성
- `이미지 생성 및 자동 삽입`: Replicate(FLUX)로 이미지 2장을 생성해 플레이스홀더 자동 치환
- `저장하기`: 마크다운 + 생성 이미지를 함께 바탕화면 폴더에 저장
