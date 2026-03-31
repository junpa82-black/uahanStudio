const $ = (id) => document.getElementById(id);

const state = {
  results: [],
  analyzed: [],
  markdown: "",
  images: [],
};

function setStatus(msg, isErr = false) {
  const el = $("status");
  el.textContent = msg;
  el.className = isErr ? "err" : "ok";
}

async function api(path, body) {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || data.message || JSON.stringify(data);
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function renderFeed() {
  const feed = $("feed");
  if (!state.results.length) {
    feed.innerHTML = '<div class="panel muted">검색 결과가 여기에 표시됩니다.</div>';
    return;
  }
  feed.innerHTML = state.results
    .map((row, i) => {
      const rank = row.ranking_basis || "관련도(sim)";
      return `<div class="feed-card">
        <strong>${i + 1}. ${escapeHtml(row.title)}</strong>
        <div class="muted">${escapeHtml(row.bloggername || "")} · ${escapeHtml(row.postdate || "")}</div>
        <p>${escapeHtml(row.description || "")}</p>
        <div class="muted">랭킹 근거: ${escapeHtml(rank)}</div>
        <a href="${escapeAttr(row.link)}" target="_blank" rel="noopener">원본 링크</a>
      </div>`;
    })
    .join("");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return String(s).replace(/"/g, "&quot;");
}

function renderTrending() {
  const el = $("trending");
  if (!state.analyzed.length) {
    el.innerHTML = '<span class="muted">—</span>';
    return;
  }
  el.innerHTML = state.analyzed
    .slice(0, 5)
    .map((row, i) => {
      const k = (row.keywords || []).slice(0, 3).join(", ") || "키워드 없음";
      return `<div class="insight-item"><strong>${i + 1}. ${escapeHtml((row.title || "").slice(0, 42))}</strong><div class="muted">${escapeHtml(k)}</div></div>`;
    })
    .join("");
}

function renderAnalysis() {
  const el = $("analysis");
  if (!state.analyzed.length) {
    el.textContent = "생성·요약 실행 후 표시됩니다.";
    el.className = "panel muted";
    return;
  }
  el.className = "panel";
  el.innerHTML = state.analyzed
    .map(
      (row, i) =>
        `<div style="margin-bottom:0.75rem"><strong>${i + 1}. ${escapeHtml(row.title)}</strong>
        <div class="muted"><a href="${escapeAttr(row.link)}" target="_blank">링크</a></div>
        <div>키워드: ${escapeHtml((row.keywords || []).join(", ") || "없음")}</div>
        <div class="muted">${escapeHtml((row.summary || "").slice(0, 400))}</div>
        ${row.analysis_source === "description_fallback" ? '<div class="muted">※ description 대체 분석</div>' : ""}
        </div>`
    )
    .join("");
}

function renderDraft() {
  $("draft").textContent = state.markdown || "(없음)";
}

$("btn-search").addEventListener("click", async () => {
  const keyword = $("keyword").value.trim();
  const sort = $("sort").value;
  if (!keyword) {
    setStatus("키워드를 입력하세요.", true);
    return;
  }
  setStatus("검색 중…");
  try {
    const data = await api("/search", { keyword, sort });
    state.results = data.results || [];
    state.analyzed = [];
    state.markdown = "";
    state.images = [];
    renderFeed();
    renderTrending();
    renderAnalysis();
    renderDraft();
    $("summary").textContent = "요약하기 버튼으로 생성합니다.";
    setStatus(`완료 · ${state.results.length}건 · ${data.sort_label || ""}`);
  } catch (e) {
    setStatus(e.message, true);
  }
});

$("btn-generate").addEventListener("click", async () => {
  const keyword = $("keyword").value.trim();
  const tone = $("tone").value;
  if (!keyword) {
    setStatus("키워드를 입력하세요.", true);
    return;
  }
  if (!state.results.length) {
    setStatus("먼저 검색 실행하세요.", true);
    return;
  }
  setStatus("분석·생성 중…");
  try {
    const a = await api("/analyze", { results: state.results });
    state.analyzed = a.analyzed || [];
    const g = await api("/generate", { keyword, tone, analyzed: state.analyzed });
    state.markdown = g.markdown || "";
    state.images = [];
    renderTrending();
    renderAnalysis();
    renderDraft();
    setStatus("생성 완료");
  } catch (e) {
    setStatus(e.message, true);
  }
});

$("btn-summarize").addEventListener("click", async () => {
  const keyword = $("keyword").value.trim();
  if (!keyword) {
    setStatus("키워드를 입력하세요.", true);
    return;
  }
  if (!state.results.length) {
    setStatus("먼저 검색 실행하세요.", true);
    return;
  }
  setStatus("요약 중…");
  try {
    const a = await api("/analyze", { results: state.results });
    state.analyzed = a.analyzed || [];
    const s = await api("/summarize", { keyword, analyzed: state.analyzed });
    $("summary").innerHTML = markedLight(s.summary || "");
    renderTrending();
    renderAnalysis();
    setStatus("요약 완료");
  } catch (e) {
    setStatus(e.message, true);
  }
});

function markedLight(md) {
  return escapeHtml(md).replace(/\n/g, "<br/>");
}

$("btn-images").addEventListener("click", async () => {
  const keyword = $("keyword").value.trim();
  if (!state.markdown) {
    setStatus("먼저 생성하기로 글을 만드세요.", true);
    return;
  }
  setStatus("이미지 생성 중…");
  try {
    const data = await api("/images", { keyword: keyword || "블로그", markdown: state.markdown });
    state.markdown = data.markdown || state.markdown;
    state.images = data.images || [];
    renderDraft();
    setStatus(`이미지 삽입 완료 · Replicate 설정: ${data.replicate_configured}`);
  } catch (e) {
    setStatus(e.message, true);
  }
});

$("btn-download").addEventListener("click", async () => {
  if (!state.markdown) {
    setStatus("저장할 초안이 없습니다.", true);
    return;
  }
  const keyword = $("keyword").value.trim() || "blog";
  const safe = keyword.replace(/[^가-힣A-Za-z0-9_-]/g, "_");
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "");

  const { default: JSZip } = await import("https://esm.sh/jszip@3.10.1");
  const zip = new JSZip();
  let md = state.markdown;
  (state.images || []).forEach((img, i) => {
    const name = img.filename || `image_${i + 1}.png`;
    const bin = Uint8Array.from(atob(img.content_base64 || ""), (c) => c.charCodeAt(0));
    zip.file(name, bin);
    md = md.replace(new RegExp(`!\\[생성 이미지 ${i + 1}\\]\\([^)]*\\)`, "g"), `![생성 이미지 ${i + 1}](${name})`);
  });
  zip.file(`${safe}.md`, md);
  const blob = await zip.generateAsync({ type: "blob" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${safe}_${stamp}.zip`;
  a.click();
  URL.revokeObjectURL(a.href);
  setStatus("ZIP 다운로드 시작됨");
});

renderFeed();
renderTrending();
renderDraft();
