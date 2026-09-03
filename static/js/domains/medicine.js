import { $, state } from "../core/state.js";
import { escapeHtml, formatInteger } from "../core/utils.js";
import { domainBooks, learningBookCard, learningRailHtml, learningSectionHeader, recentFirstBooks } from "../views/reader.js";

export function oralFocusSubjectCards(type) {
  return (state.oralFocus?.subjects || []).map((subject) => {
    const items = (subject.chapters || []).flatMap((chapter) => chapter.items || []).filter((item) => item.type === type);
    return { ...subject, focus_type: type, focus_count: items.length, focus_completed: items.filter((item) => item.completed).length };
  }).filter((subject) => subject.focus_count);
}

export function medicinePracticeSection(index, type, title, defaultDescription, tone, icon = "") {
  const subjects = oralFocusSubjectCards(type);
  const totalCount = subjects.reduce((sum, item) => sum + (item.focus_count || 0), 0);
  const description = state.oralFocus?.available
    ? `${formatInteger(totalCount)} 道${title} · 按口外、口组、牙体、牙周与修复分组`
    : defaultDescription;
  if (!state.oralFocus?.available || !subjects.length) {
    return `<section class="learning-center-section">${learningSectionHeader(index, title, description, "", icon)}<div class="learning-empty"><strong>资料尚未导入</strong><span>资料入口已保留，等待本地重点资料。</span></div></section>`;
  }
  const subjectButtons = subjects.map((subject) => {
    return `<button type="button" data-oral-subject="${escapeHtml(subject.id)}" data-oral-type="${escapeHtml(type)}" title="${escapeHtml(subject.title)} · ${escapeHtml(title)}"><span><strong>${escapeHtml(subject.title)}</strong><small>${formatInteger(subject.focus_completed)} / ${formatInteger(subject.focus_count)}</small></span><i data-lucide="arrow-up-right"></i></button>`;
  }).join("");
  return `<section class="learning-center-section learning-practice-section ${tone}">${learningSectionHeader(index, title, description, "", icon)}<div class="learning-subject-actions">${subjectButtons}</div></section>`;
}

export function renderMedicineCenter() {
  const books = recentFirstBooks(domainBooks(), "medicine"); const recentId = books[0]?.id || "";
  return `<section class="learning-center-section">${learningSectionHeader(1, "书架", `${books.length} 本口腔教材 · 最近阅读自动置前`, "medicine-books", "book-marked")}${learningRailHtml("medicine-books", books, (book) => learningBookCard(book, recentId))}</section>
    ${medicinePracticeSection(2, "definition", "名词解释", "资料入口已保留，等待本地重点资料", "basic", "sparkles")}
    ${medicinePracticeSection(3, "essay", "论述题", "资料入口已保留，等待本地重点资料", "advanced", "file-text")}`;
}