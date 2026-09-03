import { resumeActivityTarget, setActiveView, setHomeMode, setRouteHash } from "../core/router.js";
import { $, state } from "../core/state.js";
import { startWorkspaceTimer, stopReadingTimer } from "../core/timer.js";
import { escapeHtml, formatDuration, refreshIcons, renderMarkdown, showToast } from "../core/utils.js";
import { loadStats } from "./logs.js";
import { closeNotePopover } from "./reader.js";

export function reviewDateLabel(value) {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
}

export function setReviewPanel() {
  $("reviewEmpty")?.classList.add("hidden");
  $("reviewReportPanel")?.classList.remove("hidden");
}

function formatHours(seconds) {
  const secs = Number(seconds || 0);
  if (secs <= 0) return "0 小时";
  const hrs = (secs / 3600).toFixed(1);
  return hrs.endsWith(".0") ? `${parseInt(hrs, 10)} 小时` : `${hrs} 小时`;
}

function renderDomainNotesList(notes, domainLabel) {
  if (!notes || !notes.length) {
    return `<div class="review-domain-empty"><span>昨日${domainLabel}以做题或通读为主，未留独立文字笔记</span></div>`;
  }
  return notes.map((note) => `
    <article class="review-note-card" data-note-id="${escapeHtml(note.id)}">
      <div class="review-note-card-header">
        <div class="review-note-tags">
          ${(note.tags || []).map((tag) => `<span class="review-tag-pill">${escapeHtml(tag)}</span>`).join("")}
        </div>
        ${note.resume_target?.view ? `<button type="button" class="review-card-jump-btn" data-review-jump='${escapeHtml(JSON.stringify(note.resume_target))}' title="直达原章节/题目"><i data-lucide="external-link"></i><span>直达</span></button>` : ""}
      </div>
      <div class="knowledge-article review-note-card-body">${renderMarkdown(note.markdown || "")}</div>
    </article>
  `).join("");
}

export function renderReviewNotes() {
  const container = $("reviewNotesContainer");
  if (!container) return;
  const review = state.review;
  if (!review) return;

  const notesByDomain = review.notes_by_domain || { medicine: [], politics: [], english: [] };
  const filter = state.reviewActiveFilter || "all";
  const medNotes = notesByDomain.medicine || [];
  const polNotes = notesByDomain.politics || [];
  const engNotes = notesByDomain.english || [];
  const totalNotes = review.total_notes !== undefined ? review.total_notes : (medNotes.length + polNotes.length + engNotes.length);

  if (totalNotes === 0) {
    container.innerHTML = `
      <div class="review-no-notes">
        <i data-lucide="notebook-pen"></i>
        <strong>昨日以纯做题与通读为主，未留独立文字笔记</strong>
        <span>可在上方查看各学科学习时长，或点击复制笔记摘要让侧边栏 AI 进行综合复盘。</span>
      </div>
    `;
    refreshIcons();
    return;
  }

  let html = "";
  if (filter === "all" || filter === "medicine") {
    html += `
      <section class="review-domain-section">
        <header class="review-domain-section-head">
          <div class="domain-head-title"><i data-lucide="stethoscope"></i><h3>医学</h3></div>
          <span class="review-domain-badge">${medNotes.length} 条笔记</span>
        </header>
        <div class="review-note-list">${renderDomainNotesList(medNotes, "医学")}</div>
      </section>
    `;
  }

  if (filter === "all" || filter === "politics") {
    html += `
      <section class="review-domain-section">
        <header class="review-domain-section-head">
          <div class="domain-head-title"><i data-lucide="landmark"></i><h3>政治</h3></div>
          <span class="review-domain-badge">${polNotes.length} 条笔记</span>
        </header>
        <div class="review-note-list">${renderDomainNotesList(polNotes, "政治")}</div>
      </section>
    `;
  }

  if (filter === "all" || filter === "english") {
    html += `
      <section class="review-domain-section">
        <header class="review-domain-section-head">
          <div class="domain-head-title"><i data-lucide="languages"></i><h3>英语</h3></div>
          <span class="review-domain-badge">${engNotes.length} 条笔记</span>
        </header>
        <div class="review-note-list">${renderDomainNotesList(engNotes, "英语")}</div>
      </section>
    `;
  }

  container.innerHTML = html;

  container.querySelectorAll("[data-review-jump]").forEach((btn) => {
    btn.addEventListener("click", () => {
      try {
        const target = JSON.parse(btn.dataset.reviewJump);
        resumeActivityTarget(target);
      } catch (err) {
        console.error("Failed to resume target:", err);
      }
    });
  });

  refreshIcons();
}

