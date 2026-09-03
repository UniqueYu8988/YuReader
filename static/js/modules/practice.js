import { selectLibraryShelf, setActiveView, setHomeMode, setLibraryMode, setReaderMode } from "../core/router.js";
import { $, state } from "../core/state.js";
import { startWorkspaceTimer, stopReadingTimer, stopWorkspaceTimer } from "../core/timer.js";
import { escapeHtml, formatInteger, refreshIcons, renderMarkdown, showToast } from "../core/utils.js";
import { openEnglishExamOverview, renderEnglishExams } from "../domains/english.js";
import { loadStats } from "../views/logs.js";
import { closeNotePopover, openResource } from "../views/reader.js";

export function subjectiveModeCopy(mode, prompt = "") {
  if (mode === "translation") return { label: "翻译练习", answerLabel: "我的译文", hint: "按题号完成目标句，再对照参考解析", placeholder: "按题号输入译文，例如：46. ……", icon: "languages" };
  if (mode === "writing-a") return { label: "应用文写作", answerLabel: "我的作文", hint: "先确认写作对象与任务，再完成一稿", placeholder: "在这里完成应用文（书信、通知或邮件）", icon: "mail-pen" };
  if (mode === "writing-b") return { label: "图画 / 图表写作", answerLabel: "我的作文", hint: "先描述材料，再解释寓意并给出评论", placeholder: "在这里完成图画或图表作文", icon: "chart-no-axes-combined" };
  return { label: "翻译与写作", answerLabel: "我的作答", hint: "按原卷顺序完成主观题，可在下方记录修改计划", placeholder: "在这里输入你的作答", icon: "pen-line" };
}

export function subjectiveDisplayTitle(value) {
  return String(value || "").replace(/\s*(?:（候选）|\(候选\)|候选包|候选)\s*$/i, "").trim();
}

