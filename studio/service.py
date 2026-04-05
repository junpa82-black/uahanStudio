import asyncio
import json
import os
import random
import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

_NAVER_ENV_MSG = (
    "NAVER_CLIENT_ID와 NAVER_CLIENT_SECRET을 환경 변수에 설정해 주세요. "
    "로컬: uahanStudio 폴더에 .env를 두세요(.env.example 복사 후 값 입력). "
    "python-dotenv가 설치되어 있어야 .env가 읽힙니다. "
    "Vercel: Project → Settings → Environment Variables에 추가 후 재배포하세요."
)

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default)
    return (v or "").strip()


def get_replicate_token() -> str:
    return _env("REPLICATE_API_TOKEN")

KOREAN_STOPWORDS = {
    "그리고",
    "하지만",
    "그래서",
    "정말",
    "이번",
    "대한",
    "관련",
    "위해",
    "에서",
    "입니다",
    "있는",
    "하는",
    "했다",
    "같은",
    "블로그",
    "포스팅",
    "후기",
}


def strip_html(text: str) -> str:
    clean = re.sub(r"<[^>]+>", "", text or "")
    return unescape(clean).strip()


async def search_blog_by_naver_mcp(query: str, display: int = 10, sort: str = "sim") -> list[dict[str, Any]]:
    """네이버 블로그 검색 API 직접 호출 (환경변수 미설정 시 None 헤더로 httpx 오류 나지 않도록 처리)."""
    client_id = _env("NAVER_CLIENT_ID")
    client_secret = _env("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(_NAVER_ENV_MSG)
    url = "https://openapi.naver.com/v1/search/blog.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "start": 1, "sort": sort}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        raw = response.text
    payload = json.loads(raw)
    items = payload.get("items", [])
    normalized = []
    for item in items:
        normalized.append(
            {
                "title": strip_html(item.get("title", "")),
                "description": strip_html(item.get("description", "")),
                "link": item.get("link", ""),
                "bloggername": item.get("bloggername", ""),
                "postdate": item.get("postdate", ""),
            }
        )
    return normalized


def _format_naver_pub_date(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = parsedate_to_datetime(raw)
        return parsed.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return raw


async def search_news_by_naver_api(query: str, display: int = 12, sort: str = "date") -> list[dict[str, Any]]:
    """네이버 뉴스 검색 API 직접 호출."""
    client_id = _env("NAVER_CLIENT_ID")
    client_secret = _env("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(_NAVER_ENV_MSG)

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {"query": query, "display": display, "start": 1, "sort": sort}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()

    normalized = []
    for item in payload.get("items", []):
        source_link = (item.get("originallink") or "").strip()
        naver_link = (item.get("link") or "").strip()
        final_link = source_link or naver_link
        source_name = "뉴스"
        if source_link:
            host = (urlparse(source_link).netloc or "").replace("www.", "")
            source_name = host or source_name
        normalized.append(
            {
                "title": strip_html(item.get("title", "")),
                "description": strip_html(item.get("description", "")),
                "link": final_link,
                "originallink": source_link,
                "naverlink": naver_link,
                "source": source_name,
                "pubDate": _format_naver_pub_date(item.get("pubDate", "")),
            }
        )
    return normalized


def _is_public_http_url(url: str) -> bool:
    try:
        p = urlparse((url or "").strip())
        if p.scheme not in ("http", "https") or not p.netloc:
            return False
        host = (p.netloc or "").split("@")[-1].split(":")[0].lower()
        if host in ("localhost", "127.0.0.1") or host.endswith(".local"):
            return False
        return True
    except Exception:
        return False


def _normalize_economy_rows_from_web_json(data: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    items = data.get("items")
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if len(normalized) >= limit:
            break
        if not isinstance(item, dict):
            continue
        title = strip_html(str(item.get("title", "")).strip())
        desc = strip_html(str(item.get("description", "")).strip())
        url = str(item.get("url", "")).strip()
        source = str(item.get("source", "")).strip() or "웹 검색"
        published = str(item.get("published", "")).strip()[:32]
        if not title or not _is_public_http_url(url):
            continue
        normalized.append(
            {
                "title": title,
                "description": desc,
                "link": url,
                "originallink": url,
                "naverlink": url,
                "source": source,
                "pubDate": published,
            }
        )
    return normalized


async def search_economy_news_by_web_search(query: str, display: int = 12, sort: str = "date") -> list[dict[str, Any]]:
    """OpenAI Responses API의 웹 검색 도구로 키워드 관련 최신 경제 뉴스를 찾아 반환합니다."""
    q = (query or "").strip()
    if not q:
        raise ValueError("검색 키워드가 비어 있습니다.")

    api_key = _env("OPENAI_API_KEY").strip().strip('"').strip("'")
    if not api_key:
        raise ValueError("웹 뉴스 검색에는 OPENAI_API_KEY가 필요합니다.")

    n = max(4, min(int(display or 12), 12))
    sort_rule = (
        "최신 발행·시의성이 높은 기사를 배열 앞쪽에 둘 것."
        if sort == "date"
        else "검색 키워드와 헤드라인·본문 주제 적합도가 높은 기사를 배열 앞쪽에 둘 것."
    )

    item_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "url": {"type": "string"},
            "source": {"type": "string"},
            "published": {"type": "string"},
        },
        "required": ["title", "description", "url", "source", "published"],
        "additionalProperties": False,
    }
    top_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": item_schema,
                "minItems": n,
                "maxItems": n,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    instructions = (
        "너는 한국 경제 뉴스 큐레이터다. 반드시 웹 검색 도구로 인터넷에서 기사를 조회한 뒤에만 답한다. "
        "기사 URL은 검색으로 확인된 실제 페이지 주소만 쓰고, 추측·가공으로 URL을 만들지 않는다."
    )

    user_prompt = f"""검색 키워드: 「{q[:200]}」

웹 검색으로 위 키워드와 관련된 **한국 경제·금융·산업·고용·물가·환율·부동산·증시** 뉴스를 찾아라.

규칙:
- **한국어 보도**를 우선하고, 가능하면 서로 다른 언론·출처를 섞는다.
- 응답 JSON의 items 배열 길이는 **정확히 {n}개** (부족하면 검색어를 넓혀 관련 기사를 더 찾을 것).
- 각 url은 **해당 기사 본문 페이지**의 http(s) 링크여야 한다 (포털 검색 결과 페이지·메인 홈만 있는 URL 금지).
- description은 검색 스니펫·기사 요지에 근거해 2~4문장으로 요약한다.
- source는 언론사명 또는 사이트명을 짧게.
- published는 기사 날짜를 알 수 있으면 YYYY-MM-DD, 아니면 빈 문자열.
- 정렬: {sort_rule}

최종 출력 형식: JSON 객체 하나만. 키는 `items` 배열과, 각 원소의 `title`, `description`, `url`, `source`, `published` 만 사용한다.
"""

    tool_web: dict[str, Any] = {
        "type": "web_search",
        "user_location": {"type": "approximate", "country": "KR"},
        "search_context_size": "high",
    }

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)

    async def _responses_json(*, use_schema: bool, force_tool: bool) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": "gpt-4o",
            "instructions": instructions,
            "input": user_prompt,
            "tools": [tool_web],
            "tool_choice": "required" if force_tool else "auto",
            "temperature": 0.15,
            "max_output_tokens": 8192,
        }
        if use_schema:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "economy_news_feed",
                    "strict": True,
                    "schema": top_schema,
                }
            }
        resp = await client.responses.create(**kwargs)
        raw = (resp.output_text or "").strip()
        return _parse_llm_json_object(raw)

    try:
        rows: list[dict[str, Any]] = []
        try:
            data = await _responses_json(use_schema=True, force_tool=True)
            rows = _normalize_economy_rows_from_web_json(data, limit=n)
        except Exception:
            rows = []
        if len(rows) < min(4, n):
            try:
                data = await _responses_json(use_schema=False, force_tool=False)
                rows2 = _normalize_economy_rows_from_web_json(data, limit=n)
                if len(rows2) > len(rows):
                    rows = rows2
            except Exception:
                pass

        if len(rows) < min(4, n):
            raise ValueError(
                "웹 검색으로 가져온 유효한 기사 링크가 부족합니다. 키워드를 바꾸거나 잠시 후 다시 시도해 주세요."
            )
        return rows[:n]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"웹 뉴스 검색 실패: {exc}") from exc


# 호환용 (기존 코드·문서에서 이름 참조 시)
search_economy_news_by_gpt = search_economy_news_by_web_search


