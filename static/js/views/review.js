import { setActiveView, setRouteHash } from "../core/router.js";
import { $, state } from "../core/state.js";
import { startWorkspaceTimer, stopReadingTimer } from "../core/timer.js";
import { refreshIcons, renderMarkdown } from "../core/utils.js";
import { loadStats } from "./logs.js";
import { closeNotePopover } from "./reader.js";

export function reviewDateLabel(value) {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
}

export function setReviewPanel() {
  document.querySelector(".review-heading").classList.remove("hidden");
  $("reviewEmpty").classList.add("hidden");
  $("reviewReportPanel").classList.remove("hidden");
}

export function renderReviewUnified() {
  const review = state.review;
  const sourceCount = review?.source_count || 0;
  $("reviewTitle").textContent = review ? `${reviewDateLabel(review.review_date)}的回顾` : "回顾";
  $("reviewSummary").textContent = review ? `${sourceCount} 条真实学习来源 · 一次性回顾` : "正在整理最近的学习活动…";
  $("reviewProgressText").textContent = review?.review_done ? "已完成" : "待回顾";
  $("reviewCombinedDocument").innerHTML = renderMarkdown(review?.combined_markdown || "暂无可归档的学习产出；原始活动记录仍可从记录页查看。");
  $("reviewDailySummary").value = review?.review_result || "";
  $("reviewSummarySaved").textContent = review?.review_done ? (review.review_no_text ? "已标记为无文本回顾" : "已保存为独立学习记录") : `${sourceCount} 条来源 · 粘贴后保存为独立学习记录`;
  $("reviewLogObsidian").href = review?.learning_record_uri || review?.log_uri || "obsidian://open";
  setReviewPanel(); refreshIcons(); window.scrollTo({ top: 0, behavior: "auto" });
}

export async function openReview(reviewDate = "") {
  if (typeof reviewDate !== "string") reviewDate = "";
  setRouteHash("review");
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("review"); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const suffix = reviewDate ? `?date=${encodeURIComponent(reviewDate)}` : "";
    const response = await fetch(`/api/reviews${suffix}`, { cache: "no-store" });
    if (!response.ok) throw new Error("review unavailable");
    state.review = await response.json();
    const subject = state.review.subjects?.[0];
    const resourceId = subject?.book_id || subject?.subject_key || "daily-review";
    startWorkspaceTimer({ activity_type: "review", domain: subject?.domain || "medicine", subject_id: "daily-review", resource_id: resourceId, item_id: state.review.review_date, resume_target: { view: "review", resource_id: resourceId, item_id: state.review.review_date } });
    renderReviewUnified();
  } catch {
    $("reviewSummary").textContent = "暂时无法读取本地复习内容"; $("reviewEmpty").classList.remove("hidden");
  }
}

export function scheduleDailySummarySave() {
  if (!state.review) return; const content = $("reviewDailySummary").value; $("reviewSummarySaved").textContent = "保存中…"; window.clearTimeout(state.reviewSummarySaveTimer);
  state.reviewSummarySaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/review-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: state.review.review_date, content, no_text: false }) }); if (!response.ok) throw new Error("save failed"); const result = await response.json(); state.review = result.review; renderReviewUnified(); loadStats(); } catch { $("reviewSummarySaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

export async function markReviewNoText() {
  if (!state.review) return;
  $("reviewSummarySaved").textContent = "保存中…";
  try {
    const response = await fetch("/api/review-summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: state.review.review_date, content: "", no_text: true }) });
    if (!response.ok) throw new Error("save failed");
    const result = await response.json(); state.review = result.review; renderReviewUnified();
  } catch { $("reviewSummarySaved").textContent = "保存失败，请稍后重试"; }
}