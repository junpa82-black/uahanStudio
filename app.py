import asyncio
import json
import os
import random
import re
from collections import Counter
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx
import streamlit as st
from dotenv import load_dotenv
from mcp_naver import server as naver_server

load_dotenv()

FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN", "").strip()

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
    raw = await naver_server.search_blog(query=query, display=display, start=1, sort=sort)
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
    if not FIRECRAWL_API_KEY:
        return {"ok": False, "error": "FIRECRAWL_API_KEY가 설정되지 않았습니다."}

    endpoint = "https://api.firecrawl.dev/v1/scrape"
    headers = {
        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
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
    if not OPENAI_API_KEY:
        return generate_local_creative_article(topic, refs, tone)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=OPENAI_API_KEY)
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


def _download_image(url: str, save_path: Path) -> None:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60) as client:
        res = client.get(url)
        res.raise_for_status()
        save_path.write_bytes(res.content)


def generate_images_with_replicate(topic: str, markdown: str, replicate_token: str) -> dict[str, Any]:
    if not replicate_token:
        return {"ok": False, "error": "REPLICATE_API_TOKEN이 설정되지 않았습니다.", "paths": []}

    prompts = build_image_prompts_from_markdown(topic, markdown)
    out_dir = Path.cwd() / "generated_images"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths: list[Path] = []
    try:
        for idx, prompt in enumerate(prompts, start=1):
            pred_id = _replicate_create_prediction(prompt, replicate_token)
            if not pred_id:
                raise RuntimeError("Replicate prediction id를 받지 못했습니다.")
            image_url = _replicate_wait_output(pred_id, replicate_token)
            ext = Path(urlparse(image_url).path).suffix or ".png"
            save_path = out_dir / f"{stamp}_image_{idx}{ext}"
            _download_image(image_url, save_path)
            paths.append(save_path)
        return {"ok": True, "error": "", "paths": paths}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "paths": []}


def generate_images_with_fallback(topic: str, markdown: str) -> dict[str, Any]:
    prompts = build_image_prompts_from_markdown(topic, markdown)
    out_dir = Path.cwd() / "generated_images"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths: list[Path] = []
    try:
        with httpx.Client(timeout=60) as client:
            for idx, prompt in enumerate(prompts, start=1):
                url = f"https://image.pollinations.ai/prompt/{quote_plus(prompt)}?width=1280&height=720&seed={idx}"
                res = client.get(url)
                res.raise_for_status()
                save_path = out_dir / f"{stamp}_fallback_{idx}.png"
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(res.content)
                paths.append(save_path)
        return {"ok": True, "error": "", "paths": paths}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "paths": []}


def inject_images_into_markdown(markdown: str, image_paths: list[Path]) -> str:
    updated = markdown
    if len(image_paths) >= 1:
        updated = updated.replace("[IMAGE_PLACEHOLDER_1]", f"![생성 이미지 1]({image_paths[0].as_posix()})")
    if len(image_paths) >= 2:
        updated = updated.replace("[IMAGE_PLACEHOLDER_2]", f"![생성 이미지 2]({image_paths[1].as_posix()})")
    return updated


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

        # 저장본은 상대 경로로 교체해서 마크다운 미리보기 호환성을 높인다.
        for idx, dst in enumerate(copied_paths, start=1):
            final_content = re.sub(
                rf"!\[생성 이미지 {idx}\]\([^)]+\)",
                f"![생성 이미지 {idx}]({dst.name})",
                final_content,
            )

    file_path.write_text(final_content, encoding="utf-8")
    return file_path


