import { $, state } from "../core/state.js";
import { escapeHtml, formatInteger, refreshIcons } from "../core/utils.js";
import { openPractice } from "../modules/practice.js";
import { domainBooks, learningBookCard, learningRailHtml, learningSectionHeader, recentFirstBooks } from "../views/reader.js";

export const POLITICS_SUBJECTS = [
  ["marxism", "马原"],
  ["mao", "毛中特"],
  ["xi", "习思想"],
  ["modern-history", "史纲"],
  ["ethics-law", "思法"],
];

state.politicsBasicSubject = state.politicsBasicSubject || "marxism";
state.politicsAdvSubject = state.politicsAdvSubject || "marxism";
state.politicsOverviews = state.politicsOverviews || {};

export async function fetchPoliticsOverview(bankId) {
  if (state.politicsOverviews[bankId]) return state.politicsOverviews[bankId];
  try {
    const res = await fetch(`/api/practice/overview?bank_id=${encodeURIComponent(bankId)}`, { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      state.politicsOverviews[bankId] = data;
      return data;
    }
  } catch (err) {
    console.warn("Failed to fetch politics overview:", bankId, err);
  }
  return null;
}

export function renderPoliticsBasicChapters() {
  const container = $("politicsBasicChapterList");
  if (!container) return;
  const overview = state.politicsOverviews["politics-basic-bank"];
  if (!overview) {
    container.innerHTML = `<div class="learning-loading">正在读取章节目录…</div>`;
    return;
  }
  const prefix = `politics.${state.politicsBasicSubject}.`;
  const groups = (overview.groups || []).filter((g) => g.key.startsWith(prefix));
  if (!groups.length) {
    container.innerHTML = `<div class="learning-empty"><strong>本科暂无章节题目</strong><span>请选择其他学科。</span></div>`;
    return;
  }
  container.innerHTML = groups.map((g) => {
    return `<button class="politics-chapter-entry" type="button" data-politics-bank="politics-basic-bank" data-politics-knowledge="${escapeHtml(g.knowledge_id)}" data-politics-level="chapter"><div class="politics-chapter-title-group"><strong>${escapeHtml(g.label)}</strong><small>${formatInteger(g.answered_count || 0)} / ${formatInteger(g.question_count)} 题已答</small></div><i data-lucide="arrow-right"></i></button>`;
  }).join("");
  bindPoliticsChapters(container);
  refreshIcons();
}

export function renderPoliticsAdvChapters() {
  const container = $("politicsAdvChapterList");
  if (!container) return;
  const overview = state.politicsOverviews["politics-advanced-bank"];
  if (!overview) {
    container.innerHTML = `<div class="learning-loading">正在读取测试套卷…</div>`;
    return;
  }
  const sub = state.politicsAdvSubject;
  const matchFn = (g) => {
    if (sub === "marxism") return /test-0[1-6]/.test(g.key);
    if (sub === "mao") return /test-0[7-8]/.test(g.key);
    if (sub === "xi") return /test-(09|1[0-3])/.test(g.key);
    if (sub === "modern-history") return /test-1[4-8]/.test(g.key);
    if (sub === "ethics-law") return /test-(19|2[0-1])/.test(g.key);
    return false;
  };
  const groups = (overview.groups || []).filter(matchFn);
  if (!groups.length) {
    container.innerHTML = `<div class="learning-empty"><strong>本科暂无测试套卷</strong><span>请选择其他学科。</span></div>`;
    return;
  }
  container.innerHTML = groups.map((g) => {
    const num = g.key.match(/test-(\d+)/)?.[1] || "01";
    const testKnowledgeId = `politics.${sub}.test-${num}`;
    const cleanLabel = g.label.replace(/^.*?[·•]/, "");
    return `<button class="politics-chapter-entry" type="button" data-politics-bank="politics-advanced-bank" data-politics-knowledge="${escapeHtml(testKnowledgeId)}" data-politics-level="comprehensive"><div class="politics-chapter-title-group"><strong>${escapeHtml(cleanLabel)}</strong><small>${formatInteger(g.answered_count || 0)} / 30 题已做 · 阶段综合测验</small></div><i data-lucide="arrow-right"></i></button>`;
  }).join("");
  bindPoliticsChapters(container);
  refreshIcons();
}

export function bindPoliticsChapters(container) {
  if (!container) return;
  container.querySelectorAll("[data-politics-bank]").forEach((button) => {
    button.addEventListener("click", () => {
      openPractice({
        bank_id: button.dataset.politicsBank,
        knowledge_id: button.dataset.politicsKnowledge,
        match_level: button.dataset.politicsLevel,
      }, "learning-center");
    });
  });
}

export function bindPoliticsEvents() {
  const tree = $("bookTree");
  if (!tree) return;
  tree.querySelectorAll("[data-politics-basic-subject]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.politicsBasicSubject = btn.dataset.politicsBasicSubject;
      tree.querySelectorAll("[data-politics-basic-subject]").forEach((b) => b.classList.toggle("active", b === btn));
      renderPoliticsBasicChapters();
    });
  });
  tree.querySelectorAll("[data-politics-adv-subject]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.politicsAdvSubject = btn.dataset.politicsAdvSubject;
      tree.querySelectorAll("[data-politics-adv-subject]").forEach((b) => b.classList.toggle("active", b === btn));
      renderPoliticsAdvChapters();
    });
  });
}

export function renderPoliticsCenter() {
  const books = recentFirstBooks(domainBooks(), "politics");
  const recentId = books[0]?.id || "";
  const basicTabs = POLITICS_SUBJECTS.map(([key, label]) => {
    return `<button class="politics-subject-tab${state.politicsBasicSubject === key ? " active" : ""}" type="button" data-politics-basic-subject="${key}">${label}</button>`;
  }).join("");
  const advTabs = POLITICS_SUBJECTS.map(([key, label]) => {
    return `<button class="politics-subject-tab${state.politicsAdvSubject === key ? " active" : ""}" type="button" data-politics-adv-subject="${key}">${label}</button>`;
  }).join("");

  Promise.all([
    fetchPoliticsOverview("politics-basic-bank"),
    fetchPoliticsOverview("politics-advanced-bank"),
  ]).then(() => {
    renderPoliticsBasicChapters();
    renderPoliticsAdvChapters();
    refreshIcons();
  });

  return `<section class="learning-center-section">${learningSectionHeader(1, "书架", "五科基础讲义 · 最近阅读自动置前", "politics-books", "book-marked")}${learningRailHtml("politics-books", books, (book) => learningBookCard(book, recentId))}</section>
    <section class="learning-center-section learning-practice-section basic">${learningSectionHeader(2, "优题库基础篇", "按真实章节目录对应练习 · 629 道核心题", "", "check-square")}<div class="politics-subject-tabs" role="group" aria-label="基础篇学科">${basicTabs}</div><div class="politics-chapter-grid" id="politicsBasicChapterList"><div class="learning-loading">正在读取章节目录…</div></div></section>
    <section class="learning-center-section learning-practice-section advanced">${learningSectionHeader(3, "优题库拔高篇", "21 套阶段综合模考套卷 · 每卷 30 题", "", "award")}<div class="politics-subject-tabs" role="group" aria-label="拔高篇学科">${advTabs}</div><div class="politics-chapter-grid" id="politicsAdvChapterList"><div class="learning-loading">正在读取测试套卷…</div></div></section>`;
}