export function renderReviewUnified() {
  const review = state.review;
  if (!review) return;

  const notesByDomain = review.notes_by_domain || { medicine: [], politics: [], english: [] };
  const domainStats = review.domain_stats || {};
  const medNotes = notesByDomain.medicine || [];
  const polNotes = notesByDomain.politics || [];
  const engNotes = notesByDomain.english || [];
  const totalNotes = review.total_notes !== undefined ? review.total_notes : (medNotes.length + polNotes.length + engNotes.length);

  $("reviewTitle").textContent = review ? `${reviewDateLabel(review.review_date)} · 学习回顾` : "学习回顾";
  $("reviewSummary").textContent = review ? `昨日沉淀 ${totalNotes} 条笔记与核心思考` : "正在整理最近的学习活动…";
  $("reviewProgressText").textContent = review?.review_done ? "已完成" : "待回顾";

  // 1. Overview Card Stats
  if ($("reviewTotalDuration")) $("reviewTotalDuration").textContent = formatHours(review.duration_seconds || 0);
  if ($("reviewTotalNotes")) $("reviewTotalNotes").textContent = `${totalNotes} 条`;

  const medSec = (domainStats.medicine || {}).duration_seconds || 0;
  const polSec = (domainStats.politics || {}).duration_seconds || 0;
  const engSec = (domainStats.english || {}).duration_seconds || 0;

  if ($("reviewMedMetric")) $("reviewMedMetric").textContent = `${formatHours(medSec)} · ${medNotes.length} 条笔记`;
  if ($("reviewPolMetric")) $("reviewPolMetric").textContent = `${formatHours(polSec)} · ${polNotes.length} 条笔记`;
  if ($("reviewEngMetric")) $("reviewEngMetric").textContent = `${formatHours(engSec)} · ${engNotes.length} 条笔记`;

  // 2. Filter Counts
  if ($("reviewFilterAllCount")) $("reviewFilterAllCount").textContent = `(${totalNotes})`;
  if ($("reviewFilterMedCount")) $("reviewFilterMedCount").textContent = `(${medNotes.length})`;
  if ($("reviewFilterPolCount")) $("reviewFilterPolCount").textContent = `(${polNotes.length})`;
  if ($("reviewFilterEngCount")) $("reviewFilterEngCount").textContent = `(${engNotes.length})`;

  // 3. Notes Container
  renderReviewNotes();

  // 4. Daily summary & Obsidian link
  $("reviewDailySummary").value = review?.review_result || "";
  $("reviewSummarySaved").textContent = review?.review_done
    ? (review.review_no_text ? "已标记为无文本回顾" : "已保存为独立学习记录")
    : "粘贴侧边栏 Gemini 的复盘总结，自动保存为当日独立学习记录";
  $("reviewLogObsidian").href = review?.learning_record_uri || review?.log_uri || "obsidian://open";

  // Compatibility element
  if ($("reviewCombinedDocument")) {
    $("reviewCombinedDocument").innerHTML = renderMarkdown(review?.combined_markdown || "");
  }

  // 5. Bind events if not bound
  bindReviewEvents();

  setReviewPanel();
  refreshIcons();
  window.scrollTo({ top: 0, behavior: "auto" });
}

export function setReviewNoteOpen(open) {
  state.reviewNoteOpen = Boolean(open);
  $("reviewNoteFloat")?.classList.toggle("note-is-open", state.reviewNoteOpen);
  $("reviewNotePopover")?.classList.toggle("is-open", state.reviewNoteOpen);
  $("reviewNotePopover")?.setAttribute("aria-hidden", String(!state.reviewNoteOpen));
  $("toggleReviewNoteDock")?.setAttribute("aria-expanded", String(state.reviewNoteOpen));
  if (state.reviewNoteOpen) window.setTimeout(() => $("reviewDailySummary")?.focus(), 120);
}

