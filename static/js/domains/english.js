import { setActiveView } from "../core/router.js";
import { $, state } from "../core/state.js";
import { stopReadingTimer } from "../core/timer.js";
import { escapeHtml, formatInteger, refreshIcons } from "../core/utils.js";
import { openPractice, openSubjectivePractice } from "../modules/practice.js";
import { closeNotePopover, learningBookCard, learningRailHtml, learningSectionHeader, recentFirstBooks, renderLearningCenterOverview } from "../views/reader.js";

export function englishShelfBooks() {
  return state.books.filter((book) => {
    if ((book.domain || "medicine") !== "english") return false;
    // Translation/writing reference pages belong to the year-specific true-paper
    // companion, not to the method-and-vocabulary shelf.
    return !/subjective|翻译与写作/i.test(`${book.id} ${book.title} ${book.resource_type || ""}`);
  });
}

export function englishPanel(mode = "") {
  const isExams = mode === "exams"; const isExamOverview = mode === "exam-overview";
  $("englishExams")?.classList.toggle("hidden", !isExams);
  $("englishExamOverview")?.classList.toggle("hidden", !isExamOverview);
  $("bookTree")?.classList.toggle("hidden", isExams || isExamOverview);
  document.querySelector(".learning-center-header")?.classList.toggle("hidden", isExams || isExamOverview);
}

