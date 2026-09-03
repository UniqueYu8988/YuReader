import { $, state } from "../core/state.js";
import { escapeHtml, formatInteger } from "../core/utils.js";
import { domainBooks, learningBookCard, learningRailHtml, learningSectionHeader, recentFirstBooks } from "../views/reader.js";

export const POLITICS_SUBJECTS = [
  ["marxism", "马原"], ["mao", "毛中特"], ["xi", "习思想"], ["modern-history", "史纲"], ["ethics-law", "思法"],
];

export function politicsPracticeSection(index, bankId, title, description, tone) {
  const bank = state.questionBanks.find((entry) => entry.id === bankId);
  if (!bank) return `<section class="learning-center-section">${learningSectionHeader(index, title, description)}<div class="learning-empty"><strong>题库尚未导入</strong><span>通过验证后会在这里显示，不会静默消失。</span></div></section>`;
  const subjectButtons = POLITICS_SUBJECTS.map(([key, label]) => {
    const prefix = `politics.${key}.`;
    const matcher = tone === "advanced" ? ".test-" : ".ch";
    const knowledgeId = (bank.knowledge_ids || []).find((id) => id.startsWith(prefix) && id.includes(matcher)) || "";
    const units = (bank.knowledge_ids || []).filter((id) => id.startsWith(prefix) && id.includes(matcher)).length;
    return `<button type="button" ${knowledgeId ? `data-politics-bank="${escapeHtml(bank.id)}" data-politics-knowledge="${escapeHtml(knowledgeId)}" data-politics-level="${tone === "advanced" ? "comprehensive" : "chapter"}"` : "disabled"}><span><strong>${label}</strong><small>${units ? `${units} 个训练单元` : "暂无匹配题组"}</small></span><i data-lucide="arrow-up-right"></i></button>`;
  }).join("");
  return `<section class="learning-center-section learning-practice-section ${tone}">${learningSectionHeader(index, title, `${formatInteger(bank.question_count)} 道正式题 · ${description}${tone === "advanced" ? ` · ${formatInteger(bank.test_count || 0)} 组综合测试` : ""}`)}<div class="learning-subject-actions">${subjectButtons}</div></section>`;
}

export function renderPoliticsCenter() {
  const books = recentFirstBooks(domainBooks(), "politics"); const recentId = books[0]?.id || "";
  return `<section class="learning-center-section">${learningSectionHeader(1, "书架", "五科基础讲义 · 最近阅读自动置前", "politics-books")}${learningRailHtml("politics-books", books, (book) => learningBookCard(book, recentId))}</section>
    ${politicsPracticeSection(2, "politics-basic-bank", "优题库基础篇", "建立章节级选择题基础", "basic")}
    ${politicsPracticeSection(3, "politics-advanced-bank", "优题库拔高篇", "按真实综合测试分组训练", "advanced")}`;
}