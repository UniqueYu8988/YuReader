import { homeActivityTargetKey, resumeActivityTarget, selectLibraryShelf } from "../core/router.js";
import { openOralFocusIndex } from "../modules/oral_focus.js";
import { $, state } from "../core/state.js";
import { escapeHtml, formatDuration, formatInteger, refreshIcons } from "../core/utils.js";
import { openReview, reviewDateLabel } from "./review.js";

export function activityTypeLabel(type) {
  return ({ read: "阅读", objective_practice: "客观题", subjective_practice: "主观题", notebook: "笔记", review: "回顾" })[type] || "学习";
}

export function activityLevel(count, maximum) {
  if (!count || !maximum) return 0;
  return Math.min(4, Math.max(1, Math.ceil((Math.log(count + 1) / Math.log(maximum + 1)) * 4)));
}

let goalsInitialized = false;

function formatHours(seconds) {
  const hours = seconds / 3600;
  return hours >= 10 ? hours.toFixed(0) : hours.toFixed(1);
}

function calculatePercent(current, target) {
  if (!target || target <= 0) return 0;
  return Math.min(100, Math.max(0, Math.round((current / target) * 100)));
}

export function updateGoalsUI(data) {
  if (!data) return;
  state.dailyGoalsData = data;
  const goals = data.goals || {};
  const progress = data.progress || {};
  const readingGoals = goals.reading || {};
  const readingProg = progress.reading || {};
  const practiceGoals = goals.practice || {};
  const practiceProg = progress.practice || {};

  // 1. Total study duration
  const totalTargetHours = goals.total_hours || 8.0;
  const totalCurrSeconds = progress.total_seconds || 0;
  const totalCurrHours = totalCurrSeconds / 3600;
  const totalPercent = calculatePercent(totalCurrHours, totalTargetHours);

  const totalStatusEl = $("homeGoalTotalStatus");
  const totalPercentEl = $("homeGoalTotalPercent");
  const totalFillEl = $("homeGoalTotalFill");
  const totalInput = $("homeGoalTotalInput");
  if (totalStatusEl) totalStatusEl.textContent = `${formatHours(totalCurrSeconds)} / ${totalTargetHours.toFixed(1)} 小时`;
  if (totalPercentEl) totalPercentEl.textContent = `${totalPercent}%`;
  if (totalFillEl) totalFillEl.style.width = `${totalPercent}%`;
  if (totalInput && !state.goalsEditMode) totalInput.value = totalTargetHours;

  // 2. Reading goals
  const medReadGoal = readingGoals.medicine_hours || 2.0;
  const medReadSec = readingProg.medicine_seconds || 0;
  const medReadPct = calculatePercent(medReadSec / 3600, medReadGoal);
  const medReadStatus = $("homeGoalMedReadStatus");
  const medReadFill = $("homeGoalMedReadFill");
  const medReadInput = $("homeGoalMedReadInput");
  if (medReadStatus) medReadStatus.textContent = `${formatHours(medReadSec)} / ${medReadGoal.toFixed(1)} 小时 (${medReadPct}%)`;
  if (medReadFill) medReadFill.style.width = `${medReadPct}%`;
  if (medReadInput && !state.goalsEditMode) medReadInput.value = medReadGoal;

  const polReadGoal = readingGoals.politics_hours || 0.5;
  const polReadSec = readingProg.politics_seconds || 0;
  const polReadPct = calculatePercent(polReadSec / 3600, polReadGoal);
  const polReadStatus = $("homeGoalPolReadStatus");
  const polReadFill = $("homeGoalPolReadFill");
  const polReadInput = $("homeGoalPolReadInput");
  if (polReadStatus) polReadStatus.textContent = `${formatHours(polReadSec)} / ${polReadGoal.toFixed(1)} 小时 (${polReadPct}%)`;
  if (polReadFill) polReadFill.style.width = `${polReadPct}%`;
  if (polReadInput && !state.goalsEditMode) polReadInput.value = polReadGoal;

  const engReadGoal = readingGoals.english_hours || 0.5;
  const engReadSec = readingProg.english_seconds || 0;
  const engReadPct = calculatePercent(engReadSec / 3600, engReadGoal);
  const engReadStatus = $("homeGoalEngReadStatus");
  const engReadFill = $("homeGoalEngReadFill");
  const engReadInput = $("homeGoalEngReadInput");
  if (engReadStatus) engReadStatus.textContent = `${formatHours(engReadSec)} / ${engReadGoal.toFixed(1)} 小时 (${engReadPct}%)`;
  if (engReadFill) engReadFill.style.width = `${engReadPct}%`;
  if (engReadInput && !state.goalsEditMode) engReadInput.value = engReadGoal;

  // 3. Practice goals
  const medDefGoal = practiceGoals.medicine_definition || 20;
  const medDefCount = practiceProg.medicine_definition || 0;
  const medDefPct = calculatePercent(medDefCount, medDefGoal);
  const medDefStatus = $("homeGoalMedDefStatus");
  const medDefFill = $("homeGoalMedDefFill");
  const medDefInput = $("homeGoalMedDefInput");
  if (medDefStatus) medDefStatus.textContent = `${medDefCount} / ${medDefGoal} 个 (${medDefPct}%)`;
  if (medDefFill) medDefFill.style.width = `${medDefPct}%`;
  if (medDefInput && !state.goalsEditMode) medDefInput.value = medDefGoal;

  const medEssayGoal = practiceGoals.medicine_essay || 20;
  const medEssayCount = practiceProg.medicine_essay || 0;
  const medEssayPct = calculatePercent(medEssayCount, medEssayGoal);
  const medEssayStatus = $("homeGoalMedEssayStatus");
  const medEssayFill = $("homeGoalMedEssayFill");
  const medEssayInput = $("homeGoalMedEssayInput");
  if (medEssayStatus) medEssayStatus.textContent = `${medEssayCount} / ${medEssayGoal} 个 (${medEssayPct}%)`;
  if (medEssayFill) medEssayFill.style.width = `${medEssayPct}%`;
  if (medEssayInput && !state.goalsEditMode) medEssayInput.value = medEssayGoal;

  const polUnitGoal = practiceGoals.politics_units || 2;
  const polUnitCount = practiceProg.politics_units || 0;
  const polUnitPct = calculatePercent(polUnitCount, polUnitGoal);
  const polUnitStatus = $("homeGoalPolUnitStatus");
  const polUnitFill = $("homeGoalPolUnitFill");
  const polUnitInput = $("homeGoalPolUnitInput");
  if (polUnitStatus) polUnitStatus.textContent = `${polUnitCount} / ${polUnitGoal} 单元 (${polUnitPct}%)`;
  if (polUnitFill) polUnitFill.style.width = `${polUnitPct}%`;
  if (polUnitInput && !state.goalsEditMode) polUnitInput.value = polUnitGoal;

  const engCompGoal = practiceGoals.english_reading || 2;
  const engCompCount = practiceProg.english_reading || 0;
  const engCompPct = calculatePercent(engCompCount, engCompGoal);
  const engCompStatus = $("homeGoalEngReadCompStatus");
  const engCompFill = $("homeGoalEngReadCompFill");
  const engCompInput = $("homeGoalEngReadCompInput");
  if (engCompStatus) engCompStatus.textContent = `${engCompCount} / ${engCompGoal} 篇 (${engCompPct}%)`;
  if (engCompFill) engCompFill.style.width = `${engCompPct}%`;
  if (engCompInput && !state.goalsEditMode) engCompInput.value = engCompGoal;
  updateChecklistUI();
}