export function renderEnglishExams() {
  englishPanel("exams");
  const banks = state.questionBanks.filter((bank) => bank.domain === "english").sort((a, b) => b.title.localeCompare(a.title, "zh-CN"));
  const bankRows = banks.map((bank) => {
    const knowledgeId = bank.knowledge_ids?.find((id) => /^english\.exam\.\d{4}\.e\d+$/.test(id)) || "";
    const track = /(?:英语\s*[（(]?二|e2(?:-|$)|英语二)/i.test(`${bank.subject || ""} ${bank.id}`) ? "考研英语二" : "考研英语一";
    return `<button class="english-exam-row" type="button" data-bank="${escapeHtml(bank.id)}" data-knowledge="${escapeHtml(knowledgeId)}" data-count="${bank.question_count}"><span><small>${track}</small><strong>${escapeHtml(bank.title)}</strong></span><span><small>客观题</small><strong>${bank.question_count} 题</strong></span><i data-lucide="arrow-right"></i></button>`;
  }).join("");
  $("englishExamList").innerHTML = bankRows || `<div class="english-archive-empty">还没有通过验证的真题包。</div>`;
  $("englishExamList").querySelectorAll("[data-bank]").forEach((button) => button.addEventListener("click", () => openEnglishExamOverview(button.dataset.bank)));
  refreshIcons();
}

export function englishPaperSubjectiveRows(subjective) {
  if (!subjective?.available) return `<div class="english-paper-row unavailable"><span class="english-paper-row-index">—</span><span class="english-paper-row-copy"><small>SECTION III / IV</small><strong>翻译与写作</strong><em>原卷包含主观题，但对应资料尚未发布</em></span><span class="english-paper-row-status"><strong>待补充</strong></span><i data-lucide="clock-3"></i></div>`;
  return (subjective.sections || []).map((item, index) => `<button class="english-paper-row" type="button" data-paper-resource="${escapeHtml(item.book_id)}" data-paper-resource-section="${escapeHtml(item.section_id)}"><span class="english-paper-row-index">${String(index + 7).padStart(2, "0")}</span><span class="english-paper-row-copy"><small>SECTION III / IV</small><strong>${escapeHtml(item.title)}</strong><em>${escapeHtml(item.range)} · 独立作答，支持侧边栏批改</em></span><span class="english-paper-row-status"><strong>进入练习</strong></span><i data-lucide="arrow-up-right"></i></button>`).join("");
}

export function renderEnglishExamOverview() {
  englishPanel("exam-overview");
  const payload = state.englishExamOverview;
  const bank = payload?.bank || state.questionBanks.find((item) => item.id === state.englishExamOverviewBankId);
  if (!payload || !bank) {
    $("englishExamOverviewTitle").textContent = "正在读取试卷…";
    $("englishExamOverviewMeta").textContent = "正在整理题型与文章顺序。";
    $("englishExamOverviewFacts").innerHTML = "";
    $("englishExamOverviewSections").innerHTML = `<div class="english-archive-empty">正在读取这套真题的结构…</div>`;
    $("englishExamOverviewCompanion").innerHTML = "";
    $("englishExamOverviewCompanion").classList.add("hidden");
    refreshIcons();
    return;
  }
  const groups = payload.groups || [];
  const catalogBank = state.questionBanks.find((item) => item.id === bank.id) || bank;
  const subjective = payload.subjective || { available: false, sections: [], question_count: 0, range: "" };
  const coverage = bank.coverage || catalogBank.coverage || {};
  const subjectiveLabel = String(subjective.range || coverage.subjective_questions || "46–52").replace(/retained outside objective bank/i, "").trim() || "46–52";
  const track = /(?:英语\s*[（(]?二|e2(?:-|$)|英语二)/i.test(`${bank.subject || ""} ${bank.id}`) ? "考研英语二" : "考研英语一";
  const trackCode = track.endsWith("二") ? "ENGLISH II" : "ENGLISH I";
  $("englishExamOverviewEyebrow").textContent = `${String(bank.title || "").match(/\d{4}/)?.[0] || "PAST PAPER"} · ${trackCode}`;
  $("englishExamOverviewTitle").textContent = bank.title || `${track}真题`;
  $("englishExamOverviewMeta").textContent = `按原试卷顺序组织：客观题逐题作答。${subjective.available ? "翻译与写作进入独立主观题练习。" : "主观题资料尚未发布。"}`;
  $("englishExamOverviewFacts").innerHTML = `<div><span>客观题</span><strong>${formatInteger(payload.question_count)} 题</strong><em>第 1–45 题</em></div><div><span>主观题</span><strong>${formatInteger(subjective.question_count || 0)} 题</strong><em>第 ${escapeHtml(subjectiveLabel.replace(/.*?(\d+[-–]\d+).*/, "$1"))} 题</em></div><div><span>客观题型</span><strong>${groups.length} 组</strong><em>完形、阅读与新题型</em></div><div><span>完成进度</span><strong>${formatInteger(payload.answered_count)} / ${formatInteger(payload.question_count)}</strong><em>按已提交题目计算</em></div>`;
  const objectiveRows = groups.map((group, index) => {
    const range = group.start_number === group.end_number ? `第 ${group.start_number} 题` : `第 ${group.start_number}–${group.end_number} 题`;
    const passage = group.paragraph_count ? ` · 原文 ${group.paragraph_count} 段` : "";
    const completed = `${group.answered_count}/${group.question_count} 已答`;
    const knowledgeId = group.knowledge_id || catalogBank.knowledge_ids?.find((id) => /^english\.exam\.\d{4}\.e\d+$/.test(id)) || "";
    return `<button class="english-paper-row" type="button" data-paper-start="${group.start_index}" data-paper-bank="${escapeHtml(bank.id)}" data-paper-knowledge="${escapeHtml(knowledgeId)}"><span class="english-paper-row-index">${String(index + 1).padStart(2, "0")}</span><span class="english-paper-row-copy"><small>${escapeHtml(group.part)}</small><strong>${escapeHtml(group.label)}</strong><em>${range} · ${formatInteger(group.question_count)} 题${passage}</em></span><span class="english-paper-row-status"><small>${completed}</small><strong>进入答题</strong></span><i data-lucide="arrow-right"></i></button>`;
  }).join("");
  $("englishExamOverviewProgress").textContent = `${formatInteger(payload.answered_count)} / ${formatInteger(payload.question_count)} 题已答`;
  $("englishExamOverviewSections").innerHTML = objectiveRows || `<div class="english-archive-empty">暂无可用的客观题分组。</div>`;
  $("englishExamOverviewCompanion").classList.remove("hidden");
  $("englishExamOverviewCompanion").innerHTML = `<header><div><p class="eyebrow">SECTION III / IV</p><h4>翻译与写作</h4></div><span>${subjective.available ? "主观题练习" : "原卷题型"}</span></header><div class="english-paper-companion-list">${englishPaperSubjectiveRows(subjective)}</div>`;
  $("englishExamOverviewSections").querySelectorAll("[data-paper-start]").forEach((button) => button.addEventListener("click", () => {
    const startIndex = Number(button.dataset.paperStart || 0); const group = groups.find((item) => Number(item.start_index) === startIndex);
    openPractice({ bank_id: button.dataset.paperBank, knowledge_id: button.dataset.paperKnowledge, match_level: "comprehensive", question_count: Number(group?.question_count || 0), label: group?.label || "" }, "english-exam-overview", startIndex);
  }));
  $("englishExamOverviewCompanion").querySelectorAll("[data-paper-resource]").forEach((button) => button.addEventListener("click", () => { state.subjectiveReturn = "exam-overview"; openSubjectivePractice(button.dataset.paperResource, button.dataset.paperResourceSection); }));
  refreshIcons();
}

export async function openEnglishExamOverview(bankId) {
  if (!bankId) return;
  state.openRequest += 1; stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden");
  state.englishExamOverview = null; state.englishExamOverviewBankId = bankId; state.resourceBookId = null; state.resource = null;
  $("libraryWorkspace").classList.remove("reader-open", "resource-open"); $("readerContent").classList.add("hidden");
  setActiveView("library"); renderEnglishExamOverview(); window.scrollTo({ top: 0, behavior: "auto" });
  try {
    const response = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(bankId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("overview unavailable");
    const payload = await response.json();
    if (state.englishExamOverviewBankId !== bankId) return;
    state.englishExamOverview = payload; renderEnglishExamOverview();
  } catch {
    if (state.englishExamOverviewBankId !== bankId) return;
    $("englishExamOverviewTitle").textContent = "暂时无法读取试卷";
    $("englishExamOverviewMeta").textContent = "请确认题库通过验证且本地服务正在运行。";
    $("englishExamOverviewSections").innerHTML = `<div class="english-archive-empty">这套真题暂时不可用。</div>`;
    refreshIcons();
  }
}

export function englishBankInfo(bank) {
  const year = Number(String(`${bank.id} ${bank.title}`).match(/20\d{2}/)?.[0] || 0);
  const paper = /(?:英语\s*[（(]?二|e2(?:-|$)|英语二)/i.test(`${bank.subject || ""} ${bank.id}`) ? 2 : 1;
  return { bank, year, paper };
}

export function selectedEnglishBank() {
  const candidates = state.questionBanks.map(englishBankInfo).filter((entry) => entry.bank.domain === "english" && entry.paper === state.englishCenterTrack).sort((a, b) => b.year - a.year);
  if (!candidates.length) return null;
  if (!candidates.some((entry) => entry.year === Number(state.englishCenterYear))) state.englishCenterYear = String(candidates[0].year);
  return candidates.find((entry) => entry.year === Number(state.englishCenterYear)) || candidates[0];
}

export function englishSelectionHtml(selected) {
  const years = state.questionBanks.map(englishBankInfo).filter((entry) => entry.bank.domain === "english" && entry.paper === state.englishCenterTrack && entry.year).sort((a, b) => b.year - a.year);
  return `<div class="english-center-filters"><div role="group" aria-label="英语试卷类型"><button type="button" data-english-track="1" class="${state.englishCenterTrack === 1 ? "active" : ""}">英语一</button><button type="button" data-english-track="2" class="${state.englishCenterTrack === 2 ? "active" : ""}">英语二</button></div><label><span>年份</span><select id="englishCenterYear" aria-label="选择真题年份">${years.map((entry) => `<option value="${entry.year}" ${entry.year === selected?.year ? "selected" : ""}>${entry.year}</option>`).join("")}</select></label></div>`;
}

export function renderEnglishCenter() {
  const books = recentFirstBooks(englishShelfBooks(), "english"); const recentId = books[0]?.id || ""; const selected = selectedEnglishBank();
  return `<section class="learning-center-section">${learningSectionHeader(1, "书架", `${books.length} 本方法、阅读与词汇资料 · 最近阅读自动置前`, "english-books")}${learningRailHtml("english-books", books, (book) => learningBookCard(book, recentId))}</section>
    <section class="learning-center-section english-training-section">${learningSectionHeader(2, "真题训练", "完形、阅读与新题型统一按年份快速进入")}${englishSelectionHtml(selected)}<div class="english-type-tabs" role="group" aria-label="客观题型"><button type="button" data-english-type="cloze" class="${state.englishCenterType === "cloze" ? "active" : ""}">完形填空</button><button type="button" data-english-type="reading" class="${state.englishCenterType === "reading" ? "active" : ""}">阅读理解</button><button type="button" data-english-type="new" class="${state.englishCenterType === "new" ? "active" : ""}">新题型</button></div><div class="english-center-groups" id="englishCenterObjectiveGroups"><div class="learning-loading">正在读取${selected?.year || ""}年题型…</div></div></section>
    <section class="learning-center-section english-writing-section">${learningSectionHeader(3, "翻译与写作", "与客观题拆分，独立作答后再查看参考解析")}<div class="english-center-groups subjective" id="englishCenterSubjectiveGroups"><div class="learning-loading">正在读取翻译与写作资料…</div></div></section>`;
}

export async function loadEnglishCenterOverview() {
  const selected = selectedEnglishBank(); if (!selected) return;
  try {
    let payload = state.englishCenterOverviewCache.get(selected.bank.id);
    if (!payload) {
      const response = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(selected.bank.id)}`, { cache: "no-store" });
      if (!response.ok) throw new Error("overview unavailable");
      payload = await response.json(); state.englishCenterOverviewCache.set(selected.bank.id, payload);
    }
    renderLearningCenterOverview(payload, selected);
  } catch {
    const objective = $("englishCenterObjectiveGroups"); const subjective = $("englishCenterSubjectiveGroups");
    if (objective) objective.innerHTML = `<div class="learning-empty"><strong>暂时无法读取真题结构</strong><span>请确认本地题库可用后重试。</span></div>`;
    if (subjective) subjective.innerHTML = `<div class="learning-empty"><strong>暂时无法读取主观题资料</strong><span>已有作答和历史资料不会受到影响。</span></div>`;
  }
}

export function bindEnglishCenterGroups() {
  $("bookTree").querySelectorAll("[data-english-objective-bank]").forEach((button) => button.addEventListener("click", () => openPractice({ bank_id: button.dataset.englishObjectiveBank, knowledge_id: button.dataset.englishObjectiveKnowledge, match_level: "comprehensive" }, "learning-center", Number(button.dataset.englishObjectiveStart || 0))));
  $("bookTree").querySelectorAll("[data-english-subjective-section]").forEach((button) => button.addEventListener("click", () => { state.subjectiveReturn = "learning-center"; state.englishExamOverviewBankId = button.dataset.englishSubjectiveBank; openSubjectivePractice(button.dataset.englishSubjectiveBook, button.dataset.englishSubjectiveSection); }));
}