export function subjectiveWordCount(value, mode) {
  const text = String(value || "").trim();
  if (!text) return 0;
  if (mode === "translation") return text.replace(/\s/g, "").length;
  return (text.match(/[A-Za-z]+(?:['’-][A-Za-z]+)*/g) || []).length;
}

export function subjectiveWordTarget(payload) {
  const source = String(payload?.prompt_markdown || "");
  if (payload?.mode === "translation") {
    const count = (source.match(/\(\d+\)/g) || []).length;
    return count ? `${count} 个目标句` : "按原题要求完成";
  }
  const range = source.match(/(?:about|around|approximately)\s+(\d+(?:\s*[-–]\s*\d+)?)\s*words?/i) || source.match(/(\d+(?:\s*[-–]\s*\d+)?)\s*words?/i);
  return range ? `原题要求约 ${range[1].replace(/\s+/g, "")} 词` : "按原题字数完成";
}

export function renderSubjectiveLoading() {
  $("subjectivePracticeEyebrow").textContent = "主观题练习";
  $("subjectivePracticeTitle").textContent = "正在读取题目…";
  $("subjectivePracticeMeta").textContent = "原题与解析保持独立，作答会自动保存。";
  $("subjectivePromptBody").innerHTML = `<p class="practice-reading-loading">正在读取题目与材料…</p>`;
  $("subjectiveReferencePanel").classList.add("hidden");
  $("subjectiveAnswer").value = ""; $("subjectiveReflection").value = "";
}

export function renderSubjectivePractice(payload) {
  const copy = subjectiveModeCopy(payload.mode, payload.prompt_markdown);
  const response = payload.response || {};
  state.subjectivePractice = { ...payload, referenceVisible: false };
  $("subjectivePracticeEyebrow").textContent = `${copy.label} · 原卷主观题`;
  $("subjectivePracticeTitle").textContent = payload.title || copy.label;
  $("subjectivePracticeMeta").textContent = `${payload.subject || "考研英语"} · ${subjectiveDisplayTitle(payload.chapter_title || "主观题")} · ${payload.storage === "obsidian" ? "已连接 Obsidian" : "本机保存"}`;
  $("subjectivePromptMeta").textContent = payload.reference_available ? "原题保持原样 · 参考解析可稍后展开" : "原题保持原样 · 暂无独立参考解析";
  const imageBase = payload.book_id ? `/api/book-assets/${encodeURIComponent(payload.book_id)}/` : "";
  $("subjectivePromptBody").innerHTML = renderMarkdown(payload.prompt_markdown || "暂无题目内容", imageBase);
  $("subjectiveAnswerLabel").textContent = copy.answerLabel;
  $("subjectiveAnswerHint").textContent = copy.hint;
  $("subjectiveAnswer").placeholder = copy.placeholder;
  $("subjectiveAnswer").value = String(response.answer || "");
  $("subjectiveReflection").value = String(response.reflection || "");
  $("subjectiveWordTarget").textContent = subjectiveWordTarget(payload);
  $("subjectivePracticeStatus").textContent = response.answer || response.reflection ? "已载入上次保存" : "输入后自动保存";
  $("subjectivePracticeObsidian").href = payload.obsidian_uri || "obsidian://open";
  $("subjectiveReferenceBody").innerHTML = payload.reference_available ? renderMarkdown(payload.reference_markdown, imageBase) : `<p class="subjective-reference-empty">这个年份的本地资料没有独立的翻译 / 作文解析页。可以直接把题目交给侧边栏 Gemini 批改，结果会保存到本练习记录。</p>`;
  $("subjectiveReferencePanel").classList.add("hidden");
  const reveal = $("subjectiveRevealReference"); reveal.disabled = !payload.reference_available; reveal.innerHTML = `<span>${payload.reference_available ? "查看参考解析" : "暂无独立解析"}</span><i data-lucide="${payload.reference_available ? "arrow-down" : "minus"}"></i>`;
  updateSubjectiveWordCount(); refreshIcons();
}

export function updateSubjectiveWordCount() {
  const payload = state.subjectivePractice; if (!payload) return;
  const count = subjectiveWordCount($("subjectiveAnswer").value, payload.mode);
  $("subjectiveWordCount").textContent = payload.mode === "translation" ? `${formatInteger(count)} 字符` : `${formatInteger(count)} 词`;
}

export async function openSubjectivePractice(bookId, sectionId) {
  if (!bookId || !sectionId) return;
  const requestId = ++state.openRequest;
  stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden");
  state.practice = null; state.subjectivePractice = null; state.subjectiveSaveTimer = null;
  state.practiceOverviewBankId = state.englishExamOverviewBankId || "";
  $("practiceWorkspace").classList.add("hidden"); $("subjectivePracticeWorkspace").classList.remove("hidden");
  setActiveView("practice"); renderSubjectiveLoading(); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const query = new URLSearchParams({ section_id: sectionId });
    const response = await fetch(`/api/subjective/practice?${query}`, { cache: "no-store" });
    if (!response.ok) throw new Error("subjective unavailable");
    const payload = await response.json();
    if (requestId !== state.openRequest) return;
    startWorkspaceTimer({ activity_type: "subjective_practice", domain: "english", subject_id: payload.subject || payload.book_id, resource_id: payload.book_id, item_id: payload.section_id, resume_target: { view: "subjective_practice", resource_id: payload.book_id, item_id: payload.section_id } });
    renderSubjectivePractice(payload);
  } catch {
    if (requestId !== state.openRequest) return;
    $("subjectivePracticeTitle").textContent = "暂时无法读取主观题";
    $("subjectivePracticeMeta").textContent = "请返回试卷导览后重试。";
    $("subjectivePromptBody").innerHTML = `<p class="practice-reading-empty">这份主观题资料暂时不可用。</p>`;
    showToast("主观题资料读取失败");
  }
}

export function returnFromSubjectivePractice() {
  window.clearTimeout(state.subjectiveSaveTimer); state.subjectiveSaveTimer = null;
  state.subjectivePractice = null; $("subjectivePracticeWorkspace").classList.add("hidden"); $("practiceWorkspace").classList.remove("hidden");
  if (state.subjectiveReturn === "learning-center") { state.subjectiveReturn = "exam-overview"; selectLibraryShelf("english"); }
  else if (state.practiceOverviewBankId) openEnglishExamOverview(state.practiceOverviewBankId);
  else setLibraryMode();
}

export function toggleSubjectiveReference() {
  const payload = state.subjectivePractice; if (!payload?.reference_available) return;
  payload.referenceVisible = !payload.referenceVisible;
  const panel = $("subjectiveReferencePanel"); panel.classList.toggle("hidden", !payload.referenceVisible);
  const button = $("subjectiveRevealReference"); button.innerHTML = `<span>${payload.referenceVisible ? "收起参考解析" : "查看参考解析"}</span><i data-lucide="${payload.referenceVisible ? "arrow-up" : "arrow-down"}"></i>`;
  if (payload.referenceVisible) window.setTimeout(() => panel.scrollIntoView({ behavior: "smooth", block: "start" }), 30);
  refreshIcons();
}

export function scheduleSubjectiveSave() {
  const payload = state.subjectivePractice; if (!payload) return;
  updateSubjectiveWordCount();
  const answer = $("subjectiveAnswer").value; const reflection = $("subjectiveReflection").value;
  $("subjectivePracticeStatus").textContent = "保存中…"; window.clearTimeout(state.subjectiveSaveTimer);
  state.subjectiveSaveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/subjective/response", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ section_id: payload.section_id, answer, reflection }) });
      if (!response.ok) throw new Error("subjective save failed");
      const result = await response.json(); payload.response = result.response || {}; payload.obsidian_uri = result.obsidian_uri || payload.obsidian_uri;
      $("subjectivePracticeObsidian").href = payload.obsidian_uri || "obsidian://open";
      $("subjectivePracticeStatus").textContent = answer.trim() || reflection.trim() ? (result.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
    } catch { $("subjectivePracticeStatus").textContent = "保存失败，请稍后重试"; }
  }, 420);
}

export function practiceEntryLabel(entry) {
  return entry.match_level === "comprehensive" ? "综合测试" : entry.match_level === "chapter" ? "本章练习" : "本节练习";
}

export function concisePracticeBankTitle(title) {
  const value = String(title || "").trim();
  if (value.includes("拔高")) return "拔高题库";
  if (value.includes("基础")) return "基础题库";
  return value.replace(/(?:综合测试)?题库$/, "") || "真实题库";
}

export async function loadSectionPractice() {
  const button = $("readerPractice"); button.classList.add("hidden"); button.replaceWith(button.cloneNode(true));
  const fresh = $("readerPractice");
  if (!state.current?.book_id || !state.current?.id) return;
  const sectionId = state.current.id;
  try {
    const response = await fetch(`/api/practice/availability?book_id=${encodeURIComponent(state.current.book_id)}&section_id=${encodeURIComponent(state.current.id)}`, { cache: "no-store" });
    if (!response.ok || state.current?.id !== sectionId) return;
    const payload = await response.json(); const entry = payload.entries?.[0];
    if (!entry) return;
    const label = `${practiceEntryLabel(entry)}，${entry.question_count}题`;
    fresh.classList.remove("hidden"); fresh.title = label; fresh.setAttribute("aria-label", label);
    fresh.addEventListener("click", () => openPractice(entry, "reader")); refreshIcons();
  } catch { /* A missing practice package must not disturb reading. */ }
}

export async function loadResourcePractice(bookId) {
  const container = $("resourcePractice"); container.classList.add("hidden"); container.innerHTML = "";
  try {
    const response = await fetch(`/api/practice/availability?book_id=${encodeURIComponent(bookId)}`, { cache: "no-store" });
    if (!response.ok || state.resourceBookId !== bookId) return;
    const payload = await response.json(); const entry = payload.entries?.[0];
    if (!entry) return;
    let groups = [];
    if (entry.match_level === "comprehensive") {
      try {
        const overviewResponse = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(entry.bank_id)}`, { cache: "no-store" });
        const overview = overviewResponse.ok ? await overviewResponse.json() : {};
        const subject = state.resource?.book?.subject || state.resource?.book?.title || "";
        groups = (overview.groups || []).filter((group) => group.kind === "objective" && (!subject || String(group.label || "").includes(subject)));
      } catch { groups = []; }
    }
    container.classList.remove("hidden");
    if (groups.length > 1) {
      container.innerHTML = `<div class="resource-practice-list">${groups.map((group, index) => `<button type="button" data-practice-group="${index}"><i data-lucide="circle-dot-dashed"></i><span><strong>${escapeHtml(group.label)}</strong><small>${group.answered_count || 0} / ${group.question_count} 已答</small></span><i data-lucide="arrow-right"></i></button>`).join("")}</div>`;
      container.querySelectorAll("[data-practice-group]").forEach((button) => button.addEventListener("click", () => { const group = groups[Number(button.dataset.practiceGroup)]; openPractice({ ...entry, unit_label: group.label, unit_key: group.key }, "resource"); }));
    } else {
      container.innerHTML = `<button class="resource-continue" type="button"><span><small>真实题库</small><strong>${practiceEntryLabel(entry)} · ${entry.question_count} 题</strong></span><i data-lucide="arrow-right"></i></button>`;
      container.querySelector("button").addEventListener("click", () => openPractice(entry, "resource"));
    }
    refreshIcons();
  } catch { /* The resource page remains usable without a bank. */ }
}

export async function openPractice(entry, returnTo, startIndex = 0) {
  state.openRequest += 1;
  stopReadingTimer();
  closeNotePopover();
  $("sectionNoteFloat")?.classList.add("hidden");
  $("oralFocusNoteFloat")?.classList.add("hidden");
  $("reviewNoteFloat")?.classList.add("hidden");
  $("practiceNoteFloat")?.classList.remove("hidden");
  setPracticeNoteOpen(false);
  state.practiceReturn = returnTo;
  state.practiceOverviewBankId = returnTo === "english-exam-overview" ? entry.bank_id : "";
  state.practiceIndex = Math.max(0, Number(startIndex) || 0);
  state.subjectivePractice = null;
  $("subjectivePracticeWorkspace")?.classList.add("hidden");
  $("practiceWorkspace")?.classList.remove("hidden");
  try {
    const query = new URLSearchParams({ bank_id: entry.bank_id, knowledge_id: entry.knowledge_id, match_level: entry.match_level });
    const response = await fetch(`/api/practice/session?${query}`, { cache: "no-store" });
    if (!response.ok) throw new Error("practice unavailable");
    const session = await response.json();
    if (entry.unit_label) {
      const scoped = (session.questions || []).filter((question) => (question.unit_label || question.unit) === entry.unit_label);
      if (scoped.length) { session.questions = scoped; session.question_count = scoped.length; session.answered_count = scoped.filter((question) => question.answered).length; state.practiceIndex = 0; }
    }
    state.practice = { ...session, entry };
    setActiveView("practice");
    renderPracticeSessionMap();
    renderPracticeQuestion();
    window.scrollTo({ top: 0, behavior: "auto" });
  } catch { showToast("暂时无法读取这组题目"); }
}

export function practiceSessionStats() {
  const questions = state.practice?.questions || [];
  const answered = questions.filter((item) => item.answered).length;
  const correct = questions.filter((item) => item.answered && item.correct === true).length;
  const wrong = questions.filter((item) => item.answered && item.correct === false).length;
  return { total: questions.length, answered, correct, wrong, unanswered: Math.max(0, questions.length - answered) };
}

export function practiceUnitGroups() {
  const groups = [];
  (state.practice?.questions || []).forEach((question, index) => {
    const label = question.unit_label || question.unit || "本组题目";
    let group = groups[groups.length - 1];
    if (!group || group.label !== label) { group = { label, items: [] }; groups.push(group); }
    group.items.push({ ...question, index });
  });
  return groups;
}

export function renderPracticeSessionMap() {
  const map = $("practiceUnitMap"); if (!map || !state.practice) return;
  const stats = practiceSessionStats(); $("practiceSessionState").textContent = `${stats.answered} / ${stats.total} 已答${stats.wrong ? ` · ${stats.wrong} 题待梳理` : ""}`;
  map.innerHTML = practiceUnitGroups().map((group, groupIndex) => {
    const current = group.items.some((item) => item.index === state.practiceIndex);
    const answered = group.items.filter((item) => item.answered).length;
    return `<details class="practice-map-unit" ${current || groupIndex === 0 ? "open" : ""}><summary><span><strong>${escapeHtml(group.label)}</strong><small>${answered} / ${group.items.length} 已答</small></span><i data-lucide="chevron-right"></i></summary><nav>${group.items.map((item) => `<button class="practice-map-number${item.index === state.practiceIndex ? " current" : ""}${item.answered ? (item.correct ? " correct" : " wrong") : ""}" type="button" data-practice-index="${item.index}" aria-label="第 ${escapeHtml(item.local_number || item.index + 1)} 题${item.answered ? (item.correct ? "，已答对" : "，已答错") : "，未作答"}">${escapeHtml(item.local_number || item.index + 1)}</button>`).join("")}</nav></details>`;
  }).join("");
  map.querySelectorAll("[data-practice-index]").forEach((button) => button.addEventListener("click", () => {
    state.practiceIndex = Number(button.dataset.practiceIndex); $("practiceSessionMap").classList.add("hidden"); $("practiceMapToggle").setAttribute("aria-expanded", "false"); renderPracticeQuestion(); window.scrollTo({ top: 0, behavior: "auto" });
  }));
  refreshIcons();
}

export function togglePracticeSessionMap() {
  const panel = $("practiceSessionMap"); const nextOpen = panel.classList.contains("hidden");
  panel.classList.toggle("hidden", !nextOpen); $("practiceMapToggle").setAttribute("aria-expanded", String(nextOpen));
  $("practiceMapToggle").setAttribute("title", nextOpen ? "收起题组导航" : "打开题组导航");
  if (nextOpen) renderPracticeSessionMap();
}

export function finishPracticeSession() {
  if (!state.practice) return;
  const stats = practiceSessionStats(); stopWorkspaceTimer();
  $("practiceSessionMap").classList.add("hidden"); $("practiceMapToggle").setAttribute("aria-expanded", "false");
  $("practiceQuestionSurface").classList.add("hidden"); $("practiceResult").classList.add("hidden"); $("practicePagination").classList.add("hidden"); $("practiceSessionSummary").classList.remove("hidden");
  $("practiceSummaryFacts").innerHTML = `<div><span>已完成</span><strong>${stats.answered}</strong><small>共 ${stats.total} 题</small></div><div><span>回答正确</span><strong>${stats.correct}</strong><small>${stats.answered ? `${Math.round((stats.correct / stats.answered) * 100)}% 正确率` : "尚未作答"}</small></div><div><span>需要梳理</span><strong>${stats.wrong}</strong><small>可直接回到错题</small></div><div><span>未作答</span><strong>${stats.unanswered}</strong><small>下次继续完成</small></div>`;
  $("practiceReviewWrong").classList.toggle("hidden", !stats.wrong); loadStats(); refreshIcons(); window.scrollTo({ top: 0, behavior: "smooth" });
}

export function reviewFirstWrongPracticeQuestion() {
  const index = (state.practice?.questions || []).findIndex((item) => item.answered && item.correct === false);
  if (index < 0) return;
  state.practiceIndex = index; $("practiceSessionSummary").classList.add("hidden"); $("practiceQuestionSurface").classList.remove("hidden"); $("practicePagination").classList.remove("hidden"); renderPracticeQuestion(); window.scrollTo({ top: 0, behavior: "auto" });
}

export function isClozeQuestion(question) {
  return /完形填空/.test(String(question?.unit_label || question?.unit || ""));
}

export function practiceWorkflowHint(question) {
  const unit = String(question?.unit_label || question?.unit || "");
  if (/完形填空/.test(unit)) return "点击文章中的空格选择答案";
  if (/Part B/.test(unit)) return "为缺口选择合适段落";
  if (/阅读理解/.test(unit)) return "先读完整文章，再判断题干";
  return "先阅读材料，再作答";
}

export function prepareClozeMarkdown(markdown, count = 20) {
  const source = String(markdown || ""); let cursor = 0; let output = "";
  for (let number = 1; number <= count; number += 1) {
    const pattern = new RegExp(`(?<![\\d])${number}(?![\\d])`);
    let match = pattern.exec(source.slice(cursor));
    // A comma is valid punctuation after a blank ("4, you're"), but a
    // thousands separator is not a blank marker ("1,000").
    while (match) {
      const absoluteEnd = cursor + match.index + match[0].length;
      if (!(source[absoluteEnd] === "," && /^\d{3}(?!\d)/.test(source.slice(absoluteEnd + 1)))) break;
      const next = pattern.exec(source.slice(absoluteEnd));
      if (!next) { match = null; break; }
      match = { ...next, index: next.index + absoluteEnd - cursor };
    }
    if (!match) continue;
    const start = cursor + match.index; const end = start + match[0].length;
    output += source.slice(cursor, start) + `YUREADERCLOZE${number}TOKEN`; cursor = end;
  }
  return output + source.slice(cursor);
}

export function renderClozeContext(markdown, activeNumber) {
  const html = renderMarkdown(prepareClozeMarkdown(markdown));
  return html.replace(/YUREADERCLOZE(\d+)TOKEN/g, (_, value) => {
    const number = Number(value); const active = number === Number(activeNumber);
    return `<button class="cloze-blank${active ? " active" : ""}" type="button" data-cloze-index="${number}" aria-label="第 ${number} 空">${number}</button>`;
  });
}

export function renderClozeChoices(question, attempt = null) {
  const tray = $("practiceClozeChoices"); const cloze = isClozeQuestion(question);
  tray.classList.toggle("hidden", !cloze);
  if (!cloze) { tray.innerHTML = ""; return; }
  const selected = new Set(attempt?.selected_answers || [...$("practiceOptions").querySelectorAll("input:checked")].map((input) => input.value));
  const revealed = Boolean(attempt && Object.keys(attempt).length);
  const correct = new Set(question.correct_answers || []);
  const options = (question.options || []).map((option) => {
    const label = String(option.label || ""); const classes = ["cloze-choice"];
    if (selected.has(label)) classes.push("selected");
    if (revealed && correct.has(label)) classes.push("correct");
    if (revealed && selected.has(label) && !correct.has(label)) classes.push("incorrect");
    return `<button class="${classes.join(" ")}" type="button" data-cloze-answer="${escapeHtml(label)}"${revealed ? " disabled" : ""}><strong>${escapeHtml(label)}</strong><span>${renderMarkdown(option.text_md || "")}</span></button>`;
  }).join("");
  const number = question.local_number || state.practiceIndex + 1;
  tray.innerHTML = `<div class="cloze-choice-head"><strong>第 ${number} 空</strong><span>${revealed ? "已提交，可在下方查看解析" : "点击选项填入这个空"}</span></div><div class="cloze-choice-list">${options}</div>`;
  tray.querySelectorAll("[data-cloze-answer]").forEach((button) => button.addEventListener("click", () => {
    const input = $("practiceOptions").querySelector(`input[value="${button.dataset.clozeAnswer}"]`); if (!input || input.disabled) return;
    input.checked = true; updatePracticeOptionState(); renderClozeChoices(question, null);
  }));
}

export function focusClozeBlank(number) {
  const target = state.practice?.questions?.findIndex((item) => Number(item.local_number) === Number(number));
  if (target == null || target < 0) return;
  const focus = () => document.querySelector(`[data-cloze-index="${Number(number)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  if (target === state.practiceIndex) { focus(); return; }
  state.practiceIndex = target; renderPracticeQuestion().then(focus).catch(() => {});
}

export function isReadingComprehensionPractice(practice) {
  const entryLabel = String(practice?.entry?.label || practice?.entry?.unit_label || "");
  const first = practice?.questions?.[0] || {};
  const unit = String(first.unit_label || first.unit || "");
  return /阅读理解/.test(`${entryLabel} ${unit}`) && !/完形填空/.test(`${entryLabel} ${unit}`);
}

export function readingQuestionType(question) {
  return question?.question_type === "multiple_choice" ? "多项选择" : "单项选择";
}

export function readingAnswerStatus(payload) {
  if (!payload?.attempt) return "未作答";
  return payload.attempt.correct ? "已答 · 正确" : "已答 · 待梳理";
}

export function updateReadingProgress() {
  const practice = state.practice; if (!practice) return;
  const items = state.practiceReadingItems || [];
  const answered = items.filter((item) => item?.attempt).length;
  const total = items.length || practice.question_count || 0;
  $("practiceProgressText").textContent = `${answered} / ${total} 已答`;
  $("practiceReadingProgress").textContent = `${answered} / ${total} 已答`;
  $("practiceProgressBar").style.setProperty("--practice-progress", `${total ? (answered / total) * 100 : 0}%`);
}

export function readingQuestionHtml(payload, index) {
  const question = payload?.question || {};
  const attempt = payload?.attempt;
  const prior = attempt?.selected_answers || [];
  const revealed = Boolean(attempt);
  const inputType = question.question_type === "multiple_choice" ? "checkbox" : "radio";
  const options = (question.options || []).map((option) => {
    const label = String(option.label || "");
    const selected = prior.includes(label);
    const correct = revealed && (question.correct_answers || []).includes(label);
    const incorrect = revealed && selected && !correct;
    return `<label class="practice-option${selected ? " selected" : ""}${correct ? " correct" : ""}${incorrect ? " incorrect" : ""}"><input type="${inputType}" name="reading-answer-${index}" value="${escapeHtml(label)}" ${selected ? "checked" : ""}${revealed ? " disabled" : ""}><strong class="practice-option-label">${escapeHtml(label)}</strong><span class="practice-option-text">${renderMarkdown(option.text_md || "")}</span><span class="practice-option-state" aria-hidden="true">${correct ? '<i data-lucide="check"></i>' : (incorrect ? '<i data-lucide="x"></i>' : "")}</span></label>`;
  }).join("");
  const feedback = revealed ? `<section class="reading-question-feedback" aria-live="polite"><header><span class="practice-result-icon${attempt.correct ? "" : " wrong"}"><i data-lucide="${attempt.correct ? "check" : "x"}"></i></span><div><strong>${attempt.correct ? "回答正确" : "继续梳理这个知识点"}</strong><small>正确答案：${escapeHtml((question.correct_answers || []).join("、"))}</small></div></header><section class="reading-question-analysis"><h4>原书解析</h4><article class="knowledge-article">${renderMarkdown(question.source_analysis_md || "暂无原书解析")}</article></section><section class="reading-personal-analysis"><header><div><strong>个人解析</strong><small data-reading-analysis-status>${payload.personal_analysis?.trim() ? "已保存到练习笔记" : "粘贴侧边栏的分析，自动保存"}</small></div><a class="note-icon-button" href="obsidian://open" data-reading-obsidian aria-label="在 Obsidian 中打开练习笔记"><img src="/assets/obsidian.svg" alt=""></a></header><textarea rows="6" data-reading-analysis placeholder="粘贴侧边栏 AI 的解析，或写下自己的判断过程">${escapeHtml(payload.personal_analysis || "")}</textarea></section></section>` : "";
  return `<article class="reading-question-block" data-reading-index="${index}"><header class="reading-question-heading"><div><span>第 ${escapeHtml(question.local_number || index + 1)} 题</span><small>${escapeHtml(readingQuestionType(question))}</small></div><em data-reading-status>${readingAnswerStatus(payload)}</em></header><div class="knowledge-article reading-question-stem">${renderMarkdown(question.stem_md || "")}</div><div class="reading-question-options${revealed ? " is-revealed" : ""}">${options}</div><div class="reading-question-actions">${revealed ? "" : `<button class="secondary-button reading-question-submit" type="button" data-reading-submit="${index}"${prior.length ? "" : " disabled"}>提交答案</button>`}</div>${feedback}</article>`;
}

export function bindReadingQuestion(index) {
  const block = document.querySelector(`[data-reading-index="${index}"]`); const item = state.practiceReadingItems[index]; if (!block || !item) return;
  block.querySelectorAll(".practice-option input").forEach((input) => input.addEventListener("change", () => {
    block.querySelectorAll(".practice-option").forEach((option) => option.classList.toggle("selected", option.querySelector("input")?.checked));
    const submit = block.querySelector("[data-reading-submit]"); if (submit) submit.disabled = !block.querySelector("input:checked");
  }));
  block.querySelector("[data-reading-submit]")?.addEventListener("click", () => submitReadingAnswer(index));
  block.querySelector("[data-reading-analysis]")?.addEventListener("input", () => scheduleReadingAnalysisSave(index));
}

export function renderReadingQuestionBlock(index) {
  const block = document.querySelector(`[data-reading-index="${index}"]`); if (!block) return;
  block.outerHTML = readingQuestionHtml(state.practiceReadingItems[index], index);
  bindReadingQuestion(index); refreshIcons();
}

export async function submitReadingAnswer(index) {
  const item = state.practiceReadingItems[index]; const question = item?.question; const block = document.querySelector(`[data-reading-index="${index}"]`); if (!question || !block) return;
  const selected = [...block.querySelectorAll("input:checked")].map((input) => input.value); if (!selected.length) { showToast("请先选择答案"); return; }
  const submit = block.querySelector("[data-reading-submit]"); if (submit) { submit.disabled = true; submit.textContent = "提交中…"; }
  try {
    const response = await fetch("/api/practice/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, selected_answers: selected }) });
    if (!response.ok) throw new Error("answer failed");
    const result = await response.json(); state.practiceReadingItems[index] = { ...item, question: result.question, attempt: result.attempt };
    state.practice.questions[index] = { ...state.practice.questions[index], answered: true, correct: result.attempt.correct }; renderReadingQuestionBlock(index); updateReadingProgress();
  } catch { if (submit) { submit.disabled = false; submit.textContent = "提交答案"; } showToast("提交失败，请稍后重试"); }
}

export function scheduleReadingAnalysisSave(index) {
  const item = state.practiceReadingItems[index]; const question = item?.question; const block = document.querySelector(`[data-reading-index="${index}"]`); const textarea = block?.querySelector("[data-reading-analysis]"); if (!question || !item?.attempt || !textarea) return;
  const status = block.querySelector("[data-reading-analysis-status]"); const content = textarea.value; if (status) status.textContent = "保存中…"; window.clearTimeout(item.analysisSaveTimer);
  item.analysisSaveTimer = window.setTimeout(async () => {
    try {
      const response = await fetch("/api/practice/analysis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, content }) }); if (!response.ok) throw new Error("analysis failed");
      const result = await response.json(); item.personal_analysis = content; if (status) status.textContent = content.trim() ? "已保存到练习笔记" : "个人解析已清空"; const link = block.querySelector("[data-reading-obsidian]"); if (link) link.href = result.obsidian_uri || "obsidian://open";
    } catch { if (status) status.textContent = "保存失败，请稍后重试"; }
  }, 420);
}

export async function renderReadingComprehension() {
  const practice = state.practice; const requestId = state.openRequest; const layout = $("practiceReadingLayout"); const body = $("practiceReadingBody"); const questions = $("practiceReadingQuestions");
  state.practiceReadingToken += 1; const token = state.practiceReadingToken; state.practiceReadingItems = [];
  $("practiceWorkspace")?.classList.add("reading-comprehension-active"); $("practiceQuestionSurface").classList.add("is-reading-comprehension"); layout.classList.remove("hidden"); $("practiceResult").classList.add("hidden"); $("practicePagination").classList.add("hidden");
  $("practiceEyebrow").textContent = `${practice.entry?.label || "阅读理解"} · 真实题库`; $("practiceTitle").textContent = concisePracticeBankTitle(practice.bank.title); $("practiceTitle").title = practice.bank.title;
  $("practiceQuestionType").textContent = "阅读理解"; $("practiceQuestionNumber").textContent = "整篇阅读"; $("practiceMeta").textContent = `${practice.bank.subject} · ${practice.question_count} 题 · 先读完整文章，再自由选择题目作答`;
  $("practiceReadingMeta").textContent = `${practice.entry?.label || "阅读理解"} · ${practice.questions.length} 题`;
  body.innerHTML = `<p class="practice-reading-loading">正在读取整篇文章…</p>`; questions.innerHTML = `<p class="practice-reading-loading">正在读取全部题目…</p>`; updateReadingProgress();
  let results;
  try {
    results = await Promise.all(practice.questions.map(async (item) => { const query = new URLSearchParams({ bank_id: practice.bank.id, question_id: item.question_id }); const response = await fetch(`/api/practice/question?${query}`, { cache: "no-store" }); if (!response.ok) throw new Error("question unavailable"); return response.json(); }));
  } catch {
    if (requestId === state.openRequest && token === state.practiceReadingToken) { body.innerHTML = `<p class="practice-reading-empty">阅读原文暂时无法读取。</p>`; questions.innerHTML = `<p class="practice-reading-empty">题目暂时无法读取，请返回试卷导览后重试。</p>`; showToast("阅读理解题目读取失败"); }
    return;
  }
  if (requestId !== state.openRequest || token !== state.practiceReadingToken || state.practice !== practice) return;
  state.practiceReadingItems = results;
  const firstQuestion = results[0]?.question;
  if (firstQuestion) startWorkspaceTimer({ activity_type: "objective_practice", domain: practice.bank.domain || "english", subject_id: firstQuestion.subject_label || practice.bank.subject || practice.bank.id, resource_id: practice.bank.id, item_id: firstQuestion.question_id, resume_target: { view: "practice", resource_id: practice.bank.id, item_id: firstQuestion.question_id, question_id: firstQuestion.question_id } });
  const firstContext = results.map((item) => String(item.question?.context_md || "").trim()).find(Boolean) || ""; const paragraphCount = firstContext ? firstContext.split(/\n\s*\n/).filter((item) => item.trim()).length : 0;
  $("practiceReadingMeta").textContent = `${practice.entry?.label || "阅读理解"}${paragraphCount ? ` · ${paragraphCount} 段` : ""}`; body.innerHTML = firstContext ? renderMarkdown(firstContext) : `<p class="practice-reading-empty">这组题目没有附带可显示的阅读原文。</p>`; questions.innerHTML = results.map((item, index) => readingQuestionHtml(item, index)).join(""); results.forEach((_, index) => bindReadingQuestion(index)); updateReadingProgress(); refreshIcons();
}

export async function renderPracticeQuestion() {
  $("subjectivePracticeWorkspace")?.classList.add("hidden"); $("practiceWorkspace")?.classList.remove("hidden");
  $("practiceSessionSummary")?.classList.add("hidden"); $("practiceQuestionSurface")?.classList.remove("hidden");
  const practice = state.practice; const reading = isReadingComprehensionPractice(practice); $("practiceQuestionSurface").classList.toggle("is-reading-comprehension", reading); $("practiceReadingLayout").classList.toggle("hidden", !reading); $("practicePagination").classList.toggle("hidden", reading); $("practiceWorkspace")?.classList.toggle("reading-comprehension-active", reading);
  $("practiceMapToggle")?.classList.toggle("hidden", reading); $("practiceSessionMap")?.classList.add("hidden"); $("practiceMapToggle")?.setAttribute("aria-expanded", "false");
  if (reading) { await renderReadingComprehension(); return; }
  state.practiceReadingItems = [];
  await renderSinglePracticeQuestion();
}

export async function renderSinglePracticeQuestion() {
  const practice = state.practice; const item = practice?.questions?.[state.practiceIndex]; if (!item) return;
  $("practiceEyebrow").textContent = practice.entry.match_level === "comprehensive" ? "综合测试 · 真实题库" : `${practiceEntryLabel(practice.entry)} · 真实题库`;
  $("practiceTitle").textContent = concisePracticeBankTitle(practice.bank.title); $("practiceTitle").title = practice.bank.title; $("practiceMeta").textContent = `${practice.bank.subject} · ${practice.question_count} 题 · ${practiceWorkflowHint(item)}`;
  $("practiceProgressText").textContent = `${state.practiceIndex + 1} / ${practice.question_count}`; $("practiceProgressBar").style.setProperty("--practice-progress", `${((state.practiceIndex + 1) / practice.question_count) * 100}%`);
  $("practiceResult").classList.add("hidden"); $("practiceSubmit").classList.remove("hidden"); $("practiceSubmit").disabled = true;
  const query = new URLSearchParams({ bank_id: practice.bank.id, question_id: item.question_id }); const response = await fetch(`/api/practice/question?${query}`, { cache: "no-store" }); if (!response.ok) { showToast("题目读取失败"); return; }
  const payload = await response.json(); const question = payload.question; state.practice.question = payload;
  startWorkspaceTimer({ activity_type: "objective_practice", domain: question.domain || practice.bank.domain || "english", subject_id: question.subject_label || practice.bank.subject || practice.bank.id, resource_id: practice.bank.id, item_id: question.question_id, resume_target: { view: "practice", resource_id: practice.bank.id, item_id: question.question_id, question_id: question.question_id } });
  const unitLabel = question.unit_label || question.unit || "题目"; const answerType = question.question_type === "multiple_choice" ? "多项选择" : "单项选择";
  $("practiceMeta").textContent = `${practice.bank.subject} · ${practice.question_count} 题 · ${practiceWorkflowHint(question)}`;
  $("practiceQuestionType").textContent = `${unitLabel} · ${answerType}`; $("practiceQuestionNumber").textContent = `第 ${question.local_number || state.practiceIndex + 1} 题`;
  const context = String(question.context_md || "").trim(); const paragraphCount = context ? context.split(/\n\s*\n/).filter((item) => item.trim()).length : 0; const cloze = isClozeQuestion(question); $("practiceContext").classList.toggle("hidden", !context); $("practiceContext").open = Boolean(context); $("practiceContextLabel").textContent = context ? `${cloze ? "完形填空全文" : "阅读原文"} · ${unitLabel}${paragraphCount ? `（${paragraphCount}段）` : ""}` : "阅读原文"; $("practiceContextBody").innerHTML = context ? (cloze ? renderClozeContext(context, question.local_number) : renderMarkdown(context)) : "";
  $("practiceContextBody").querySelectorAll("[data-cloze-index]").forEach((button) => button.addEventListener("click", () => focusClozeBlank(Number(button.dataset.clozeIndex))));
  $("practiceStem").innerHTML = cloze ? `<p class="cloze-instruction">点击正文中的任意空格，选项会在正文下方出现。</p>` : renderMarkdown(question.stem_md || ""); const prior = payload.attempt?.selected_answers || [];
  $("practiceOptions").innerHTML = (question.options || []).map((option) => `<label class="practice-option${prior.includes(option.label) ? " selected" : ""}"><input type="${question.question_type === "multiple_choice" ? "checkbox" : "radio"}" name="practice-answer" value="${escapeHtml(option.label)}" ${prior.includes(option.label) ? "checked" : ""}><strong class="practice-option-label">${escapeHtml(option.label)}</strong><span class="practice-option-text">${renderMarkdown(option.text_md || "")}</span><span class="practice-option-state" aria-hidden="true"></span></label>`).join("");
  $("practiceOptions").classList.toggle("hidden", cloze); renderClozeChoices(question, payload.attempt);
  $("practiceOptions").querySelectorAll("input").forEach((input) => input.addEventListener("change", updatePracticeOptionState));
  updatePracticeOptionState();
  $("practicePrevious").disabled = state.practiceIndex === 0; const last = state.practiceIndex >= practice.question_count - 1; $("practiceNext").disabled = false; $("practiceNext").querySelector("span").textContent = last ? "完成本组" : "下一题";
  if (payload.attempt) showPracticeResult(payload); renderPracticeSessionMap(); refreshIcons();
}

export function showPracticeResult(payload) {
  const question = payload.question; const attempt = payload.attempt || {}; $("practiceSubmit").classList.add("hidden"); $("practiceResult").classList.remove("hidden");
  $("practiceResultTitle").textContent = attempt.correct ? "回答正确" : "继续梳理这个知识点"; $("practiceCorrectAnswer").textContent = `正确答案：${(question.correct_answers || []).join("、")}`;
  $("practiceResultIcon").classList.toggle("wrong", !attempt.correct); $("practiceResultIcon").innerHTML = `<i data-lucide="${attempt.correct ? "check" : "x"}"></i>`;
  const correct = new Set(question.correct_answers || []); const selected = new Set(attempt.selected_answers || []);
  $("practiceOptions").querySelectorAll(".practice-option").forEach((option) => {
    const input = option.querySelector("input"); const label = input.value; input.disabled = true;
    option.classList.toggle("correct", correct.has(label)); option.classList.toggle("incorrect", selected.has(label) && !correct.has(label));
    option.querySelector(".practice-option-state").innerHTML = correct.has(label) ? '<i data-lucide="check"></i>' : (selected.has(label) ? '<i data-lucide="x"></i>' : "");
  });
  renderClozeChoices(question, attempt); $("practiceSourceAnalysis").innerHTML = renderMarkdown(question.source_analysis_md || "暂无原书解析"); $("practicePersonalAnalysis").value = payload.personal_analysis || ""; $("practiceAnalysisSaved").textContent = payload.personal_analysis?.trim() ? "已保存到练习笔记" : "粘贴侧边栏的分析，自动保存"; refreshIcons();
}

export function updatePracticeOptionState() {
  const options = $("practiceOptions").querySelectorAll(".practice-option");
  options.forEach((option) => option.classList.toggle("selected", option.querySelector("input").checked));
  $("practiceSubmit").disabled = !$("practiceOptions").querySelector("input:checked");
}

export async function submitPracticeAnswer() {
  const question = state.practice?.question?.question; if (!question) return; const selected = [...document.querySelectorAll('#practiceOptions input:checked')].map((input) => input.value);
  if (!selected.length) { showToast("请先选择答案"); return; }
  $("practiceSubmit").disabled = true;
  try { const response = await fetch("/api/practice/answer", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, selected_answers: selected }) }); if (!response.ok) throw new Error("answer failed"); const result = await response.json(); state.practice.question = { ...state.practice.question, question: result.question, attempt: result.attempt }; showPracticeResult(state.practice.question); state.practice.questions[state.practiceIndex] = { ...state.practice.questions[state.practiceIndex], answered: true, correct: result.attempt.correct }; renderPracticeSessionMap(); } catch { $("practiceSubmit").disabled = false; showToast("提交失败，请稍后重试"); }
}

export function schedulePracticeAnalysisSave() {
  const question = state.practice?.question?.question; if (!question || !state.practice?.question?.attempt) return; const content = $("practicePersonalAnalysis").value; $("practiceAnalysisSaved").textContent = "保存中…"; window.clearTimeout(state.practiceAnalysisSaveTimer);
  state.practiceAnalysisSaveTimer = window.setTimeout(async () => { try { const response = await fetch("/api/practice/analysis", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ bank_id: question.bank_id, question_id: question.question_id, content }) }); if (!response.ok) throw new Error("analysis failed"); const result = await response.json(); $("practiceAnalysisSaved").textContent = content.trim() ? "已保存到练习笔记" : "个人解析已清空"; $("practiceObsidian").href = result.obsidian_uri || "obsidian://open"; } catch { $("practiceAnalysisSaved").textContent = "保存失败，请稍后重试"; } }, 420);
}

