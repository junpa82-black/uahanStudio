import base64
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import studio.service as svc

app = FastAPI(title="Uahan Studio API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/api")


class SearchBody(BaseModel):
    keyword: str = Field(..., min_length=1)
    sort: Literal["sim", "date"] = "sim"


class AnalyzeBody(BaseModel):
    results: list[dict[str, Any]]


class GenerateBody(BaseModel):
    keyword: str
    tone: str = "전문가톤"
    analyzed: list[dict[str, Any]]


class SummarizeBody(BaseModel):
    keyword: str
    analyzed: list[dict[str, Any]]


class ImagesBody(BaseModel):
    keyword: str
    markdown: str


@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@router.post("/search")
async def search(body: SearchBody) -> dict[str, Any]:
    try:
        rows = await svc.search_blog_by_naver_mcp(body.keyword.strip(), display=10, sort=body.sort)
        label = "관련도(sim)" if body.sort == "sim" else "최신순(date)"
        rows = [{**item, "ranking_basis": label} for item in rows]
        return {"results": rows, "sort": body.sort, "sort_label": label}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/analyze")
def analyze(body: AnalyzeBody) -> dict[str, Any]:
    if not body.results:
        raise HTTPException(status_code=400, detail="results 비어 있음")
    analyzed = svc.analyze_top_results(body.results, top_n=5)
    return {"analyzed": analyzed}


@router.post("/generate")
def generate(body: GenerateBody) -> dict[str, Any]:
    refs = [r for r in body.analyzed if r.get("analysis_ok")][:5]
    if len(refs) < 3:
        raise HTTPException(status_code=400, detail="분석 가능한 참조가 부족합니다(최소 3개).")
    md = svc.llm_generate_article(body.keyword, refs, body.tone)
    return {"markdown": md}


@router.post("/summarize")
def summarize(body: SummarizeBody) -> dict[str, Any]:
    if not body.analyzed:
        raise HTTPException(status_code=400, detail="analyzed 비어 있음")
    text = svc.build_clear_thought_summary(body.keyword, body.analyzed)
    return {"summary": text}


@router.post("/images")
def images(body: ImagesBody) -> dict[str, Any]:
    token = svc.get_replicate_token()
    out = svc.generate_images_auto(body.keyword or "블로그", body.markdown, token)
    if not out["ok"]:
        raise HTTPException(status_code=500, detail=out["error"])
    items_out = []
    for item in out["items"]:
        items_out.append(
            {
                "filename": item["filename"],
                "content_base64": base64.b64encode(item["content"]).decode("ascii"),
            }
        )
    md = svc.inject_images_into_markdown_items(body.markdown, out["items"])
    return {
        "markdown": md,
        "images": items_out,
        "replicate_configured": bool(token),
    }


app.include_router(router)