export async function fetchDailyGoals() {
  try {
    const res = await fetch("/api/daily-goals");
    if (res.ok) {
      const data = await res.json();
      updateGoalsUI(data);
    }
  } catch (err) {
    console.warn("Failed to fetch daily goals:", err);
  }
}

export async function saveDailyGoals() {
  const payload = {
    total_hours: parseFloat($("homeGoalTotalInput")?.value) || 8.0,
    reading: {
      medicine_hours: parseFloat($("homeGoalMedReadInput")?.value) || 0,
      politics_hours: parseFloat($("homeGoalPolReadInput")?.value) || 0,
      english_hours: parseFloat($("homeGoalEngReadInput")?.value) || 0,
    },
    practice: {
      medicine_definition: parseInt($("homeGoalMedDefInput")?.value, 10) || 0,
      medicine_essay: parseInt($("homeGoalMedEssayInput")?.value, 10) || 0,
      politics_units: parseInt($("homeGoalPolUnitInput")?.value, 10) || 0,
      english_reading: parseInt($("homeGoalEngReadCompInput")?.value, 10) || 0,
    },
  };

  try {
    const res = await fetch("/api/daily-goals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      await fetchDailyGoals();
    }
  } catch (err) {
    console.error("Failed to save daily goals:", err);
  }
}

