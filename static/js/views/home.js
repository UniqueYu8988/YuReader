import { homeActivityTargetKey, resumeActivityTarget } from "../core/router.js";
import { $, state } from "../core/state.js";
import { escapeHtml, formatDuration, formatInteger, refreshIcons } from "../core/utils.js";
import { reviewDateLabel } from "./review.js";

export function activityTypeLabel(type) {
  return ({ read: "阅读", objective_practice: "客观题", subjective_practice: "主观题", notebook: "笔记", review: "回顾" })[type] || "学习";
}

export function activityLevel(count, maximum) {
  if (!count || !maximum) return 0;
  return Math.min(4, Math.max(1, Math.ceil((Math.log(count + 1) / Math.log(maximum + 1)) * 4)));
}

export function renderHome() {
  const stats = state.stats || {};
  const today = stats.today ? new Date(`${stats.today}T00:00:00`) : new Date();
  $("homeDate").textContent = today.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  $("homeGreeting").textContent = "今天继续学一点";
  const continuation = stats.continue_activity;
  const continueTarget = stats.continue_target || null;
  state.homeContinueTarget = continueTarget;
  $("homeLeadText").textContent = continuation ? `上次停在“${continuation.title}”` : "选择一本书，开始今天的学习";
  $("homeContinueLabel").textContent = continuation?.activity_label ? `继续${continuation.activity_label}` : "继续学习";
  $("homeContinueTitle").textContent = continuation?.title || "进入学习库选择内容";
  const pending = stats.review_pending;
  $("homeTodayMinutes").textContent = formatInteger(Math.floor((stats.today_activity_seconds || 0) / 60));
  $("homeTodayActivities").textContent = `${formatInteger(stats.today_activity_count || 0)} 项活动`;
  $("homeTodayNotes").textContent = `${formatInteger(stats.today_note_count || 0)} 条笔记`;
  $("homeReviewMeta").textContent = pending ? `${reviewDateLabel(pending.date)} · ${formatInteger(pending.activity_count)} 条待整理` : "整理最近学习";

  state.homeResumeTargets.clear();
  const todayActivities = stats.today_activities || [];
  $("homeTracePanel").classList.toggle("hidden", !todayActivities.length);
  $("homeTraceList").innerHTML = todayActivities.map((item, index) => {
    const key = homeActivityTargetKey("activity", index); state.homeResumeTargets.set(key, item.resume_target);
    return `<button class="reader-home-trace-row" type="button" data-home-resume="${key}"><span><strong>${escapeHtml(item.activity_label || activityTypeLabel(item.activity_type))}</strong><small>${escapeHtml(item.title || item.item_id || "学习条目")} · ${escapeHtml(item.subject_id || item.domain || "")}</small></span><span>${formatDuration(item.duration_seconds, true)}</span><i data-lucide="arrow-up-right"></i></button>`;
  }).join("");
  $("homeTraceList").querySelectorAll("[data-home-resume]").forEach((button) => button.addEventListener("click", () => resumeActivityTarget(state.homeResumeTargets.get(button.dataset.homeResume))));
  refreshIcons();
}