def inject_dashboard_styles() -> None:
    st.markdown(
        """
        <style>
        .main .block-container {
            max-width: 1400px;
            padding-top: 1.2rem;
        }
        .glass-card {
            background: #f7f8fb;
            border: 1px solid #e6e8ef;
            border-radius: 16px;
            padding: 14px 16px;
            margin-bottom: 12px;
        }
        .feed-card {
            background: #ffffff;
            border: 1px solid #e7e9f0;
            border-radius: 16px;
            padding: 14px 16px;
            margin-bottom: 12px;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
        }
        .muted {
            color: #6b7280;
            font-size: 0.9rem;
        }
        .panel-title {
            font-weight: 700;
            margin-bottom: 10px;
        }
        [data-testid="stToolbar"] {
            display: none !important;
        }
        [data-testid="stDecoration"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_result_feed(results: list[dict[str, Any]]) -> None:
    if not results:
        st.markdown(
            '<div class="glass-card"><span class="muted">검색 결과가 여기에 피드 형태로 표시됩니다.</span></div>',
            unsafe_allow_html=True,
        )
        return
    for idx, row in enumerate(results, start=1):
        st.markdown('<div class="feed-card">', unsafe_allow_html=True)
        st.markdown(f"**{idx}. {row['title']}**")
        st.markdown(f"<span class='muted'>{row['bloggername']} · {row.get('postdate', '')}</span>", unsafe_allow_html=True)
        st.write(row["description"])
        st.markdown(
            f"<span class='muted'>랭킹 근거: {row.get('ranking_basis', '관련도(sim)')}</span>",
            unsafe_allow_html=True,
        )
        st.markdown(f"[원본 링크 열기]({row['link']})")
        st.markdown("</div>", unsafe_allow_html=True)


def render_right_panel(analyzed: list[dict[str, Any]]) -> None:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    if analyzed:
        for idx, row in enumerate(analyzed[:5], start=1):
            key_line = ", ".join(row.get("keywords", [])[:3]) or "키워드 없음"
            st.markdown(f"**{idx}. {row['title'][:40]}**")
            st.markdown(f"<span class='muted'>{key_line}</span>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def run() -> None:
    st.set_page_config(page_title="Naver MCP Blog Studio", layout="wide")
    inject_dashboard_styles()
    st.markdown("## 우아한블로그 스튜디오")

    if "results" not in st.session_state:
        st.session_state.results = []
    if "analyzed" not in st.session_state:
        st.session_state.analyzed = []
    if "generated_markdown" not in st.session_state:
        st.session_state.generated_markdown = ""
    if "generated_images" not in st.session_state:
        st.session_state.generated_images = []
    if "search_sort" not in st.session_state:
        st.session_state.search_sort = "sim"
    if "clear_thought_summary" not in st.session_state:
        st.session_state.clear_thought_summary = ""

    keyword = st.text_input("키워드 입력", placeholder="예: 제주도 가족여행")
    tone = st.selectbox(
        "생성 스타일",
        ["전문가톤", "친근톤", "브랜디드톤"],
        index=0,
        help="생성하기 버튼으로 만드는 신규 글의 문체/분위기를 선택합니다.",
    )
    search_sort = st.selectbox(
        "검색 정렬 기준",
        ["관련도순(sim)", "최신순(date)"],
        index=0 if st.session_state.search_sort == "sim" else 1,
        help="네이버 블로그 검색 API 정렬 기준입니다. 조회수 기준은 API에서 제공하지 않습니다.",
    )
    st.session_state.search_sort = "sim" if "sim" in search_sort else "date"
    replicate_token = REPLICATE_API_TOKEN

    top_mid, top_right = st.columns([2.2, 1.2])
    with top_mid:
        if st.button("검색 실행", type="primary", use_container_width=True):
            if not keyword.strip():
                st.warning("키워드를 입력해주세요.")
            else:
                with st.spinner("Naver MCP로 블로그를 검색하는 중..."):
                    try:
                        st.session_state.results = asyncio.run(
                            search_blog_by_naver_mcp(
                                keyword.strip(),
                                display=10,
                                sort=st.session_state.search_sort,
                            )
                        )
                        ranking_label = (
                            "관련도(sim)"
                            if st.session_state.search_sort == "sim"
                            else "최신순(date)"
                        )
                        st.session_state.results = [
                            {**item, "ranking_basis": ranking_label}
                            for item in st.session_state.results
                        ]
                        st.session_state.analyzed = []
                        st.session_state.generated_markdown = ""
                        st.session_state.generated_images = []
                        st.success(f"{len(st.session_state.results)}개 검색 완료 · 정렬기준: {ranking_label}")
                    except Exception as exc:
                        st.error(f"검색 실패: {exc}")

    with top_right:
        if st.button("생성하기", use_container_width=True):
            if not keyword.strip():
                st.warning("키워드를 먼저 입력해주세요.")
            elif not st.session_state.results:
                st.warning("먼저 '검색 실행'을 눌러 검색 결과를 가져와주세요.")
            else:
                with st.spinner("Firecrawl로 상위 5개 본문을 분석 중..."):
                    st.session_state.analyzed = analyze_top_results(st.session_state.results, top_n=5)

                refs = [r for r in st.session_state.analyzed if r.get("analysis_ok")][:5]
                if len(refs) < 3:
                    st.warning(
                        "분석 가능한 글이 부족합니다. 검색 결과 링크 품질을 바꾸거나 "
                        "키워드를 더 구체적으로 입력한 뒤 다시 시도해주세요."
                    )
                else:
                    with st.spinner("벤치마킹 인사이트 기반으로 새로운 글 생성 중..."):
                        st.session_state.generated_markdown = llm_generate_article(keyword, refs, tone)
                        st.success("새 글 생성 완료")
        if st.button("요약하기", use_container_width=True):
            if not keyword.strip():
                st.warning("키워드를 먼저 입력해주세요.")
            elif not st.session_state.results:
                st.warning("먼저 '검색 실행'을 눌러 검색 결과를 가져와주세요.")
            else:
                with st.spinner("블로그 본문 분석 후 Clear Thought 요약 생성 중..."):
                    st.session_state.analyzed = analyze_top_results(st.session_state.results, top_n=5)
                    st.session_state.clear_thought_summary = build_clear_thought_summary(
                        keyword, st.session_state.analyzed
                    )
                st.success("요약 완료")
        if st.session_state.generated_markdown:
            st.subheader("생성된 블로그 초안")
            if st.button("이미지 생성 및 자동 삽입", use_container_width=True):
                with st.spinner("이미지 2장 생성 중..."):
                    generated = generate_images_with_replicate(
                        keyword or "블로그",
                        st.session_state.generated_markdown,
                        replicate_token,
                    )
                    if (not generated["ok"]) and ("402" in generated["error"]):
                        generated = generate_images_with_fallback(keyword or "블로그", st.session_state.generated_markdown)
                        if generated["ok"]:
                            st.info("Replicate 결제 이슈(402)로 대체 이미지 엔진으로 생성했습니다.")
                    if not generated["ok"]:
                        st.error(f"이미지 생성 실패: {generated['error']}")
                    else:
                        st.session_state.generated_images = generated["paths"]
                        st.session_state.generated_markdown = inject_images_into_markdown(
                            st.session_state.generated_markdown,
                            st.session_state.generated_images,
                        )
                        st.success("이미지 삽입 완료")
            if st.session_state.generated_images:
                st.caption("생성 이미지: " + ", ".join([p.name for p in st.session_state.generated_images]))
            st.text_area(
                "마크다운 결과",
                value=st.session_state.generated_markdown,
                height=360,
            )
            if st.button("저장하기", use_container_width=True):
                path = save_markdown_to_desktop(
                    st.session_state.generated_markdown,
                    keyword,
                    st.session_state.generated_images,
                )
                st.success(f"저장 완료: {path}")
        if st.session_state.clear_thought_summary:
            st.subheader("Clear Thought 요약")
            st.markdown(st.session_state.clear_thought_summary)

    center, right = st.columns([2.4, 1.15], gap="medium")
    with center:
        st.subheader("Feed")
        render_result_feed(st.session_state.results)
    with right:
        st.subheader("Trending Insights")
        render_right_panel(st.session_state.analyzed)

    if st.session_state.analyzed:
        st.subheader("Firecrawl 분석 결과")
        for idx, row in enumerate(st.session_state.analyzed, start=1):
            with st.container(border=True):
                st.markdown(f"**{idx}. {row['title']}**")
                st.write(f"- 링크: {row['link']}")
                st.write(f"- 핵심 키워드: {', '.join(row['keywords']) if row['keywords'] else '없음'}")
                st.write(f"- 요약: {row['summary']}")
                if row.get("analysis_source") == "description_fallback":
                    st.caption("※ Firecrawl 실패로 description 기반 대체 분석")

if __name__ == "__main__":
    run()