function initGoalsListeners() {
  if (goalsInitialized) return;
  const toggleBtn = $("homeGoalsEditToggle");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", async () => {
      state.goalsEditMode = !state.goalsEditMode;
      const isEdit = state.goalsEditMode;

      // Update button text and icon
      const textEl = $("homeGoalsEditToggleText");
      if (textEl) textEl.textContent = isEdit ? "保存目标" : "编辑目标";
      toggleBtn.innerHTML = `<i data-lucide="${isEdit ? "check" : "edit-3"}"></i><span id="homeGoalsEditToggleText">${isEdit ? "保存目标" : "编辑目标"}</span>`;
      refreshIcons();

      // Toggle edit inputs
      const totalWrap = $("homeGoalTotalInputWrap");
      if (totalWrap) totalWrap.classList.toggle("hidden", !isEdit);

      document.querySelectorAll(".goal-item-edit").forEach((el) => {
        el.classList.toggle("hidden", !isEdit);
      });

      if (!isEdit) {
        // Save upon exiting edit mode
        await saveDailyGoals();
      }
    });

    document.querySelectorAll(".reader-home-goal-item[data-goal-target]").forEach((item) => {
      item.addEventListener("click", (event) => {
        if (state.goalsEditMode || event.target.closest(".goal-item-edit") || event.target.tagName === "INPUT") return;
        const target = item.dataset.goalTarget;
        if (target === "med-read") {
          selectLibraryShelf("medicine");
        } else if (target === "med-def") {
          openOralFocusIndex(undefined, "definition");
        } else if (target === "med-essay") {
          openOralFocusIndex(undefined, "essay");
        } else if (target === "eng-read") {
          selectLibraryShelf("english");
        } else if (target === "eng-comp") {
          state.englishCenterType = "reading";
          selectLibraryShelf("english");
        } else if (target === "pol-read" || target === "pol-unit") {
          selectLibraryShelf("politics");
        }
      });
    });

    goalsInitialized = true;
  }
}

export function updateExamCountdown() {
  const dDayEl = $("ecDDayNumber");
  const stageLabelEl = $("ecCurrentStageLabel");
  if (!dDayEl) return;

  const examDate = new Date("2026-12-26T08:30:00+08:00");
  const now = new Date();
  const diffMs = examDate.getTime() - now.getTime();
  const diffDays = Math.max(0, Math.ceil(diffMs / (1000 * 60 * 60 * 24)));

  dDayEl.textContent = `D-${String(diffDays).padStart(3, "0")}`;

  let stageNum = 1;
  let stageText = "当前：一轮知识奠基与深度精读";
  if (diffDays <= 30) {
    stageNum = 3;
    stageText = "当前：三轮全真模拟冲刺与核心名解狂背";
  } else if (diffDays <= 120) {
    stageNum = 2;
    stageText = "当前：二轮真题强化攻坚与错题精准斩杀";
  } else {
    stageNum = 1;
    stageText = "当前：一轮全面教材精读与考点筑基";
  }

  if (stageLabelEl) stageLabelEl.textContent = stageText;

  document.querySelectorAll(".ec-stage-pill").forEach((pill) => {
    const stage = parseInt(pill.dataset.stage, 10);
    pill.classList.toggle("active", stage === stageNum);
    pill.classList.toggle("completed", stage < stageNum);
  });
}

let checklistInitialized = false;

