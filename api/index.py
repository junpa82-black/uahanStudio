import base64
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
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

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>우아한블로그 스튜디오</title>
    <style>
      :root { --bg:#f6f7fb; --card:#fff; --border:#e7e9f0; --text:#111827; --muted:#6b7280; --accent:#dc2626; }
      *{ box-sizing:border-box; }
      body{ margin:0; font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,"Apple SD Gothic Neo","Noto Sans KR",sans-serif; background:var(--bg); color:var(--text); }
      header{ padding:1.25rem 1.5rem; background:var(--card); border-bottom:1px solid var(--border); }
      header h1{ margin:0; font-size:1.35rem; }
      .layout{ display:grid; grid-template-columns:minmax(0,2.2fr) minmax(280px,1fr); gap:1rem; padding:1rem 1.25rem 2rem; max-width:1280px; margin:0 auto; }
      .panel{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:1rem; margin-bottom:.75rem; }
      label{ display:block; font-size:.85rem; font-weight:600; margin-bottom:.35rem; }
      input[type="text"], select, textarea{ width:100%; padding:.55rem .65rem; border:1px solid var(--border); border-radius:8px; font:inherit; }
      .row{ display:flex; gap:.5rem; flex-wrap:wrap; margin-bottom:.75rem; }
      button{ cursor:pointer; border-radius:8px; font:inherit; padding:.55rem 1rem; border:1px solid var(--border); background:var(--card); }
      button.primary{ background:var(--accent); color:#fff; border-color:var(--accent); }
      button:disabled{ opacity:.55; cursor:not-allowed; }
      .muted{ color:var(--muted); font-size:.88rem; }
      .feed-card{ border:1px solid var(--border); border-radius:12px; padding:.85rem; margin-bottom:.65rem; background:#fff; }
      .feed-card a{ color:var(--accent); }
      .insight-item{ padding:.35rem 0; border-bottom:1px solid var(--border); }
      .insight-item:last-child{ border-bottom:none; }
      #status{ margin-top:.5rem; font-size:.9rem; }
      .err{ color:#b91c1c; } .ok{ color:#15803d; }
      pre.out{ white-space:pre-wrap; word-break:break-word; font-size:.85rem; max-height:320px; overflow:auto; background:#f9fafb; padding:.75rem; border-radius:8px; border:1px solid var(--border); }
      @media (max-width:900px){ .layout{ grid-template-columns:1fr; } }
    </style>
  </head>
  <body>
    <header>
      <h1>우아한블로그 스튜디오</h1>
      <p class="muted">Vercel · 검색 → 분석 → 생성 → 이미지</p>
    </header>

    <div class="layout">
      <main>
        <div class="panel">
          <label for="keyword">키워드 입력</label>
          <input id="keyword" type="text" placeholder="예: 제주도 가족여행" />

          <div class="row" style="margin-top: 0.75rem">
            <div style="flex: 1; min-width: 140px">
              <label for="tone">생성 스타일</label>
              <select id="tone">
                <option value="전문가톤">전문가톤</option>
                <option value="친근톤">친근톤</option>
                <option value="브랜디드톤">브랜디드톤</option>
              </select>
            </div>
            <div style="flex: 1; min-width: 140px">
              <label for="sort">검색 정렬</label>
              <select id="sort">
                <option value="sim">관련도순 (sim)</option>
                <option value="date">최신순 (date)</option>
              </select>
            </div>
          </div>

          <div class="row">
            <button class="primary" id="btn-search">검색 실행</button>
            <button id="btn-generate">생성하기</button>
            <button id="btn-summarize">요약하기</button>
            <button id="btn-images">이미지 생성 및 삽입</button>
            <button id="btn-download">다운로드 (md + 이미지)</button>
          </div>
          <div id="status" class="muted"></div>
        </div>

        <h2>Feed</h2>
        <div id="feed"></div>

        <h2>Firecrawl 분석 결과</h2>
        <div id="analysis" class="panel muted">생성·요약 실행 후 표시됩니다.</div>

        <h2>생성된 블로그 초안</h2>
        <div class="panel">
          <pre class="out" id="draft">(없음)</pre>
        </div>
      </main>

      <aside>
        <h2>Trending Insights</h2>
        <div id="trending" class="panel"></div>

        <h2>Clear Thought 요약</h2>
        <div class="panel">
          <div id="summary" class="muted">요약하기 버튼으로 생성합니다.</div>
        </div>
      </aside>
    </div>

    <script type="module">
      const $ = (id) => document.getElementById(id);
      const state = { results: [], analyzed: [], markdown: "", images: [] };

      function setStatus(msg, isErr=false){ const el=$("status"); el.textContent=msg; el.className=isErr?"err":"ok"; }
      async function api(path, body){
        const res = await fetch(`/api${path}`, { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(body) });
        const data = await res.json().catch(()=>({}));
        if(!res.ok){ const detail = data.detail || data.message || JSON.stringify(data); throw new Error(typeof detail==="string"?detail:JSON.stringify(detail)); }
        return data;
      }
      function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\"/g,"&quot;"); }
      function escAttr(s){ return String(s).replace(/\"/g,"&quot;"); }

      function renderFeed(){
        const feed=$("feed");
        if(!state.results.length){ feed.innerHTML='<div class="panel muted">검색 결과가 여기에 표시됩니다.</div>'; return; }
        feed.innerHTML = state.results.map((row,i)=> {
          const rank = row.ranking_basis || "관련도(sim)";
          return `<div class="feed-card">
            <strong>${i+1}. ${esc(row.title)}</strong>
            <div class="muted">${esc(row.bloggername||"")} · ${esc(row.postdate||"")}</div>
            <p>${esc(row.description||"")}</p>
            <div class="muted">랭킹 근거: ${esc(rank)}</div>
            <a href="${escAttr(row.link)}" target="_blank" rel="noopener">원본 링크</a>
          </div>`;
        }).join("");
      }
      function renderTrending(){
        const el=$("trending");
        if(!state.analyzed.length){ el.innerHTML='<span class="muted">—</span>'; return; }
        el.innerHTML = state.analyzed.slice(0,5).map((row,i)=> {
          const k=(row.keywords||[]).slice(0,3).join(", ") || "키워드 없음";
          return `<div class="insight-item"><strong>${i+1}. ${esc((row.title||"").slice(0,42))}</strong><div class="muted">${esc(k)}</div></div>`;
        }).join("");
      }
      function renderAnalysis(){
        const el=$("analysis");
        if(!state.analyzed.length){ el.textContent="생성·요약 실행 후 표시됩니다."; el.className="panel muted"; return; }
        el.className="panel";
        el.innerHTML = state.analyzed.map((row,i)=> `
          <div style="margin-bottom:0.75rem">
            <strong>${i+1}. ${esc(row.title)}</strong>
            <div class="muted"><a href="${escAttr(row.link)}" target="_blank">링크</a></div>
            <div>키워드: ${esc((row.keywords||[]).join(", ") || "없음")}</div>
            <div class="muted">${esc((row.summary||"").slice(0,400))}</div>
            ${row.analysis_source==="description_fallback" ? '<div class="muted">※ description 대체 분석</div>' : ''}
          </div>
        `).join("");
      }
      function renderDraft(){ $("draft").textContent = state.markdown || "(없음)"; }

      $("btn-search").addEventListener("click", async ()=> {
        const keyword=$("keyword").value.trim(); const sort=$("sort").value;
        if(!keyword){ setStatus("키워드를 입력하세요.", true); return; }
        setStatus("검색 중…");
        try{
          const data = await api("/search", { keyword, sort });
          state.results = data.results || [];
          state.analyzed = []; state.markdown=""; state.images=[];
          renderFeed(); renderTrending(); renderAnalysis(); renderDraft();
          $("summary").textContent = "요약하기 버튼으로 생성합니다.";
          setStatus(`완료 · ${state.results.length}건 · ${data.sort_label||""}`);
        }catch(e){ setStatus(e.message, true); }
      });
      $("btn-generate").addEventListener("click", async ()=> {
        const keyword=$("keyword").value.trim(); const tone=$("tone").value;
        if(!keyword){ setStatus("키워드를 입력하세요.", true); return; }
        if(!state.results.length){ setStatus("먼저 검색 실행하세요.", true); return; }
        setStatus("분석·생성 중…");
        try{
          const a = await api("/analyze", { results: state.results });
          state.analyzed = a.analyzed || [];
          const g = await api("/generate", { keyword, tone, analyzed: state.analyzed });
          state.markdown = g.markdown || ""; state.images=[];
          renderTrending(); renderAnalysis(); renderDraft();
          setStatus("생성 완료");
        }catch(e){ setStatus(e.message, true); }
      });
      $("btn-summarize").addEventListener("click", async ()=> {
        const keyword=$("keyword").value.trim();
        if(!keyword){ setStatus("키워드를 입력하세요.", true); return; }
        if(!state.results.length){ setStatus("먼저 검색 실행하세요.", true); return; }
        setStatus("요약 중…");
        try{
          const a = await api("/analyze", { results: state.results });
          state.analyzed = a.analyzed || [];
          const s = await api("/summarize", { keyword, analyzed: state.analyzed });
          $("summary").innerHTML = esc(s.summary||"").replace(/\\n/g,"<br/>");
          renderTrending(); renderAnalysis();
          setStatus("요약 완료");
        }catch(e){ setStatus(e.message, true); }
      });
      $("btn-images").addEventListener("click", async ()=> {
        const keyword=$("keyword").value.trim();
        if(!state.markdown){ setStatus("먼저 생성하기로 글을 만드세요.", true); return; }
        setStatus("이미지 생성 중…");
        try{
          const data = await api("/images", { keyword: keyword || "블로그", markdown: state.markdown });
          state.markdown = data.markdown || state.markdown;
          state.images = data.images || [];
          renderDraft();
          setStatus(`이미지 삽입 완료 · Replicate 설정: ${data.replicate_configured}`);
        }catch(e){ setStatus(e.message, true); }
      });
      $("btn-download").addEventListener("click", async ()=> {
        if(!state.markdown){ setStatus("저장할 초안이 없습니다.", true); return; }
        const keyword=$("keyword").value.trim() || "blog";
        const safe=keyword.replace(/[^가-힣A-Za-z0-9_-]/g,"_");
        const stamp=new Date().toISOString().slice(0,19).replace(/[:T]/g,"");
        const { default: JSZip } = await import("https://esm.sh/jszip@3.10.1");
        const zip=new JSZip();
        let md=state.markdown;
        (state.images||[]).forEach((img,i)=> {
          const name=img.filename || `image_${i+1}.png`;
          const bin = Uint8Array.from(atob(img.content_base64||""), c=>c.charCodeAt(0));
          zip.file(name, bin);
          md = md.replace(new RegExp(`!\\\\[생성 이미지 ${i+1}\\\\]\\\\([^)]*\\\\)`, "g"), `![생성 이미지 ${i+1}](${name})`);
        });
        zip.file(`${safe}.md`, md);
        const blob=await zip.generateAsync({ type:"blob" });
        const a=document.createElement("a");
        a.href=URL.createObjectURL(blob);
        a.download=`${safe}_${stamp}.zip`;
        a.click();
        URL.revokeObjectURL(a.href);
        setStatus("ZIP 다운로드 시작됨");
      });

      renderFeed(); renderTrending(); renderDraft();
    </script>
  </body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index_html():
    return INDEX_HTML


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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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

