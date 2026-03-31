"""로컬 전용 Streamlit UI. 프로덕션(Vercel)은 FastAPI + public/ 정적 UI."""

import asyncio

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

import studio.service as svc


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


def render_result_feed(results: list) -> None:
    if not results:
        st.markdown(
            '<div class="glass-card"><span class="muted">검색 결과가 여기에 피드 형태로 표시됩니다.</span></div>',
            unsafe_allow_html=True,
        )
        return
    for idx, row in enumerate(results, start=1):
        st.markdown('<div class="feed-card">', unsafe_allow_html=True)
        st.markdown(f"**{idx}. {row['title']}**")
        st.markdown(
            f"<span class='muted'>{row['bloggername']} · {row.get('postdate', '')}</span>",
            unsafe_allow_html=True,
        )
        st.write(row["description"])
        st.markdown(
            f"<span class='muted'>랭킹 근거: {row.get('ranking_basis', '관련도(sim)')}</span>",
            unsafe_allow_html=True,
        )
        st.markdown(f"[원본 링크 열기]({row['link']})")
        st.markdown("</div>", unsafe_allow_html=True)


def render_right_panel(analyzed: list) -> None:
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
    if "generated_image_items" not in st.session_state:
        st.session_state.generated_image_items = []
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
    replicate_token = svc.get_replicate_token()

    top_mid, top_right = st.columns([2.2, 1.2])
    with top_mid:
        if st.button("검색 실행", type="primary", use_container_width=True):
            if not keyword.strip():
                st.warning("키워드를 입력해주세요.")
            else:
                with st.spinner("Naver MCP로 블로그를 검색하는 중..."):
                    try:
                        st.session_state.results = asyncio.run(
                            svc.search_blog_by_naver_mcp(
                                keyword.strip(),
                                display=10,
                                sort=st.session_state.search_sort,
                            )
                        )
                        ranking_label = (
                            "관련도(sim)" if st.session_state.search_sort == "sim" else "최신순(date)"
                        )
                        st.session_state.results = [
                            {**item, "ranking_basis": ranking_label}
                            for item in st.session_state.results
                        ]
                        st.session_state.analyzed = []
                        st.session_state.generated_markdown = ""
                        st.session_state.generated_image_items = []
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
                    st.session_state.analyzed = svc.analyze_top_results(st.session_state.results, top_n=5)

                refs = [r for r in st.session_state.analyzed if r.get("analysis_ok")][:5]
                if len(refs) < 3:
                    st.warning(
                        "분석 가능한 글이 부족합니다. 검색 결과 링크 품질을 바꾸거나 "
                        "키워드를 더 구체적으로 입력한 뒤 다시 시도해주세요."
                    )
                else:
                    with st.spinner("벤치마킹 인사이트 기반으로 새로운 글 생성 중..."):
                        st.session_state.generated_markdown = svc.llm_generate_article(keyword, refs, tone)
                        st.session_state.generated_image_items = []
                        st.success("새 글 생성 완료")
        if st.button("요약하기", use_container_width=True):
            if not keyword.strip():
                st.warning("키워드를 먼저 입력해주세요.")
            elif not st.session_state.results:
                st.warning("먼저 '검색 실행'을 눌러 검색 결과를 가져와주세요.")
            else:
                with st.spinner("블로그 본문 분석 후 Clear Thought 요약 생성 중..."):
                    st.session_state.analyzed = svc.analyze_top_results(st.session_state.results, top_n=5)
                    st.session_state.clear_thought_summary = svc.build_clear_thought_summary(
                        keyword, st.session_state.analyzed
                    )
                st.success("요약 완료")
        if st.session_state.generated_markdown:
            st.subheader("생성된 블로그 초안")
            if st.button("이미지 생성 및 자동 삽입", use_container_width=True):
                with st.spinner("이미지 2장 생성 중..."):
                    generated = svc.generate_images_auto(
                        keyword or "블로그",
                        st.session_state.generated_markdown,
                        replicate_token,
                    )
                    if not generated["ok"]:
                        st.error(f"이미지 생성 실패: {generated['error']}")
                    else:
                        st.session_state.generated_image_items = generated["items"]
                        st.session_state.generated_markdown = svc.inject_images_into_markdown_items(
                            st.session_state.generated_markdown,
                            st.session_state.generated_image_items,
                        )
                        st.success("이미지 삽입 완료")
            if st.session_state.generated_image_items:
                names = [i.get("filename", "") for i in st.session_state.generated_image_items]
                st.caption("생성 이미지: " + ", ".join(names))
            st.text_area(
                "마크다운 결과",
                value=st.session_state.generated_markdown,
                height=360,
            )
            if st.button("저장하기", use_container_width=True):
                path = svc.save_markdown_bundle_from_items(
                    st.session_state.generated_markdown,
                    keyword,
                    st.session_state.generated_image_items or None,
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