def _categorize_economy_article(text: str) -> str:
    corpus = (text or "").lower()
    rules = [
        ("정책·금리", ["금리", "기준금리", "한국은행", "연준", "fomc", "물가", "cpi", "pce"]),
        ("증시·투자", ["주가", "증시", "코스피", "코스닥", "나스닥", "s&p", "etf", "투자"]),
        ("부동산", ["부동산", "주택", "아파트", "분양", "전세", "월세", "재건축"]),
        ("환율·원자재", ["환율", "달러", "원화", "유가", "원유", "금값", "원자재"]),
        ("기업·산업", ["실적", "매출", "영업이익", "반도체", "수출", "공급망", "기업"]),
    ]
    for category, keywords in rules:
        if any(keyword in corpus for keyword in keywords):
            return category
    return "글로벌·기타"


def build_economy_briefing(topic: str, results: list[dict[str, Any]]) -> str:
    picked = results[:10]
    if not picked:
        return "분석할 뉴스가 없어 브리핑을 생성하지 못했습니다."

    keyword_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    headline_lines: list[str] = []

    for row in picked:
        title = row.get("title", "").strip()
        desc = row.get("description", "").strip()
        source = row.get("source", "뉴스")
        published = row.get("pubDate", "")
        category = _categorize_economy_article(f"{title} {desc}")
        category_counter.update([category])
        keyword_counter.update(extract_keywords(f"{title} {desc}", top_k=5))
        headline_lines.append(
            f"- [{category}] {title}\n  - 출처: {source}"
            + (f" · {published}" if published else "")
        )

    top_keywords = [k for k, _ in keyword_counter.most_common(8)]
    top_categories = [f"{name} {count}건" for name, count in category_counter.most_common(3)]
    dominant = category_counter.most_common(1)[0][0]
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    keyword_line = ", ".join(top_keywords) if top_keywords else "경제, 시장, 정책"
    category_line = " / ".join(top_categories) if top_categories else "분류 데이터 부족"

    insights = [
        f"헤드라인 분포상 **{dominant}** 이슈 비중이 높아, 단기 뉴스 흐름이 해당 축에 집중되고 있습니다.",
        "여러 기사에서 공통으로 등장한 키워드는 시장 참여자들이 현재 가장 민감하게 보는 변수로 해석할 수 있습니다.",
        "실행 측면에서는 수치(금리·환율·지수) 업데이트를 확인한 뒤, 산업/기업 뉴스와 교차 검증하는 순서가 안전합니다.",
    ]

    return (
        f"### 경제 데일리 브리핑: {topic}\n\n"
        f"- 기준 시각: {now_label}\n"
        f"- 핵심 키워드: {keyword_line}\n"
        f"- 이슈 분포: {category_line}\n\n"
        "#### 주요 헤드라인\n"
        + "\n".join(headline_lines[:6])
        + "\n\n#### 오늘의 시사점\n"
        + "\n".join([f"{idx}. {line}" for idx, line in enumerate(insights, start=1)])
    )


def _economy_news_article_block(topic: str, results: list[dict[str, Any]], base_briefing: str) -> str:
    """LLM에 넣을 뉴스 맥락: 자동 브리핑 + 기사 스니펫."""
    parts = [
        f"[검색 주제]\n{topic}\n",
        "[자동 브리핑 요약]\n" + base_briefing + "\n",
        "[개별 기사 스니펫]\n",
    ]
    for i, row in enumerate(results[:12], 1):
        title = (row.get("title") or "").strip()
        desc = (row.get("description") or "").strip()
        src = (row.get("source") or "뉴스").strip()
        link = (row.get("link") or "").strip()
        tail = f"\n   링크: {link}" if link else ""
        parts.append(f"{i}. [{src}] {title}\n   본문/요약 일부: {desc[:500]}{tail}\n")
    return "\n".join(parts)


_BRIEFING_SCHOOL_LEVELS = frozenset({"초등", "중등", "고등"})


def _part2_school_instruction(request_level: str | None) -> str:
    """PART 2 제목 괄호 안 학력·난이도 지시. 미지정 시 40대 주부 가정 기준."""
    for candidate in ((request_level or "").strip(), (_env("BRIEFING_SCHOOL_LEVEL") or "").strip()):
        if candidate in _BRIEFING_SCHOOL_LEVELS:
            return f"10대 학생 타겟, 학력 수준: {candidate}"
    return (
        "40대 주부 가정 기준(학년 미지정) — PART 1 독자와 같은 가정의 자녀에게, "
        "저녁 식탁에서 나눌 만한 보통 한국어 난이도로 설명 (초·중·고를 특정하지 말 것)"
    )


async def build_economy_briefing_for_students(
    topic: str, results: list[dict[str, Any]], school_level: str | None = None
) -> str:
    """규칙 기반 요약 + 뉴스 스니펫을 바탕으로 ChatGPT 통합 브리핑(엄마·학생·식탁 대화) 생성."""
    base = build_economy_briefing(topic, results)
    if base.startswith("분석할 뉴스가 없어"):
        return base

    api_key = _env("OPENAI_API_KEY").strip().strip('"').strip("'")
    if not api_key:
        return (
            base
            + "\n\n---\n\n**학생용 쉬운 설명**을 쓰려면 환경 변수 `OPENAI_API_KEY`를 설정해 주세요. "
            "(로컬: `.env`, Vercel: Environment Variables) 위 내용은 규칙 기반 요약입니다."
        )

    part2_school = _part2_school_instruction(school_level)
    news_article = _economy_news_article_block(topic, results, base)

    system_persona = (
        "너는 40대 주부에게는 **'지혜로운 자산 관리 멘토'**가 되어주고, 10대 학생에게는 "
        "**'세상 돌아가는 법을 알려주는 친한 형/누나'**가 되어주는 경제 분석가야. "
        "아래 제공되는 뉴스 기사와 요약을 읽고, 두 사람의 눈높이에 맞춰 이중 구조로 분석해줘. "
        "제공된 자료에 없는 사실을 지어내지 말 것."
    )

    user_instructions = f"""[통합 분석 프롬프트: 경제 뉴스로 잇는 우리 집]

2. 출력 포맷 지시 사항 (Output Structure) — 반드시 아래 순서·제목(이모지 포함)을 지킬 것.

[PART 1. 엄마를 위한 실속 리포트 (40대 주부 타겟)]

📍 한 줄 핵심: 이 뉴스가 우리 가계에 미치는 영향 (한 문장 요약)

🛒 장바구니/가계부 영향: 물가, 공공요금, 금리 등 실생활 지출과 관련된 변화 예측 및 대처법.

🎓 엄마의 교육 한마디: 이 뉴스를 소재로 아이에게 가르쳐줄 수 있는 경제 원리(예: 인플레이션, 환율 등)와 대화 시작 멘트.

[PART 2. 학생을 위한 뉴스 3분 컷 ({part2_school})]

🔥 이게 왜 핫해?: (10대에게 익숙한 표현·이모지를 섞어서) 이 사건이 왜 주목받는지 쉽게 설명.

🎮 용돈 체감 지수: "떡볶이 1인분 가격으로 이젠 0.8인분밖에…" 같은 **구체적인 용돈·물가 비유**를 넣을 것.

🚀 미래 내 직업은?: 이 뉴스와 관련된 미래 유망 산업이나 준비하면 좋을 능력.

[PART 3. 오늘 저녁 식탁 대화 가이드]

💬 대화 퀴즈: 엄마가 아이에게 낼 수 있는 가벼운 퀴즈 1문제 (정답 포함).

🤝 가족 미션: "이번 주말엔 다 같이 편의점 수입 과자 가격 확인해보기" 같은 소소한 행동 과제.

3. 제약 사항 (Constraints)

- 말투: 엄마 파트는 신뢰감 있고 다정한 말투로, 학생 파트는 친근하고 통통 튀는 구어체로 작성할 것.
- 금기: 지나치게 어려운 전문 용어는 반드시 일상적인 비유(학교, 게임, 쇼핑 등)로 풀어서 설명할 것.
- 길이: 전체는 스마트폰 한 화면~두 화면 정도로, 섹션별 핵심만 간결하게.
- 특정 주식·코인 매수/매도 권유, 불법·혐오 표현 금지.

4. 마지막에 반드시 한 줄 추가
이 뉴스를 바탕으로 **엄마와 아이가 웃으며 대화하는 삽화 스타일** 이미지를 만들기 위한 **영문 이미지 생성 프롬프트**를 한 줄로 적을 것. 형식: `(Image prompt: ...)` 

---

[뉴스 기사 전문·맥락: 아래 블록만 근거로 작성]

{news_article}
"""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_persona},
                {"role": "user", "content": user_instructions},
            ],
            temperature=0.45,
            max_tokens=4000,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text if text else base
    except Exception as exc:
        err = str(exc)
        hint = ""
        if "401" in err or "invalid_api_key" in err or "Incorrect API key" in err:
            hint = (
                "\n\n**조치:** OpenAI가 API 키를 거부했습니다(401). "
                "[API Keys](https://platform.openai.com/api-keys)에서 **새 비밀 키**를 만들고, "
                "로컬은 `uahanStudio/.env`의 `OPENAI_API_KEY=`, Vercel은 Settings → Environment Variables에 **그대로 붙여 넣기**만 하세요. "
                "앞뒤 공백·따옴표·잘린 문자가 없는지 확인한 뒤 서버 재시작 또는 **Redeploy** 하세요. "
                "이전에 노출된 키는 삭제하는 것이 안전합니다."
            )
        return (
            base
            + f"\n\n---\n\n**(학생용 설명 자동 생성에 실패했습니다)**\n{err}{hint}\n\n위는 규칙 기반 브리핑 원문입니다."
        )