let reviewEventsBound = false;
function bindReviewEvents() {
  if (reviewEventsBound) return;

  $("reviewCopyPromptBtn")?.addEventListener("click", async () => {
    const prompt = state.review?.ai_summary_prompt || "";
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt);
      showToast("已复制三科笔记摘要，可直接在侧边栏 Gemini 中粘贴提炼！");
    } catch {
      showToast("复制失败，请手动复制");
    }
  });

  $("reviewOpenDrawerBtn")?.addEventListener("click", () => {
    setReviewNoteOpen(!state.reviewNoteOpen);
  });

  $("toggleReviewNoteDock")?.addEventListener("click", () => {
    setReviewNoteOpen(!state.reviewNoteOpen);
  });

  $("closeReviewNote")?.addEventListener("click", () => {
    setReviewNoteOpen(false);
  });

  $("reviewDailySummary")?.addEventListener("input", scheduleDailySummarySave);
  $("reviewMarkNoText")?.addEventListener("click", markReviewNoText);

  $("reviewDomainTabs")?.querySelectorAll("[data-review-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("reviewDomainTabs").querySelectorAll("[data-review-filter]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.reviewActiveFilter = btn.dataset.reviewFilter;
      renderReviewNotes();
    });
  });

  reviewEventsBound = true;
}

export async function openReview(reviewDate = "") {
  if (typeof reviewDate !== "string") reviewDate = "";
  setRouteHash("review");
  state.openRequest += 1;
  stopReadingTimer();
  closeNotePopover();
  $("sectionNoteFloat")?.classList.add("hidden");
  $("oralFocusNoteFloat")?.classList.add("hidden");
  $("practiceNoteFloat")?.classList.add("hidden");
  $("reviewNoteFloat")?.classList.remove("hidden");
  setReviewNoteOpen(false);
  setActiveView("review");
  window.scrollTo({ top: 0, behavior: "auto" });

  try {
    const suffix = reviewDate ? `?date=${encodeURIComponent(reviewDate)}` : "";
    const response = await fetch(`/api/reviews${suffix}`, { cache: "no-store" });
    if (!response.ok) throw new Error("review unavailable");
    state.review = await response.json();
    const subject = state.review.subjects?.[0];
    const resourceId = subject?.book_id || subject?.subject_key || "daily-review";
    startWorkspaceTimer({
      activity_type: "review",
      domain: subject?.domain || "medicine",
      subject_id: "daily-review",
      resource_id: resourceId,
      item_id: state.review.review_date,
      resume_target: { view: "review", resource_id: resourceId, item_id: state.review.review_date }
    });
    renderReviewUnified();
  } catch {
    $("reviewSummary").textContent = "暂时无法读取本地复习内容";
    $("reviewEmpty").classList.remove("hidden");
  }
}

export function scheduleDailySummarySave() {
  if (!state.review) return;
  const content = $("reviewDailySummary").value;
  $("reviewSummarySaved").textContent = "保存中…";
  window.clearTimeout(state.reviewSummarySaveTimer);
  state.reviewSummarySaveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/review-summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: state.review.review_date, content, no_text: false })
      });
      if (!response.ok) throw new Error("save failed");
      const result = await response.json();
      state.review = result.review;
      renderReviewUnified();
      loadStats();
    } catch {
      $("reviewSummarySaved").textContent = "保存失败，请稍后重试";
    }
  }, 420);
}

export async function markReviewNoText() {
  if (!state.review) return;
  $("reviewSummarySaved").textContent = "保存中…";
  try {
    const response = await fetch("/api/review-summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: state.review.review_date, content: "", no_text: true })
    });
    if (!response.ok) throw new Error("save failed");
    const result = await response.json();
    state.review = result.review;
    renderReviewUnified();
  } catch {
    $("reviewSummarySaved").textContent = "保存失败，请稍后重试";
  }
}