export function setPracticeNoteOpen(open) {
  state.practiceNoteOpen = Boolean(open);
  $("practiceNoteFloat")?.classList.toggle("note-is-open", state.practiceNoteOpen);
  $("practiceNotePopover")?.classList.toggle("is-open", state.practiceNoteOpen);
  $("practiceNotePopover")?.setAttribute("aria-hidden", String(!state.practiceNoteOpen));
  $("togglePracticeNoteDock")?.setAttribute("aria-expanded", String(state.practiceNoteOpen));
  if (state.practiceNoteOpen) window.setTimeout(() => $("practicePersonalAnalysis")?.focus(), 120);
}

export function returnFromPractice() {
  setPracticeNoteOpen(false);
  $("practiceNoteFloat")?.classList.add("hidden");
  if (state.practiceReturn === "home") setHomeMode();
  else if (state.practiceReturn === "learning-center") setLibraryMode();
  else if (state.practiceReturn === "english-exams") { setActiveView("library"); renderEnglishExams(); }
  else if (state.practiceReturn === "english-exam-overview" && state.practiceOverviewBankId) openEnglishExamOverview(state.practiceOverviewBankId);
  else if (state.practiceReturn === "resource" && state.resourceBookId) openResource(state.resourceBookId);
  else if (state.current?.id) setReaderMode();
  else setLibraryMode();
}