def _economy_chip_strings(raw: Any, *, max_items: int = 10, max_chars: int = 15) -> list[str]:
    out: list[str] = []
    if not isinstance(raw, list):
        return []
    for x in raw:
        s = str(x).strip()
        if not s:
            continue
        if len(s) > max_chars:
            s = s[:max_chars].rstrip()
        out.append(s)
        if len(out) >= max_items:
            break
    return out


def _parse_llm_json_object(text: str) -> dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```\s*$", "", t)
    try:
        out = json.loads(t)
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", t)
        if m:
            try:
                out = json.loads(m.group(0))
                return out if isinstance(out, dict) else {}
            except json.JSONDecodeError:
                pass
        return {}


async def extract_economy_keyword_chips_from_news(
    results: list[dict[str, Any]],
    *,
    diversity_seed: int | None = None,
) -> dict[str, Any]:
    """뉴스 목록 기반 맘·학생·공통 토픽 키워드 칩(JSON)."""
    empty: dict[str, Any] = {
        "Mom_Keywords": [],
        "Student_Keywords": [],
        "Common_Topic": "",
        "ok": False,
        "message": "",
        "source": "news",
    }
    if not results:
        return {**empty, "message": "뉴스 결과가 없습니다."}

    api_key = _env("OPENAI_API_KEY").strip().strip('"').strip("'")
    if not api_key:
        return {**empty, "message": "OPENAI_API_KEY가 필요합니다."}

    lines: list[str] = []
    for i, row in enumerate(results[:10], 1):
        title = (row.get("title") or "").strip()
        desc = (row.get("description") or "").strip().replace("\n", " ")
        lines.append(f"{i}. {title[:180]}\n   요약: {desc[:380]}")
    news_blob = "\n".join(lines)

    seed_block = ""
    if diversity_seed is not None:
        seed_block = (
            f"\n다양성 시드: {diversity_seed} — 정치·사회·문화·기술·생활소비 등 서로 다른 관점 중 "
            "하나를 골라, 그 관점이 살짝 드러나도록 칩 톤을 바꿔 줄 것.\n"
        )

    system_persona = (
        "너는 뉴스 기사에서 핵심 정보를 파악해 사용자의 관심을 끄는 **'클릭 유도형 키워드(Click-bait Keywords)'**를 만드는 "
        "마케팅 전문가이자 경제 분석가야. 특히 40대 주부와 10대 학생이 각각 무엇에 반응하는지 정확히 알고 있어. "
        "출력은 요청한 JSON 객체 하나만. 다른 설명·마크다운 금지."
    )

    user_prompt = f"""다음 뉴스 기사를 분석하여 아래 키 이름을 정확히 지킨 JSON만 출력해줘.

{{
  "Mom_Keywords": ["문구1", "문구2", "문구3", "문구4", "문구5", "문구6", "문구7", "문구8", "문구9", "문구10"],
  "Student_Keywords": ["문구1", "문구2", "문구3", "문구4", "문구5", "문구6", "문구7", "문구8", "문구9", "문구10"],
  "Common_Topic": "핵심 경제 용어 한 단어 또는 짧은 구"
}}

규칙:
- Mom_Keywords (40대 주부 타겟): 뉴스 맥락에 맞춰 **실속형** 클릭 문구 정확히 **10개**. 반드시 아래 축을 골고루 반영할 것 — **자녀 교육**, **경제·가계 현황**, **다이어트**, **인간관계**, **긍정적 마인드**, **부동산/주식/재테크**(직접 연결 가능한 것 위주). #태그 형식 권장.
- Student_Keywords (10대 학생 타겟): 뉴스 맥락에 맞춰 **트렌디한** 문구 정확히 **10개**. 아래 축과 연결할 것 — **역사**, **경제**, **시장**, **용돈**, **유행 브랜드**, **게임/IT**, **미래 직업**. #태그 형식 권장.
- Common_Topic: 기사의 가장 핵심적인 경제 용어 1개(짧게).
- 각 칩은 공백 포함 15자 이내, 짧고 강렬하게.
{seed_block}
[뉴스 기사]
{news_blob}
"""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_persona},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.78,
            max_tokens=1400,
            response_format={"type": "json_object"},
        )
        raw_text = (completion.choices[0].message.content or "").strip()
        data = _parse_llm_json_object(raw_text)
        mom = _economy_chip_strings(data.get("Mom_Keywords"))
        stu = _economy_chip_strings(data.get("Student_Keywords"))
        ct = data.get("Common_Topic")
        common_s = str(ct).strip()[:20] if ct is not None else ""
        if len(mom) < 1 and len(stu) < 1 and not common_s:
            return {**empty, "message": "키워드 JSON 파싱에 실패했습니다."}
        return {
            "Mom_Keywords": mom,
            "Student_Keywords": stu,
            "Common_Topic": common_s,
            "ok": True,
            "message": "",
            "source": "news",
        }
    except Exception as exc:
        return {**empty, "message": str(exc)[:500]}


async def extract_economy_keyword_chips_trending(
    *,
    hint: str | None = None,
    diversity_seed: int | None = None,
) -> dict[str, Any]:
    """뉴스 없이 GPT만으로 맘·학생·공통 키워드 칩 제안(검색 전용)."""
    empty: dict[str, Any] = {
        "Mom_Keywords": [],
        "Student_Keywords": [],
        "Common_Topic": "",
        "ok": False,
        "message": "",
        "source": "trending",
    }
    api_key = _env("OPENAI_API_KEY").strip().strip('"').strip("'")
    if not api_key:
        return {**empty, "message": "OPENAI_API_KEY가 필요합니다."}

    hint_block = ""
    h = (hint or "").strip()
    if h:
        hint_block = f"\n사용자 힌트(반드시 반영): 「{h[:140]}」\n"

    seed_block = ""
    if diversity_seed is not None:
        seed_block = (
            f"\n다양성 시드: {diversity_seed} — 정치·사회·문화·기술·생활소비·글로벌 중 "
            "서로 다른 관점 하나를 골라 칩 톤을 바꿀 것.\n"
        )

    system_persona = (
        "너는 뉴스 기사에서 핵심 정보를 파악해 사용자의 관심을 끄는 **'클릭 유도형 키워드(Click-bait Keywords)'**를 만드는 "
        "마케팅 전문가이자 경제 분석가야. 특히 40대 주부와 10대 학생이 각각 무엇에 반응하는지 정확히 알고 있어. "
        "출력은 요청한 JSON 객체 하나만. 다른 설명·마크다운 금지."
    )

    user_prompt = f"""실제 뉴스 본문은 주어지지 않는다. 최근 한국 경제·사회 화제를 가정해, 네이버 뉴스 검색에 쓸 만한 클릭 유도형 키워드 칩 JSON만 출력해줘.

키 이름(정확히):
{{
  "Mom_Keywords": ["문구1", "문구2", "문구3", "문구4", "문구5", "문구6", "문구7", "문구8", "문구9", "문구10"],
  "Student_Keywords": ["문구1", "문구2", "문구3", "문구4", "문구5", "문구6", "문구7", "문구8", "문구9", "문구10"],
  "Common_Topic": "핵심 경제 용어 한 단어 또는 짧은 구"
}}

규칙:
- Mom_Keywords (40대 주부 타겟): 힌트·최근 화제 맥락에 맞춰 **실속형** 문구 정확히 **10개** — **자녀 교육**, **경제·가계 현황**, **다이어트**, **인간관계**, **긍정적 마인드**, **부동산/주식/재테크** 축을 활용. #태그 형식 권장.
- Student_Keywords (10대 학생 타겟): **트렌디한** 문구 정확히 **10개** — **역사**, **경제**, **시장**, **용돈**, **유행 브랜드**, **게임/IT**, **미래 직업**과 연결. #태그 형식 권장.
- Common_Topic: 지금 이슈로 그럴듯한 핵심 경제 용어 1개.
- 각 칩 공백 포함 15자 이내.
{hint_block}
{seed_block}
"""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_persona},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.82,
            max_tokens=1400,
            response_format={"type": "json_object"},
        )
        raw_text = (completion.choices[0].message.content or "").strip()
        data = _parse_llm_json_object(raw_text)
        mom = _economy_chip_strings(data.get("Mom_Keywords"))
        stu = _economy_chip_strings(data.get("Student_Keywords"))
        ct = data.get("Common_Topic")
        common_s = str(ct).strip()[:20] if ct is not None else ""
        if len(mom) < 1 and len(stu) < 1 and not common_s:
            return {**empty, "message": "키워드 JSON 파싱에 실패했습니다."}
        return {
            "Mom_Keywords": mom,
            "Student_Keywords": stu,
            "Common_Topic": common_s,
            "ok": True,
            "message": "",
            "source": "trending",
        }
    except Exception as exc:
        return {**empty, "message": str(exc)[:500]}


def _wind_feel_desc(speed_mps: float) -> str:
    if speed_mps < 2:
        return "거의 바람이 느껴지지 않아요."
    if speed_mps < 5:
        return "산들바람 수준으로 가볍게 느껴져요."
    if speed_mps < 9:
        return "우산/머리카락이 눈에 띄게 흔들리는 정도예요."
    if speed_mps < 14:
        return "걷는 동안 바람 저항이 분명하게 느껴져요."
    return "강한 바람으로 체감이 크게 떨어질 수 있어요."


def _rain_feel_desc(precip_mm: float) -> str:
    if precip_mm <= 0:
        return "비 예보가 거의 없는 상태예요."
    if precip_mm < 1:
        return "이슬비 수준으로 우산 없이도 버틸 수 있는 경우가 많아요."
    if precip_mm < 5:
        return "약한 비로, 이동 시 작은 우산이 있으면 충분해요."
    if precip_mm < 15:
        return "중간 강도의 비로, 야외 활동이 불편해질 수 있어요."
    return "강한 비 수준이라 외출 시 방수 대비가 꼭 필요해요."


def _weather_icon(condition: str, is_day: bool = True) -> str:
    text = (condition or "").lower()
    if any(k in text for k in ["thunder", "뇌우"]):
        return "⛈️"
    if any(k in text for k in ["snow", "눈", "sleet"]):
        return "🌨️"
    if any(k in text for k in ["rain", "비", "drizzle", "shower"]):
        return "🌧️"
    if any(k in text for k in ["fog", "mist", "안개", "haze"]):
        return "🌫️"
    if any(k in text for k in ["cloud", "흐림", "구름"]):
        return "⛅" if is_day else "☁️"
    if any(k in text for k in ["sun", "clear", "맑"]):
        return "☀️" if is_day else "🌙"
    return "🌤️"


def _to_local_time_label(iso_time: str) -> str:
    try:
        # open-meteo hourly.time 형식: YYYY-MM-DDTHH:MM
        dt = datetime.strptime(iso_time, "%Y-%m-%dT%H:%M")
        return dt.strftime("%H:%M")
    except Exception:
        return iso_time


# Open-Meteo Geocoding은 한글 단독 검색(예: name=서울)에서 results가 비는 경우가 많음 → 영문 검색으로 폴백
_KOREAN_REGION_ENGLISH: dict[str, str] = {
    "서울": "Seoul",
    "서울시": "Seoul",
    "서울특별시": "Seoul",
    "부산": "Busan",
    "부산광역시": "Busan",
    "대구": "Daegu",
    "대구광역시": "Daegu",
    "인천": "Incheon",
    "인천광역시": "Incheon",
    "광주": "Gwangju",
    "광주광역시": "Gwangju",
    "대전": "Daejeon",
    "대전광역시": "Daejeon",
    "울산": "Ulsan",
    "울산광역시": "Ulsan",
    "세종": "Sejong",
    "세종시": "Sejong",
    "세종특별자치시": "Sejong",
    "수원": "Suwon",
    "수원시": "Suwon",
    "성남": "Seongnam",
    "성남시": "Seongnam",
    "고양": "Goyang",
    "고양시": "Goyang",
    "용인": "Yongin",
    "용인시": "Yongin",
    "제주": "Jeju City",
    "제주시": "Jeju City",
    "제주도": "Jeju City",
    "제주특별자치도": "Jeju City",
    "강릉": "Gangneung",
    "강릉시": "Gangneung",
    "춘천": "Chuncheon",
    "춘천시": "Chuncheon",
    "전주": "Jeonju",
    "전주시": "Jeonju",
    "청주": "Cheongju",
    "청주시": "Cheongju",
    "천안": "Cheonan",
    "천안시": "Cheonan",
    "포항": "Pohang",
    "포항시": "Pohang",
    "창원": "Changwon",
    "창원시": "Changwon",
    "김해": "Gimhae",
    "김해시": "Gimhae",
    "평택": "Pyeongtaek",
    "평택시": "Pyeongtaek",
    "의정부": "Uijeongbu",
    "의정부시": "Uijeongbu",
    "시흥": "Siheung",
    "시흥시": "Siheung",
    "파주": "Paju",
    "파주시": "Paju",
}


def _korean_region_english_fallback(query: str) -> str | None:
    q = (query or "").strip()
    if not q:
        return None
    compact = q.replace(" ", "")
    return _KOREAN_REGION_ENGLISH.get(q) or _KOREAN_REGION_ENGLISH.get(compact)


def _rows_to_geocode_out(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        admin_bits = [row.get("admin1"), row.get("admin2"), row.get("country")]
        admin_label = ", ".join([x for x in admin_bits if x])
        out.append(
            {
                "name": row.get("name", ""),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "timezone": row.get("timezone", "Asia/Seoul"),
                "country": row.get("country", ""),
                "admin": admin_label,
            }
        )
    return out


async def _geocode_open_meteo_raw(
    name: str, *, count: int, language: str, country_code: str | None = None
) -> list[dict[str, Any]]:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params: dict[str, Any] = {"name": name, "count": count, "language": language, "format": "json"}
    if country_code:
        params["countryCode"] = country_code
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    return payload.get("results", []) or []


async def geocode_city(query: str, count: int = 8) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []

    for lang in ("ko", "en"):
        rows = await _geocode_open_meteo_raw(q, count=count, language=lang)
        if rows:
            return _rows_to_geocode_out(rows)[:count]

    en_name = _korean_region_english_fallback(q)
    if en_name:
        for lang in ("en", "ko"):
            rows = await _geocode_open_meteo_raw(en_name, count=count, language=lang, country_code="KR")
            if rows:
                return _rows_to_geocode_out(rows)[:count]
            rows = await _geocode_open_meteo_raw(en_name, count=count, language=lang)
            if rows:
                return _rows_to_geocode_out(rows)[:count]

    return []


async def fetch_weather_now(latitude: float, longitude: float, timezone: str = "Asia/Seoul") -> dict[str, Any]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation,rain,showers,snowfall",
        "hourly": "weather_code,temperature_2m,wind_speed_10m,precipitation_probability",
        "forecast_days": 2,
    }
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()

    current = payload.get("current", {})
    hourly = payload.get("hourly", {})
    now_time = current.get("time", "")
    current_hour = now_time[11:13] if len(now_time) >= 13 else "12"
    is_day = 7 <= int(current_hour) <= 18 if current_hour.isdigit() else True

    weather_code = str(current.get("weather_code", ""))
    weather_map = {
        "0": "맑음",
        "1": "대체로 맑음",
        "2": "부분적으로 흐림",
        "3": "흐림",
        "45": "안개",
        "48": "짙은 안개",
        "51": "약한 이슬비",
        "53": "이슬비",
        "55": "강한 이슬비",
        "61": "약한 비",
        "63": "비",
        "65": "강한 비",
        "71": "약한 눈",
        "73": "눈",
        "75": "강한 눈",
        "80": "소나기",
        "81": "강한 소나기",
        "82": "매우 강한 소나기",
        "95": "뇌우",
    }
    condition = weather_map.get(weather_code, f"코드 {weather_code}")

    wind_speed = float(current.get("wind_speed_10m", 0.0) or 0.0)
    precipitation = float(current.get("precipitation", 0.0) or 0.0)
    rain = float(current.get("rain", 0.0) or 0.0)
    showers = float(current.get("showers", 0.0) or 0.0)
    snowfall = float(current.get("snowfall", 0.0) or 0.0)

    timeline: list[dict[str, Any]] = []
    times = hourly.get("time", []) or []
    t2m = hourly.get("temperature_2m", []) or []
    w10 = hourly.get("wind_speed_10m", []) or []
    pprob = hourly.get("precipitation_probability", []) or []
    wcode = hourly.get("weather_code", []) or []

    # 현재 시각에 가장 가까운 시각(이전 정시 슬롯)부터 이후 24시간
    start_idx = 0
    if now_time and times:
        for i, t in enumerate(times):
            if isinstance(t, str) and t <= now_time:
                start_idx = i
            else:
                break
    end_idx = min(start_idx + 24, len(times))
    for idx in range(start_idx, end_idx):
        code = str(wcode[idx]) if idx < len(wcode) else "0"
        cond = weather_map.get(code, f"코드 {code}")
        hour = times[idx]
        hour_int = int(hour[11:13]) if isinstance(hour, str) and len(hour) >= 13 and hour[11:13].isdigit() else 12
        slot_day = 7 <= hour_int <= 18
        timeline.append(
            {
                "time": _to_local_time_label(hour),
                "temperature_c": t2m[idx] if idx < len(t2m) else None,
                "wind_mps": w10[idx] if idx < len(w10) else None,
                "precip_probability": pprob[idx] if idx < len(pprob) else None,
                "condition": cond,
                "icon": _weather_icon(cond, is_day=slot_day),
            }
        )

    return {
        "current": {
            "time": now_time,
            "condition": condition,
            "icon": _weather_icon(condition, is_day=is_day),
            "temperature_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "wind_mps": wind_speed,
            "wind_feel": _wind_feel_desc(wind_speed),
            "precipitation_mm": precipitation,
            "rain_mm": rain,
            "showers_mm": showers,
            "snowfall_cm": snowfall,
            "rain_feel": _rain_feel_desc(precipitation),
        },
        "timeline": timeline,
    }


async def fetch_air_quality_snapshot(
    latitude: float, longitude: float, timezone: str = "Asia/Seoul"
) -> dict[str, Any]:
    """Open-Meteo 대기질 API — PM2.5·PM10·UV (모델값, 참고용). 실패 시 빈 dict."""
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "hourly": "pm2_5,pm10,uv_index",
        "forecast_days": 2,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return {}

    hourly = payload.get("hourly") or {}
    times: list[str] = list(hourly.get("time") or [])
    if not times:
        return {}

    pm25 = list(hourly.get("pm2_5") or [])
    pm10 = list(hourly.get("pm10") or [])
    uv = list(hourly.get("uv_index") or [])

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    best_i = 0
    best_sec: float | None = None
    for i, t in enumerate(times):
        if not isinstance(t, str) or len(t) < 16:
            continue
        try:
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            sec = abs((dt - now).total_seconds())
            if best_sec is None or sec < best_sec:
                best_sec = sec
                best_i = i
        except Exception:
            continue

    def _at(arr: list[Any], idx: int) -> float | None:
        if idx < len(arr) and arr[idx] is not None:
            try:
                return float(arr[idx])
            except (TypeError, ValueError):
                return None
        return None

    out: dict[str, Any] = {}
    p25 = _at(pm25, best_i)
    p10 = _at(pm10, best_i)
    uvi = _at(uv, best_i)
    if p25 is not None:
        out["pm2_5_ugm3"] = p25
    if p10 is not None:
        out["pm10_ugm3"] = p10
    if uvi is not None:
        out["uv_index"] = uvi
    if best_i < len(times):
        out["reference_time"] = times[best_i]
    return out


def _weather_timeline_aggregate(timeline: list[dict[str, Any]]) -> str:
    if not timeline:
        return "향후 24시간 타임라인 없음"
    temps: list[float] = []
    prob_slots: list[tuple[float, str]] = []
    for slot in timeline:
        tc = slot.get("temperature_c")
        if tc is not None:
            try:
                temps.append(float(tc))
            except (TypeError, ValueError):
                pass
        pr = slot.get("precip_probability")
        if pr is not None:
            try:
                prob_slots.append((float(pr), str(slot.get("time", ""))))
            except (TypeError, ValueError):
                pass
    parts: list[str] = []
    if temps:
        parts.append(f"예보 구간 기온 약 {min(temps):.0f}°C ~ {max(temps):.0f}°C")
    if prob_slots:
        mx = max(prob_slots, key=lambda x: x[0])
        parts.append(f"강수확률 최대 약 {mx[0]:.0f}% ({mx[1]})")
    return " · ".join(parts) if parts else "집계 없음"


def _weather_timeline_sample_lines(timeline: list[dict[str, Any]], max_slots: int = 5) -> str:
    if not timeline:
        return "(슬롯 없음)"
    n = len(timeline)
    if n <= max_slots:
        picks = timeline
    else:
        step = max(1, n // max_slots)
        picks = [timeline[i] for i in range(0, n, step)][:max_slots]
    lines = []
    for p in picks:
        lines.append(
            f"  - {p.get('time')}: {p.get('condition')} · {p.get('temperature_c')}°C · "
            f"바람 {p.get('wind_mps')} m/s · 강수확률 {p.get('precip_probability')}%"
        )
    return "\n".join(lines)


def _weather_regions_llm_context_block(successful: list[dict[str, Any]], now_label: str) -> str:
    chunks: list[str] = [f"기준 시각(서버): {now_label}", ""]
    for row in successful:
        loc = row["location"]
        w = row["weather"]
        cur = w["current"]
        tl = w.get("timeline") or []
        air = w.get("air_quality") or {}
        name = loc.get("name") or row.get("region_query") or "지역"
        admin = (loc.get("admin") or "").strip()
        country = (loc.get("country") or "").strip()
        loc_line = f"{name}" + (f" ({admin})" if admin else "") + (f", {country}" if country else "")

        air_bits: list[str] = []
        if air.get("pm2_5_ugm3") is not None:
            air_bits.append(f"PM2.5 약 {air['pm2_5_ugm3']:.1f} ㎍/㎥ (모델)")
        if air.get("pm10_ugm3") is not None:
            air_bits.append(f"PM10 약 {air['pm10_ugm3']:.1f} ㎍/㎥ (모델)")
        if air.get("uv_index") is not None:
            air_bits.append(f"자외선 지수(UV) 약 {air['uv_index']:.1f}")
        air_line = " / ".join(air_bits) if air_bits else "미세먼지·UV: API 데이터 없음(해당 항목은 수치 없이 안내만)"

        chunks.append(f"[{loc_line}] 검색어: {row.get('region_query')}")
        chunks.append(
            f"- 현재: {cur.get('icon', '')} {cur.get('condition')} · 기온 {cur.get('temperature_c')}°C "
            f"(체감 {cur.get('feels_like_c')}°C) · 관측시각 {cur.get('time', '')}"
        )
        chunks.append(
            f"- 바람: {cur.get('wind_mps')} m/s ({cur.get('wind_feel')}) · "
            f"강수 강도 mm/h: 총 {cur.get('precipitation_mm')} (비 {cur.get('rain_mm')}, 소나기 {cur.get('showers_mm')}, 눈cm {cur.get('snowfall_cm')}) — {cur.get('rain_feel')}"
        )
        chunks.append(f"- 24시간 예보 요약: {_weather_timeline_aggregate(tl)}")
        chunks.append(f"- 대기·자외선: {air_line}")
        chunks.append("- 시간대 샘플:")
        chunks.append(_weather_timeline_sample_lines(tl))
        chunks.append("")
    return "\n".join(chunks).strip()


async def _build_weather_morning_alert_briefing_llm(context_block: str) -> str:
    """통합 날씨 브리핑: 우리 집 아침 알림이 (GPT). 실패 시 빈 문자열."""
    api_key = _env("OPENAI_API_KEY").strip().strip('"').strip("'")
    if not api_key:
        return ""

    system_persona = (
        "너는 기상 캐스터이면서 동시에 **'꼼꼼한 살림꾼'**이자 **'트렌디한 스타일리스트'**야. "
        "오늘 날씨 정보를 바탕으로 40대 주부와 10대 학생에게 꼭 필요한 맞춤형 가이드를 제공해줘. "
        "아래 [지역별 날씨 원시 데이터]에 없는 기온·강수·미세먼지·자외선 수치를 지어내지 말 것. "
        "미세먼지·UV가 없다고 적혀 있으면 수치를 만들지 말고, 앱·기상청 확인을 권하는 짧은 문장으로 처리할 것."
    )

    user_instructions = f"""[통합 날씨 브리핑: 우리 집 아침 알림이]

2. 출력 포맷 지시 사항 (Output Structure) — 반드시 아래 순서·이모지·소제목을 지킬 것.

[PART 1. 오늘의 날씨 요약]

🌡️ 기온 및 하늘: 현재·최고·최저(데이터에 있으면) 기온과 하늘 상태를 한국어로 생동감 있게 (예: "맑음 뒤 비☔" 느낌으로 가능).

😷 미세먼지/지수: 원시 데이터의 PM2.5·PM10·UV가 있으면 짧게 해석하고, 없으면 "오늘은 미세먼지 앱에서 한 번 확인해요" 수준으로만.

[PART 2. 엄마를 위한 '오늘의 살림 캐스터']

🧺 세탁 및 환기: "오늘은 빨래가 잘 말라요!", "환기는 오후 ○시쯤이 나을 수 있어요" 같이 실속 팁 (날씨·바람·비와 모순 없게).

🥘 오늘 저녁 메뉴 추천: 날씨에 어울리는 음식 (예: 비 오는 날 부침개, 미세먼지 심할 땐 국물 요리 등 — 데이터와 맞게).

👜 외출 준비물: 우산, 마스크, 가벼운 겉옷 등.

[PART 3. 학생을 위한 '오늘의 등교 룩 & 팁']

👕 등교 코디 추천: 10대 유행 스타일을 반영해 유쾌하게 (예: 반팔+바람막이, 비 올 땐 레인부츠 등, 기온·강수에 맞게).

🍱 매점/간식 추천: 날씨에 따라 생각날 만한 간식.

⛹️ 점심시간 활동: 운동장·실내 등 (비·바람·미세먼지 반영).

[PART 4. 가족을 위한 '오늘의 한 줄 덕담']

💖 따뜻한 응원: 한두 문장.

3. 제약 사항 (Constraints)
- 어조: 엄마에게는 상냥하고 정보 중심, 학생에게는 티키타카 가능한 유쾌하고 친근한 말투.
- 비유: 단순히 "기온이 낮다"만 쓰지 말고 "어제보다 붕어빵이 더 생각날 정도로 추워요" 같은 생동감 있는 표현을 섞을 것.
- 길이: 바쁜 아침에 빠르게 읽도록 각 소항목당 1~2문장.
- 지역이 여러 개면 지역명을 밝혀 [서울] [부산] 식으로 나누거나 한 페이지에서 자연스럽게 모두 언급할 것.

---
[지역별 날씨 원시 데이터 — 이 블록만 근거로 작성]
{context_block}
"""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        completion = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_persona},
                {"role": "user", "content": user_instructions},
            ],
            temperature=0.48,
            max_tokens=3800,
        )
        text = (completion.choices[0].message.content or "").strip()
        return text
    except Exception:
        return ""


async def collect_weather_region_items(
    regions: list[str], *, include_air_quality: bool = False
) -> list[dict[str, Any]]:
    """지역별 지오코딩 + 날씨(·선택 대기질). 검색 전용은 대기질 생략으로 지연을 줄임."""
    cleaned = [r.strip() for r in regions if r and r.strip()]
    if not cleaned:
        raise ValueError("조회할 지역명이 비어 있습니다.")

    items: list[dict[str, Any]] = []
    for query in cleaned:
        cands = await geocode_city(query, count=1)
        if not cands:
            items.append(
                {
                    "region_query": query,
                    "ok": False,
                    "error": "지역을 찾지 못했습니다.",
                }
            )
            continue
        loc = cands[0]
        tz = loc.get("timezone", "Asia/Seoul")
        weather = await fetch_weather_now(loc["latitude"], loc["longitude"], tz)
        if include_air_quality:
            weather["air_quality"] = await fetch_air_quality_snapshot(
                loc["latitude"], loc["longitude"], tz
            )
        else:
            weather["air_quality"] = {}
        items.append(
            {
                "region_query": query,
                "ok": True,
                "location": loc,
                "weather": weather,
            }
        )
    return items


async def fetch_weather_items_for_regions(regions: list[str]) -> dict[str, Any]:
    """실시간 검색용: LLM·대기질 API 없이 카드 데이터만."""
    items = await collect_weather_region_items(regions, include_air_quality=False)
    return {"items": items}


async def build_weather_briefing_for_regions(regions: list[str]) -> dict[str, Any]:
    items = await collect_weather_region_items(regions, include_air_quality=True)

    successful = [x for x in items if x.get("ok")]
    if not successful:
        return {"items": items, "briefing": "조회 가능한 지역이 없어 날씨 브리핑을 만들지 못했습니다."}

    lines = ["### 날씨 데일리 브리핑 (요약)", ""]
    for row in successful:
        loc = row["location"]
        cur = row["weather"]["current"]
        air = row["weather"].get("air_quality") or {}
        air_hint = ""
        if air.get("pm2_5_ugm3") is not None:
            air_hint += f" · PM2.5≈{air['pm2_5_ugm3']:.0f}"
        if air.get("uv_index") is not None:
            air_hint += f" · UV≈{air['uv_index']:.1f}"
        lines.append(
            f"- **{loc.get('name')}** {cur.get('icon')} {cur.get('condition')} · "
            f"{cur.get('temperature_c')}°C (체감 {cur.get('feels_like_c')}°C){air_hint}"
        )
        lines.append(
            f"  - 바람: {cur.get('wind_mps')} m/s — {cur.get('wind_feel')}"
        )
        lines.append(
            f"  - 강수: {cur.get('precipitation_mm')} mm/h "
            f"(비 {cur.get('rain_mm')} · 소나기 {cur.get('showers_mm')} · 눈 {cur.get('snowfall_cm')}) — {cur.get('rain_feel')}"
        )

    base_md = "\n".join(lines)
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    ctx = _weather_regions_llm_context_block(successful, now_label)
    llm_text = await _build_weather_morning_alert_briefing_llm(ctx)
    api_key = _env("OPENAI_API_KEY").strip().strip('"').strip("'")

    if llm_text:
        briefing = llm_text
    elif not api_key:
        briefing = (
            base_md
            + "\n\n---\n\n**통합 아침 브리핑**(PART 1~4: 날씨 요약·살림 캐스터·등교 룩·덕담)은 "
            "`OPENAI_API_KEY`를 설정하면 GPT로 생성됩니다. 위는 관측·예보·대기질(모델) 요약입니다."
        )
    else:
        briefing = (
            base_md
            + "\n\n---\n\n**(맞춤 아침 브리핑 생성에 실패했습니다.)** 잠시 후 다시 시도하세요. 위는 관측·예보 요약입니다."
        )

    return {"items": items, "briefing": briefing}


def extract_keywords(text: str, top_k: int = 6) -> list[str]:
    tokens = re.findall(r"[가-힣A-Za-z0-9]{2,}", text.lower())
    filtered = [t for t in tokens if t not in KOREAN_STOPWORDS and not t.isdigit()]
    return [word for word, _ in Counter(filtered).most_common(top_k)]


def short_summary(text: str, max_len: int = 260) -> str:
    sentences = re.split(r"(?<=[.!?다])\s+", text)
    summary = " ".join(sentences[:3]).strip()
    if len(summary) <= max_len:
        return summary
    return summary[:max_len].rstrip() + "..."


def build_local_benchmark_insights(refs: list[dict[str, Any]]) -> dict[str, Any]:
    keyword_counter: Counter[str] = Counter()
    summary_corpus: list[str] = []
    for ref in refs:
        keyword_counter.update(ref.get("keywords", []))
        summary_corpus.append(ref.get("summary", ""))

    top_keywords = [k for k, _ in keyword_counter.most_common(12)]
    corpus = " ".join(summary_corpus)
    audience_pain_points = extract_keywords(corpus, 8)
    return {
        "top_keywords": top_keywords,
        "pain_points": audience_pain_points,
        "summaries": summary_corpus,
    }


def _pick_ref_insight_lines(refs: list[dict[str, Any]], limit: int = 5) -> list[str]:
    lines: list[str] = []
    for ref in refs[:limit]:
        title = ref.get("title", "제목 없음")
        keywords = ", ".join(ref.get("keywords", [])[:4]) or "핵심 키워드 없음"
        summary = short_summary(ref.get("summary", ""), max_len=140)
        lines.append(f"- {title}: ({keywords}) {summary}")
    return lines


def _build_action_points_from_refs(refs: list[dict[str, Any]]) -> list[str]:
    corpus = " ".join([ref.get("summary", "") for ref in refs])
    tokens = extract_keywords(corpus, top_k=18)
    action_map = {
        "제목": "제목에서 문제 상황 + 결과 약속을 동시에 제시한다.",
        "후기": "경험담은 결과 수치나 변화 전/후 비교와 함께 제시한다.",
        "추천": "추천 포인트는 대상(초보/직장인/가족 등)을 명확히 구분한다.",
        "방법": "방법 설명은 단계별 체크리스트로 끝맺어 바로 실행하게 만든다.",
        "정리": "각 섹션 끝에 핵심 한 줄 정리를 추가해 스크롤 이탈을 줄인다.",
        "비용": "비용/시간 정보는 표 또는 불릿으로 시각적으로 빠르게 전달한다.",
        "준비": "준비물/사전조건은 본문 초반에 배치해 실패 가능성을 낮춘다.",
    }
    selected: list[str] = []
    for token in tokens:
        for key, text in action_map.items():
            if key in token and text not in selected:
                selected.append(text)
        if len(selected) >= 4:
            break
    if len(selected) < 4:
        selected.extend(
            [
                "도입 3문장 안에 독자의 문제, 원인, 기대 결과를 순서대로 배치한다.",
                "소제목마다 '왜 중요한가' 한 문장을 넣어 맥락을 분명히 한다.",
                "설명만 하지 말고 복붙 가능한 예시 문장을 최소 2개 제공한다.",
                "마지막 문단은 요약 대신 오늘 당장 할 액션 3개를 제시한다.",
            ]
        )
    return selected[:4]


def generate_local_creative_article(topic: str, refs: list[dict[str, Any]], tone: str) -> str:
    insights = build_local_benchmark_insights(refs)
    top_keywords = insights["top_keywords"][:8]
    pain_points = insights["pain_points"][:6]
    ref_lines = _pick_ref_insight_lines(refs, limit=5)
    action_points = _build_action_points_from_refs(refs)

    if tone == "전문가톤":
        title_hooks = [
            f"{topic}, 남들보다 먼저 성과 내는 실전 설계법",
            f"{topic} 글쓰기: 클릭을 부르는 구조를 만드는 7단계",
            f"{topic} 콘텐츠, 오늘부터 반응이 달라지는 이유",
        ]
        opening_angles = [
            "대부분의 글은 정보는 많지만 독자가 움직일 이유를 주지 못합니다.",
            "검색은 잘 되는데 체류 시간이 짧다면, 글의 전개 순서가 문제일 가능성이 큽니다.",
            "좋은 주제를 잡아도 '첫 10초'를 놓치면 클릭 이후 이탈이 빠르게 일어납니다.",
        ]
    elif tone == "친근톤":
        title_hooks = [
            f"{topic}, 어렵지 않게 시작하는 현실적인 글쓰기 루틴",
            f"{topic} 글, 오늘 바로 써보는 반응형 포맷",
            f"{topic} 처음이라면 이렇게만 써도 충분합니다",
        ]
        opening_angles = [
            "괜히 어렵게 느껴져서 시작을 미루고 있었다면, 오늘은 다르게 가볼게요.",
            "정보는 넘치는데 막상 글로 옮기기 어려운 순간이 있죠.",
            "완벽하게 쓰려고 하기보다, 읽히는 구조부터 잡으면 훨씬 쉬워집니다.",
        ]
    else:
        title_hooks = [
            f"[브랜드 인사이트] {topic}를 콘텐츠 자산으로 바꾸는 방법",
            f"{topic} 콘텐츠 전략: 신뢰와 전환을 함께 만드는 설계",
            f"{topic}, 우리만의 관점으로 재해석하는 실전 프레임",
        ]
        opening_angles = [
            "브랜드 콘텐츠의 핵심은 정보 전달이 아니라 관점의 일관성입니다.",
            "같은 주제라도 브랜드 언어로 재해석해야 기억에 남습니다.",
            "단발성 조회수보다 반복 방문을 만드는 구조가 더 중요합니다.",
        ]

    selected_title = random.choice(title_hooks)
    opening = random.choice(opening_angles)

    keyword_line = ", ".join(top_keywords) if top_keywords else topic
    pain_line = ", ".join(pain_points[:4]) if pain_points else "정보 과부하, 실행 난이도"
    ref_evidence_block = "\n".join(ref_lines) if ref_lines else "- 분석 가능한 참고 글이 부족했습니다."
    action_block = "\n".join([f"{idx}. {pt}" for idx, pt in enumerate(action_points, start=1)])

    return f"""# {selected_title}

{opening}
{topic}에 대해 여러 글을 읽다 보면, 이상하게 마음만 더 복잡해지는 순간이 있습니다.  
정보는 분명 넘치는데, 정작 내가 지금 무엇부터 결정해야 하는지는 흐릿해지는 때 말입니다.  
이번 글은 그런 막막함을 줄이기 위해, 실제 상위 글에서 반복된 결을 따라 하나의 서사로 다시 엮었습니다.

먼저 눈에 들어온 단어들은 이렇습니다. **{keyword_line}**.  
그리고 사람들이 자주 멈춰 서는 지점은 대체로 **{pain_line}** 근처였습니다.  
중요한 건 정답을 더 많이 아는 것이 아니라, 내 상황에 맞는 기준을 먼저 세우는 일이었습니다.

## 참고 글에서 건져 올린 장면들
{ref_evidence_block}

위 문장들을 가만히 읽어보면 공통된 리듬이 있습니다.  
누군가는 풍경을 먼저 이야기했고, 누군가는 동선과 시간을 먼저 계산했습니다.  
하지만 결국 좋은 글은 하나의 질문으로 모였습니다.  
**"지금 이 선택이 내 하루를 어떻게 바꾸는가?"**

[IMAGE_PLACEHOLDER_1]

## {topic}을 제대로 즐기기 위한 현실적인 순서
처음에는 거창한 계획보다, 하루를 망치지 않을 최소한의 기준을 정하는 편이 좋았습니다.  
예를 들면 이동 시간의 상한, 한 번에 소화할 장소의 개수, 그리고 꼭 보고 싶은 장면 한 가지.  
이 세 가지가 정해지면 선택은 오히려 쉬워집니다.

상위 글의 문장들이 좋았던 이유도 여기에 있었습니다.  
단순히 "어디가 좋다"가 아니라, 왜 지금 이 선택이 덜 피곤하고 더 만족스러운지 설명해줬기 때문입니다.  
사람들은 정보보다 맥락을 기억합니다.  
그래서 추천 목록보다, 추천의 이유가 있는 글이 오래 남습니다.

## 바로 적용할 수 있는 작성 포인트
{action_block}

이 포인트를 글에 옮길 때는 과장된 표현보다, 실제로 겪을 수 있는 장면을 짧게 그려주는 것이 효과적입니다.  
예를 들어 "아침 9시 이전에는 한적해서 사진 구도가 좋다" 같은 문장은, 읽는 사람의 결정을 빠르게 도와줍니다.  
작은 디테일 하나가 글의 신뢰를 만들고, 그 신뢰가 다시 다음 문장을 읽게 합니다.

[IMAGE_PLACEHOLDER_2]

## 끝맺으며
좋은 글은 정보를 많이 담은 글이 아니라, 독자가 한 걸음 움직이게 만드는 글이라고 생각합니다.  
{topic} 역시 마찬가지입니다.  
오늘은 욕심내지 말고, 단 하나의 기준만 정해보세요.  
그 기준이 생기는 순간부터, 검색은 수집이 아니라 선택이 됩니다.
"""


def build_clear_thought_summary(topic: str, analyzed: list[dict[str, Any]]) -> str:
    refs = analyzed[:5]
    if not refs:
        return ""
    key_pool = []
    for r in refs:
        key_pool.extend(r.get("keywords", []))
    top_keys = [k for k, _ in Counter(key_pool).most_common(8)]

    evidence_lines = []
    for r in refs:
        evidence_lines.append(f"- {r.get('title', '제목 없음')}: {short_summary(r.get('summary', ''), 120)}")

    return (
        f"### Clear Thought 요약: {topic}\n\n"
        "#### 1) 사실 관찰\n"
        + "\n".join(evidence_lines)
        + "\n\n#### 2) 패턴 추론\n"
        + f"- 반복 핵심어: {', '.join(top_keys) if top_keys else topic}\n"
        + "- 상위 글은 단순 정보 나열보다 선택 기준과 맥락 설명이 길수록 반응이 좋습니다.\n"
        + "- 독자가 바로 적용 가능한 디테일(시간, 동선, 비용, 대안)이 포함될수록 신뢰도가 올라갑니다.\n\n"
        + "#### 3) 실행 제안\n"
        + "- 글의 첫 20%에서 독자 상황을 구체화하고, 왜 이 글을 읽어야 하는지 한 문장으로 명시하세요.\n"
        + "- 본문은 추천 목록보다 `선택 기준 -> 사례 -> 대안` 순으로 구성하세요.\n"
        + "- 마무리에서는 오늘 실행할 수 있는 행동 2~3개를 제시해 행동 전환을 유도하세요.\n"
    )


def firecrawl_scrape(url: str) -> dict[str, Any]:
    fc_key = _env("FIRECRAWL_API_KEY")
    if not fc_key:
        return {"ok": False, "error": "FIRECRAWL_API_KEY가 설정되지 않았습니다."}

    endpoint = "https://api.firecrawl.dev/v1/scrape"
    headers = {
        "Authorization": f"Bearer {fc_key}",
        "Content-Type": "application/json",
    }
    body = {"url": url, "formats": ["markdown"], "onlyMainContent": True}
    try:
        with httpx.Client(timeout=35) as client:
            res = client.post(endpoint, headers=headers, json=body)
            res.raise_for_status()
            data = res.json()
            markdown = data.get("data", {}).get("markdown", "")
            if not markdown:
                return {"ok": False, "error": "Firecrawl 응답에 markdown 본문이 없습니다."}
            return {"ok": True, "markdown": markdown}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def analyze_top_results(results: list[dict[str, Any]], top_n: int = 5) -> list[dict[str, Any]]:
    analyzed = []
    for row in results[:top_n]:
        scraped = firecrawl_scrape(row["link"])
        if not scraped["ok"]:
            fallback_text = f"{row.get('title', '')}. {row.get('description', '')}"
            analyzed.append(
                {
                    **row,
                    "keywords": extract_keywords(fallback_text, 7),
                    "summary": (
                        "Firecrawl 본문 수집 실패로 검색 description 기반 분석으로 대체했습니다. "
                        f"{row.get('description', '')}"
                    ).strip(),
                    "scrape_ok": False,
                    "analysis_ok": True,
                    "analysis_source": "description_fallback",
                    "analysis_error": scraped["error"],
                }
            )
            continue
        md = scraped["markdown"]
        analyzed.append(
            {
                **row,
                "keywords": extract_keywords(md, 7),
                "summary": short_summary(md),
                "scrape_ok": True,
                "analysis_ok": True,
                "analysis_source": "firecrawl",
                "analysis_error": "",
            }
        )
    return analyzed


def llm_generate_article(topic: str, refs: list[dict[str, Any]], tone: str) -> str:
    ref_block = "\n".join(
        [
            f"- 키워드: {', '.join(r.get('keywords', []))}\n  요약: {r.get('summary', '')}"
            for r in refs
        ]
    )
    prompt = f"""
당신은 전문 블로그 에디터입니다.
주제: {topic}

참고 인사이트(벤치마킹용, 그대로 복사 금지):
{ref_block}

요구사항:
1) 완전히 새로운 글을 한국어로 작성
2) 독자의 이목을 끄는 제목 포함
3) 본문은 실제 정보 중심의 긴 글(최소 1600자 이상)로 작성
3-1) 글의 톤앤매너: {tone}
3-2) "독자를 붙잡는 도입 설계", "문제 -> 해석 -> 실행" 같은 메타 템플릿 문구는 절대 사용 금지
3-3) 상위 참고글에서 추출된 인사이트를 자연스럽게 녹여서 작성
3-4) 작가가 쓴 칼럼처럼 문단 흐름을 살리고, 장면 묘사/맥락/감정을 넣어 서사적으로 작성
3-5) 불필요한 매뉴얼 문체(체크리스트 남발, 기계적 번호 나열)는 최소화
4) 이미지 자리 2곳에 아래 플레이스홀더를 정확히 삽입
   [IMAGE_PLACEHOLDER_1]
   [IMAGE_PLACEHOLDER_2]
5) 마크다운 형식
"""
    api_key = _env("OPENAI_API_KEY").strip().strip('"').strip("'")
    if not api_key:
        return generate_local_creative_article(topic, refs, tone)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
        )
        return completion.choices[0].message.content or "생성 결과가 비어 있습니다."
    except Exception as exc:
        return f"생성 중 오류가 발생했습니다: {exc}"


def build_image_prompts_from_markdown(topic: str, markdown: str) -> list[str]:
    headers = re.findall(r"^##\s+(.+)$", markdown, flags=re.MULTILINE)
    if len(headers) < 2:
        headers = ["핵심 인사이트", "실행 체크리스트"]
    prompt_1 = (
        f"Korean blog hero image about '{topic}', editorial style, clean composition, "
        f"soft natural lighting, modern visual metaphor for '{headers[0]}', no text"
    )
    prompt_2 = (
        f"Korean blog supporting image about '{topic}', practical scene, "
        f"high clarity, visualizing '{headers[1]}', cohesive color tone, no text"
    )
    return [prompt_1, prompt_2]


def _replicate_create_prediction(prompt: str, replicate_token: str) -> str:
    endpoint = "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions"
    headers = {
        "Authorization": f"Token {replicate_token}",
        "Content-Type": "application/json",
    }
    body = {"input": {"prompt": prompt, "output_format": "png", "aspect_ratio": "16:9", "num_outputs": 1}}
    with httpx.Client(timeout=35) as client:
        res = client.post(endpoint, headers=headers, json=body)
        res.raise_for_status()
        data = res.json()
        return data.get("id", "")


def _replicate_wait_output(prediction_id: str, replicate_token: str) -> str:
    endpoint = f"https://api.replicate.com/v1/predictions/{prediction_id}"
    headers = {"Authorization": f"Token {replicate_token}"}
    with httpx.Client(timeout=35) as client:
        for _ in range(35):
            res = client.get(endpoint, headers=headers)
            res.raise_for_status()
            data = res.json()
            status = data.get("status")
            if status == "succeeded":
                output = data.get("output")
                if isinstance(output, list) and output:
                    return output[0]
                if isinstance(output, str):
                    return output
                raise RuntimeError("Replicate output이 비어 있습니다.")
            if status in {"failed", "canceled"}:
                raise RuntimeError(f"Replicate 이미지 생성 실패: {data.get('error', status)}")
            import time

            time.sleep(1.5)
    raise RuntimeError("Replicate 응답 대기 시간이 초과되었습니다.")


def _download_image_bytes(url: str) -> bytes:
    with httpx.Client(timeout=60) as client:
        res = client.get(url)
        res.raise_for_status()
        return res.content


def generate_images_with_replicate(topic: str, markdown: str, replicate_token: str) -> dict[str, Any]:
    if not replicate_token:
        return {"ok": False, "error": "REPLICATE_API_TOKEN이 설정되지 않았습니다.", "items": []}

    prompts = build_image_prompts_from_markdown(topic, markdown)
    items: list[dict[str, Any]] = []
    try:
        for idx, prompt in enumerate(prompts, start=1):
            pred_id = _replicate_create_prediction(prompt, replicate_token)
            if not pred_id:
                raise RuntimeError("Replicate prediction id를 받지 못했습니다.")
            image_url = _replicate_wait_output(pred_id, replicate_token)
            ext = Path(urlparse(image_url).path).suffix or ".png"
            content = _download_image_bytes(image_url)
            items.append({"filename": f"image_{idx}{ext}", "content": content})
        return {"ok": True, "error": "", "items": items}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "items": []}


def generate_images_with_fallback(topic: str, markdown: str) -> dict[str, Any]:
    prompts = build_image_prompts_from_markdown(topic, markdown)
    items: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=60) as client:
            for idx, prompt in enumerate(prompts, start=1):
                url = f"https://image.pollinations.ai/prompt/{quote_plus(prompt)}?width=1280&height=720&seed={idx}"
                res = client.get(url)
                res.raise_for_status()
                items.append({"filename": f"image_{idx}.png", "content": res.content})
        return {"ok": True, "error": "", "items": items}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "items": []}


def inject_images_into_markdown_items(markdown: str, image_items: list[dict[str, Any]]) -> str:
    updated = markdown
    for idx, item in enumerate(image_items[:2], start=1):
        fn = item.get("filename", f"image_{idx}.png")
        updated = updated.replace(f"[IMAGE_PLACEHOLDER_{idx}]", f"![생성 이미지 {idx}]({fn})")
    return updated


def generate_images_auto(topic: str, markdown: str, replicate_token: str) -> dict[str, Any]:
    if not (replicate_token or "").strip():
        return generate_images_with_fallback(topic, markdown)
    out = generate_images_with_replicate(topic, markdown, replicate_token)
    if out["ok"]:
        return out
    err = out.get("error", "")
    if "402" in err:
        return generate_images_with_fallback(topic, markdown)
    return out


def save_markdown_to_desktop(content: str, keyword: str, image_paths: list[Path] | None = None) -> Path:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = re.sub(r"[^가-힣A-Za-z0-9_-]", "_", keyword).strip("_") or "blog"
    bundle_dir = desktop / f"{safe_keyword}_{stamp}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    file_path = bundle_dir / f"{safe_keyword}.md"

    final_content = content
    if image_paths:
        copied_paths: list[Path] = []
        for idx, src in enumerate(image_paths, start=1):
            if not src.exists():
                continue
            dst = bundle_dir / f"image_{idx}{src.suffix or '.png'}"
            dst.write_bytes(src.read_bytes())
            copied_paths.append(dst)

        for idx, dst in enumerate(copied_paths, start=1):
            final_content = re.sub(
                rf"!\[생성 이미지 {idx}\]\([^)]+\)",
                f"![생성 이미지 {idx}]({dst.name})",
                final_content,
            )

    file_path.write_text(final_content, encoding="utf-8")
    return file_path


def save_markdown_bundle_from_items(content: str, keyword: str, image_items: list[dict[str, Any]] | None) -> Path:
    """Save markdown + image bytes to Desktop (same layout as path-based helper)."""
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keyword = re.sub(r"[^가-힣A-Za-z0-9_-]", "_", keyword).strip("_") or "blog"
    bundle_dir = desktop / f"{safe_keyword}_{stamp}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    file_path = bundle_dir / f"{safe_keyword}.md"

    final_content = content
    if image_items:
        for idx, item in enumerate(image_items[:5], start=1):
            fn = item.get("filename") or f"image_{idx}.png"
            dst = bundle_dir / fn
            dst.write_bytes(item.get("content", b""))
            final_content = re.sub(
                rf"!\[생성 이미지 {idx}\]\([^)]+\)",
                f"![생성 이미지 {idx}]({Path(fn).name})",
                final_content,
            )

    file_path.write_text(final_content, encoding="utf-8")
    return file_path