export async function updateChecklistUI() {
  let oralDone = false;
  let mistakesDone = false;

  // 1. Oral focus due
  try {
    const res = await fetch("/api/oral-focus/due", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      const dueCount = data.total_due || 0;
      const chkOralCard = $("chkOralCard");
      const chkOralBadge = $("chkOralBadge");
      const chkOralDesc = $("chkOralDesc");
      if (dueCount > 0) {
        if (chkOralBadge) {
          chkOralBadge.textContent = `${dueCount} 词待复习`;
          chkOralBadge.className = "hci-status is-pending";
        }
        if (chkOralDesc) chkOralDesc.textContent = `${dueCount} 个考点待复习`;
        chkOralCard?.classList.remove("is-completed");
        oralDone = false;
      } else {
        if (chkOralBadge) {
          chkOralBadge.textContent = "已清空";
          chkOralBadge.className = "hci-status is-done";
        }
        if (chkOralDesc) chkOralDesc.textContent = "今日无到期复习";
        chkOralCard?.classList.add("is-completed");
        oralDone = true;
      }
    }
  } catch {}

  // 2. Mistakes
  try {
    const res = await fetch("/api/practice/mistakes", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      const count = data.pending ?? (data.total || 0);
      const chkMistakesCard = $("chkMistakesCard");
      const chkMistakesBadge = $("chkMistakesBadge");
      const chkMistakesDesc = $("chkMistakesDesc");
      if (count > 0) {
        if (chkMistakesBadge) {
          chkMistakesBadge.textContent = `${count} 题待攻坚`;
          chkMistakesBadge.className = "hci-status is-pending";
        }
        if (chkMistakesDesc) chkMistakesDesc.textContent = `${count} 道客观错题待消灭`;
        chkMistakesCard?.classList.remove("is-completed");
        mistakesDone = false;
      } else {
        if (chkMistakesBadge) {
          chkMistakesBadge.textContent = "已清空";
          chkMistakesBadge.className = "hci-status is-done";
        }
        if (chkMistakesDesc) chkMistakesDesc.textContent = "错题本已清零";
        chkMistakesCard?.classList.add("is-completed");
        mistakesDone = true;
      }
    }
  } catch {}

  // 3. Celebration Banner
  const celebration = $("homeChecklistCelebration");
  if (celebration) {
    celebration.classList.toggle("hidden", !(oralDone && mistakesDone));
  }
}

export function initChecklistListeners() {
  if (checklistInitialized) return;
  checklistInitialized = true;

  $("chkOralCard")?.addEventListener("click", () => openOralFocusIndex());
  $("chkMistakesCard")?.addEventListener("click", () => selectLibraryShelf("mistakes"));
}

export function renderHome() {
  const stats = state.stats || {};
  const today = stats.today ? new Date(`${stats.today}T00:00:00`) : new Date();
  $("homeDate").textContent = today.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
  $("homeGreeting").textContent = "今天继续学一点";
  const continuation = stats.continue_activity;
  const continueTarget = stats.continue_target || null;
  state.homeContinueTarget = continueTarget;
  if ($("homeLeadText")) $("homeLeadText").textContent = continuation ? `上次停在“${continuation.title}”` : "选择一本书，开始今天的学习";
  if ($("homeContinueLabel")) $("homeContinueLabel").textContent = continuation?.activity_label ? `继续${continuation.activity_label}` : "继续学习";
  if ($("homeContinueTitle")) $("homeContinueTitle").textContent = continuation?.title || "进入学习选择内容";
  const pending = stats.review_pending;
  $("homeTodayMinutes").textContent = formatInteger(Math.floor((stats.today_activity_seconds || 0) / 60));
  $("homeTodayActivities").textContent = `${formatInteger(stats.today_activity_count || 0)} 项活动`;
  $("homeTodayNotes").textContent = `${formatInteger(stats.today_note_count || 0)} 条笔记`;
  $("homeReviewMeta").textContent = pending ? `${reviewDateLabel(pending.date)} · ${formatInteger(pending.activity_count)} 条待整理` : "整理最近学习";

  initGoalsListeners();
  initChecklistListeners();
  fetchDailyGoals();
  updateChecklistUI();
  refreshIcons();
}

window.updateChecklistUI = updateChecklistUI;
