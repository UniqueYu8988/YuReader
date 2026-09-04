import { setActiveView, setRouteHash } from "../core/router.js";
import { $, ORAL_FOCUS_TYPE_STORAGE_KEY, ORAL_REFERENCE_STORAGE_KEY, state } from "../core/state.js";
import { startWorkspaceTimer, stopReadingTimer } from "../core/timer.js";
import { escapeHtml, formatInteger, refreshIcons, renderMarkdown, showToast } from "../core/utils.js";
import { closeNotePopover } from "../views/reader.js";

export const ORAL_CLOZE_STORAGE_KEY = "yureader-oral-cloze-mode";
if (typeof state.oralFocusClozeMode === "undefined") {
  try {
    state.oralFocusClozeMode = localStorage.getItem(ORAL_CLOZE_STORAGE_KEY) === "true";
  } catch {
    state.oralFocusClozeMode = false;
  }
}

export function selectedOralFocusSubject() {
  const subjects = state.oralFocus?.subjects || [];
  return subjects.find((item) => item.id === state.oralFocusSubjectId) || subjects[0] || null;
}

export async function renderOralFocusDueBanner() {
  const banner = $("oralFocusDueBanner");
  if (!banner) return;
  try {
    const res = await fetch("/api/oral-focus/due", { cache: "no-store" });
    if (!res.ok) throw new Error("due fetch failed");
    const data = await res.json();
    state.oralDueData = data;
    state.oralDueCount = data.total_due || 0;

    banner.classList.remove("hidden");
    if (data.total_due > 0) {
      const subjCount = Object.keys(data.by_subject || {}).length;
      banner.innerHTML = `
        <div class="oral-due-banner-content">
          <div class="oral-due-info">
            <div class="oral-due-tag"><i data-lucide="flame"></i><span>艾宾浩斯抗遗忘</span></div>
            <div class="oral-due-text">
              <strong>今日到期待复习 <span class="oral-due-count-badge">${formatInteger(data.total_due)}</span> 题</strong>
              <span class="oral-due-subtext">名解 ${data.definitions_due} · 论述 ${data.essays_due} · 覆盖 ${subjCount} 门专科</span>
            </div>
          </div>
          <button type="button" class="oral-due-start-btn" id="oralDueStartBtn">
            <i data-lucide="sparkles"></i><span>一键开启今日复习</span>
          </button>
        </div>
      `;
      $("oralDueStartBtn")?.addEventListener("click", () => {
        openOralFocusChapter("due-session", "", "card");
      });
    } else {
      banner.innerHTML = `
        <div class="oral-due-banner-content is-cleared">
          <div class="oral-due-info">
            <div class="oral-due-tag is-cleared"><i data-lucide="check-circle-2"></i><span>今日已清空</span></div>
            <div class="oral-due-text">
              <strong>今日抗遗忘复习任务已全部清空！</strong>
              <span class="oral-due-subtext">当前暂无到期卡片，可前往各专科章节继续开启新一轮背诵。</span>
            </div>
          </div>
        </div>
      `;
    }
    refreshIcons();
  } catch {
    banner.classList.add("hidden");
  }
}

export function renderOralFocusDirectory() {
  renderOralFocusDueBanner();
  const subjects = state.oralFocus?.subjects || [];
  const subject = selectedOralFocusSubject();
  if (!subject) {
    $("oralFocusSubjectTabs").innerHTML = "";
    $("oralFocusChapterList").innerHTML = `<div class="knowledge-index-empty"><strong>口腔重点资料尚未导入</strong><span>运行本地 DOCX 导入后，这里会显示章节。</span></div>`;
    return;
  }
  state.oralFocusSubjectId = subject.id;
  if (!state.oralFocusTypeFilter) {
    try {
      state.oralFocusTypeFilter = localStorage.getItem(ORAL_FOCUS_TYPE_STORAGE_KEY) || "definition";
    } catch {
      state.oralFocusTypeFilter = "definition";
    }
  }
  const type = state.oralFocusTypeFilter || "definition";
  const typeLabel = type === "definition" ? "名词解释" : "简答论述";

  // Filter chapters strictly by type
  const chapters = (subject.chapters || []).filter((chapter) => {
    if (chapter.type) return chapter.type === type;
    return chapter.id.includes(`-${type}-`);
  }).map((chapter) => {
    const items = chapter.items || [];
    return { ...chapter, filtered_items: items, completed: items.filter((item) => item.completed).length };
  }).filter((chapter) => chapter.filtered_items.length);

  const filteredItems = chapters.flatMap((chapter) => chapter.filtered_items);
  const completedCount = filteredItems.filter((item) => item.completed).length;

  $("oralFocusDirectoryTitle").textContent = `${subject.short_title || subject.title} · ${typeLabel}`;
  $("oralFocusSummary").textContent = `${formatInteger(completedCount)} / ${formatInteger(filteredItems.length)}`;

  // Subject tabs
  $("oralFocusSubjectTabs").innerHTML = subjects.map((entry) => {
    const items = (entry.chapters || []).filter((ch) => ch.type === type || ch.id.includes(`-${type}-`)).flatMap((ch) => ch.items || []);
    const completed = items.filter((item) => item.completed).length;
    return `<button type="button" class="${entry.id === subject.id ? "active" : ""}" data-oral-subject="${escapeHtml(entry.id)}" aria-pressed="${entry.id === subject.id ? "true" : "false"}"><strong>${escapeHtml(entry.short_title)}</strong><small>${formatInteger(completed)} / ${formatInteger(items.length)}</small></button>`;
  }).join("");

  // Type filter tabs counts
  const defItems = (subject.chapters || []).filter((ch) => ch.type === "definition" || ch.id.includes("-definition-")).flatMap((ch) => ch.items || []);
  const essayItems = (subject.chapters || []).filter((ch) => ch.type === "essay" || ch.id.includes("-essay-")).flatMap((ch) => ch.items || []);
  const defCountEl = $("oftDefCount");
  if (defCountEl) defCountEl.textContent = formatInteger(defItems.length);
  const essayCountEl = $("oftEssayCount");
  if (essayCountEl) essayCountEl.textContent = formatInteger(essayItems.length);

  document.querySelectorAll("[data-oral-filter-type]").forEach((btn) => {
    const isActive = btn.dataset.oralFilterType === type;
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-selected", isActive ? "true" : "false");
  });

  $("oralFocusChapterPanel").classList.add("hidden");
  $("oralFocusChapterList").classList.remove("hidden");
  $("oralFocusChapterList").innerHTML = chapters.length ? chapters.map((chapter) => {
    const pct = chapter.filtered_items.length ? Math.round((chapter.completed / chapter.filtered_items.length) * 100) : 0;
    return `<div class="oral-focus-chapter-card" data-oral-chapter="${escapeHtml(chapter.id)}">
      <div class="of-chapter-main" data-oral-open-chapter="${escapeHtml(chapter.id)}" data-mode="list">
        <span class="of-chapter-order">${String(chapter.order || 0).padStart(2, "0")}</span>
        <div class="of-chapter-meta">
          <strong>${escapeHtml(chapter.title || "未分章")}</strong>
          <div class="of-chapter-progress-row">
            <div class="of-chapter-progress-track">
              <div class="of-chapter-progress-bar" style="width: ${pct}%"></div>
            </div>
            <small>${formatInteger(chapter.completed)} / ${formatInteger(chapter.filtered_items.length)} 题 · ${pct}%</small>
          </div>
        </div>
      </div>
      <div class="of-chapter-actions">
        <button class="of-chapter-btn is-study" type="button" data-oral-open-chapter="${escapeHtml(chapter.id)}" data-mode="list" title="进入题目列表研读">
          <i data-lucide="book-open"></i><span>研读列表</span>
        </button>
        <button class="of-chapter-btn is-card" type="button" data-oral-open-chapter="${escapeHtml(chapter.id)}" data-mode="card" title="进入艾宾浩斯翻转记忆卡">
          <i data-lucide="sparkles"></i><span>背诵卡</span>
        </button>
      </div>
    </div>`;
  }).join("") : `<div class="knowledge-index-empty"><strong>本科暂无${typeLabel}</strong><span>切换其他学科，或返回医学学习选择另一类资料。</span></div>`;

  $("oralFocusSubjectTabs").querySelectorAll("[data-oral-subject]").forEach((button) => button.addEventListener("click", () => { state.oralFocusSubjectId = button.dataset.oralSubject; state.oralFocusChapterId = ""; state.oralFocusChapter = null; renderOralFocusDirectory(); window.scrollTo({ top: 0, behavior: "auto" }); }));
  $("oralFocusChapterList").querySelectorAll("[data-oral-open-chapter]").forEach((el) => el.addEventListener("click", (e) => {
    e.stopPropagation();
    const chId = el.dataset.oralOpenChapter;
    const mode = el.dataset.mode || "list";
    openOralFocusChapter(chId, "", mode);
  }));
  $("oralFocusTypeFilterBar")?.querySelectorAll("[data-oral-filter-type]").forEach((btn) => btn.addEventListener("click", () => {
    state.oralFocusTypeFilter = btn.dataset.oralFilterType;
    try { localStorage.setItem(ORAL_FOCUS_TYPE_STORAGE_KEY, state.oralFocusTypeFilter); } catch {}
    state.oralFocusChapterId = "";
    state.oralFocusChapter = null;
    renderOralFocusDirectory();
  }));

  refreshIcons();
}

export function oralFocusAnswerHtml(item) {
  if (item.answer_status === "source_missing") {
    return `<div class="oral-focus-source-missing-box">
      <div class="of-missing-head">
        <i data-lucide="info"></i>
        <strong>原资料未提供参考答案</strong>
      </div>
      <p>该考点在原始整理讲义中未附带完整解答（仅有题名或中文译名）。建议使用右侧 Obsidian 笔记与侧边栏 AI 查阅官方教材进行理解补充。</p>
    </div>`;
  }
  const tagsHtml = (item.source_tags && item.source_tags.length)
    ? `<div class="oral-focus-tags-row">${item.source_tags.map((t) => `<span class="oral-focus-source-tag">${escapeHtml(t)}</span>`).join("")}</div>`
    : "";
  const translation = item.definition_translation ? `<div class="oral-focus-translation"><small>中文译名</small><strong>${escapeHtml(item.definition_translation)}</strong></div>` : "";
  return `${tagsHtml}${translation}<article class="knowledge-article oral-focus-answer-copy">${renderMarkdown(item.answer_markdown || "暂无可识别的标准答案。")}</article>`;
}

export const OUTLINE_CATEGORY_MAP = [
  { type: "indication", label: "适应证", re: /^(?:【(?:适应[证症]|适用范围|适用)】|(?:适应[证症]|适用范围|适用)\s*[:：])/ },
  { type: "contraindication", label: "禁忌证", re: /^(?:【(?:禁忌[证症]|禁忌)】|(?:禁忌[证症]|禁忌)\s*[:：])/ },
  { type: "feature", label: "特点表现", re: /^(?:【(?:(?:临床|局麻|病理|主要)?特点|临床表现|病理表现|主要表现|表现)】|(?:(?:临床|局麻|病理|主要)?特点|临床表现|病理表现|主要表现|表现)\s*[:：])/ },
  { type: "method", label: "方法药物", re: /^(?:【(?:常用(?:药物|方法)|使用药物|治疗方法|操作要点|注意事项|取材|麻醉|给药途径)】|(?:常用(?:药物|方法)|使用药物|治疗方法|操作要点|注意事项|取材|麻醉|给药途径)\s*[:：])/ },
  { type: "principle", label: "原则机制", re: /^(?:【(?:(?:治疗|操作)?原则|(?:发病)?机制|病因|临床意义)】|(?:(?:治疗|操作)?原则|(?:发病)?机制|病因|临床意义)\s*[:：])/ },
  { type: "warning", label: "局限并发", re: /^(?:【(?:局限性|主要并发症|并发症|优缺点|优点|缺点)】|(?:局限性|主要并发症|并发症|优缺点|优点|缺点)\s*[:：])/ },
  { type: "definition", label: "概念定义", re: /^(?:【(?:定义|概念|确切含义)】|(?:定义|概念|确切含义)\s*[:：])/ },
  { type: "taxonomy", label: "分型诊断", re: /^(?:【(?:分类|分型|分期|诊断标准|诊断|鉴别诊断)】|(?:分类|分型|分期|诊断标准|诊断|鉴别诊断)\s*[:：])/ },
];

export function enhanceOralFocusSource(root) {
  const circledChars = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";
  const paragraphs = [...root.querySelectorAll("p")];

  // Pass 1: Structural Hierarchy Recognition (L1 Section, L2 Item, L3 Step, or Standard)
  paragraphs.forEach((paragraph, idx) => {
    if (paragraph.classList.contains("oral-focus-structured-point") || paragraph.closest(".oral-focus-structured-point, .of-section-header, .of-step-item")) return;

    const rawText = paragraph.textContent || "";
    const trimText = rawText.trim();
    if (!trimText) return;

    // Check if L1 Section: e.g. （1）面形及关节动度检查 or 一、面形及关节动度检查
    const mSec = trimText.match(/^(?:[（(](\d{1,2})[）)]|([一二三四五六七八九十]+)[、.])\s*(.+)$/);
    const nextP = paragraphs[idx + 1];
    const nextText = nextP?.textContent?.trim() || "";
    const nextHasCircle = new RegExp(`^[${circledChars}]`).test(nextText);
    const isShortTitle = mSec && mSec[3].length <= 26 && !mSec[3].endsWith("。") && !mSec[3].endsWith("；") && !/^[是为指]/.test(mSec[3]);

    if (mSec && (nextHasCircle || isShortTitle)) {
      const secNum = mSec[1] ? String(mSec[1]).padStart(2, "0") : mSec[2];
      const secTitle = mSec[3].trim();
      const secDiv = document.createElement("div");
      secDiv.className = "of-section-header";
      secDiv.innerHTML = `<span class="of-section-badge">${escapeHtml(secNum)}</span><span class="of-section-title">${escapeHtml(secTitle)}</span>`;
      paragraph.replaceWith(secDiv);
      return;
    }

    // Check if L3 Sub-item (NO "步骤", purely artistic numbers)
    const mStep = trimText.match(/^(\d{1,2})[）)]\s*(.+)$/) || trimText.match(/^步骤\s*(\d{1,2})[：:、.]\s*(.+)$/);
    if (mStep) {
      const num = mStep[1];
      const content = mStep[2].trim();
      const div = document.createElement("div");
      div.className = "of-sub-item-row";
      div.innerHTML = `<span class="of-art-num-badge">${escapeHtml(num)})</span><div class="of-sub-item-text">${escapeHtml(content)}</div>`;
      paragraph.replaceWith(div);
      return;
    }

    // Check if L4 Alpha item: e.g. a.关节源性的疼痛... or b.非关节源性疼痛...
    const mAlpha = trimText.match(/^([a-zA-Z])[\.、)]\s*(.+)$/);
    if (mAlpha) {
      const alphaLetter = mAlpha[1].toLowerCase();
      const alphaContent = mAlpha[2].trim();
      const alphaDiv = document.createElement("div");
      alphaDiv.className = "of-alpha-row";
      alphaDiv.innerHTML = `<span class="of-art-alpha">${escapeHtml(alphaLetter)}</span><div class="of-alpha-text">${escapeHtml(alphaContent)}</div>`;
      paragraph.replaceWith(alphaDiv);
      return;
    }

    // Check if L2 Item: starts with ①, ②, ③ ...
    const mCircle = trimText.match(new RegExp(`^([${circledChars}])\\s*(.*)$`));
    if (mCircle) {
      const cChar = mCircle[1];
      const cIndex = circledChars.indexOf(cChar) + 1;
      let bodyText = mCircle[2].trim();

      // Check outline keyword
      let outlineBadge = null;
      for (const cat of OUTLINE_CATEGORY_MAP) {
        const om = bodyText.trimStart().match(cat.re);
        if (om) {
          outlineBadge = { type: cat.type, label: cat.label };
          bodyText = bodyText.slice(bodyText.indexOf(om[0]) + om[0].length).trim();
          break;
        }
      }

      // Check target scope colon (e.g. 口外：, 口内：, 髁突动度检查：)
      let targetScope = null;
      const tm = bodyText.trimStart().match(/^([\u4e00-\u9fa5A-Za-z0-9／]{2,8}[：:])/);
      if (tm && !outlineBadge) {
        targetScope = tm[1];
        bodyText = bodyText.slice(bodyText.indexOf(tm[0]) + tm[0].length).trim();
      }

      const pDiv = document.createElement("div");
      pDiv.className = "oral-focus-structured-point of-level-2";

      let innerHtml = `<span class="of-art-circle">${cIndex}</span><div class="oral-focus-point-content">`;
      if (outlineBadge) {
        innerHtml += `<span class="of-outline-badge of-badge-${outlineBadge.type}">${outlineBadge.label}</span>`;
      }
      innerHtml += `<div class="of-point-body">${targetScope ? `<span class="of-target-scope">${escapeHtml(targetScope)}</span>` : ""}${escapeHtml(bodyText)}</div></div>`;
      pDiv.innerHTML = innerHtml;
      paragraph.replaceWith(pDiv);
      return;
    }

    // Standard definition point: starts with （1）, 1., etc.
    const mStd = trimText.match(/^\s*(?:[（(](\d{1,2})[）)]|(\d{1,2})[\.、])\s*(.*)$/);
    if (mStd) {
      const markerVal = (mStd[1] || mStd[2]).padStart(2, "0");
      let bodyText = mStd[3].trim();

      // Nested circled sub-points check (e.g. （4）特点 ①... ②...)
      const hasCircled = new RegExp(`[${circledChars}]`).test(bodyText);
      if (hasCircled) {
        const subParts = bodyText.split(new RegExp(`([${circledChars}])`));
        if (subParts.length > 2) {
          const leadIntro = subParts[0].trim();
          let subItemsHtml = "";
          for (let i = 1; i < subParts.length; i += 2) {
            const cChar = subParts[i];
            const cIndex = circledChars.indexOf(cChar) + 1;
            const cText = (subParts[i + 1] || "").trim();
            if (!cText) continue;
            subItemsHtml += `<div class="of-sub-item"><span class="of-sub-num">${cIndex}</span><span class="of-sub-text">${escapeHtml(cText)}</span></div>`;
          }

          let outlineBadge = null;
          for (const cat of OUTLINE_CATEGORY_MAP) {
            const om = leadIntro.match(cat.re);
            if (om) {
              outlineBadge = { type: cat.type, label: cat.label };
              break;
            }
          }

          const pDiv = document.createElement("div");
          pDiv.className = "oral-focus-structured-point has-sub-points";
          let innerHtml = `<span class="oral-focus-point-marker">${escapeHtml(markerVal)}</span><div class="oral-focus-point-content">`;
          if (outlineBadge) innerHtml += `<span class="of-outline-badge of-badge-${outlineBadge.type}">${outlineBadge.label}</span>`;
          if (leadIntro) innerHtml += `<div class="of-point-intro">${escapeHtml(leadIntro)}</div>`;
          innerHtml += `<div class="of-sub-points-list">${subItemsHtml}</div></div>`;
          pDiv.innerHTML = innerHtml;
          paragraph.replaceWith(pDiv);
          return;
        }
      }

      // Check outline badge
      let outlineBadge = null;
      for (const cat of OUTLINE_CATEGORY_MAP) {
        const om = bodyText.trimStart().match(cat.re);
        if (om) {
          outlineBadge = { type: cat.type, label: cat.label };
          bodyText = bodyText.slice(bodyText.indexOf(om[0]) + om[0].length).trim();
          break;
        }
      }

      // Check target scope colon
      let targetScope = null;
      const tm = bodyText.trimStart().match(/^([\u4e00-\u9fa5A-Za-z0-9／]{2,8}[：:])/);
      if (tm && !outlineBadge) {
        targetScope = tm[1];
        bodyText = bodyText.slice(bodyText.indexOf(tm[0]) + tm[0].length).trim();
      }

      const pDiv = document.createElement("div");
      pDiv.className = "oral-focus-structured-point of-level-standard";
      let innerHtml = `<span class="oral-focus-point-marker">${escapeHtml(markerVal)}</span><div class="oral-focus-point-content">`;
      if (outlineBadge) innerHtml += `<span class="of-outline-badge of-badge-${outlineBadge.type}">${outlineBadge.label}</span>`;
      innerHtml += `<div class="of-point-body">${targetScope ? `<span class="of-target-scope">${escapeHtml(targetScope)}</span>` : ""}${escapeHtml(bodyText)}</div></div>`;
      pDiv.innerHTML = innerHtml;
      paragraph.replaceWith(pDiv);
      return;
    }
  });

  // Pass 2: Content-level Inline Markup (Metrics, English, Slashes)
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.parentElement?.closest("code, pre, a, .oral-focus-point-marker, .of-section-badge, .of-circle-marker, .of-step-num, .of-sub-num, .of-outline-badge, .of-target-scope, .of-metric-num, .of-term-en")) {
      continue;
    }
    const val = node.textContent;
    if (/[／\dA-Za-z]/.test(val)) {
      textNodes.push(node);
    }
  }

  const metricRe = /(\d+\/\d+|\d+(?:\.\d+)?\s*[:：]\s*\d+|\d+(?:\.\d+)?\s*[~～\-—]\s*\d+(?:\.\d+)?\s*(?:mm|cm|ml|mg|kg|min|周|月|年|岁|倍|度|%|‰|℃|m|g|h|s)?|\d+(?:\.\d+)?\s*(?:mm|cm|ml|mg|kg|min|周|月|年|岁|倍|度|%|‰|℃))/g;
  const enRe = /(?<![A-Za-z0-9])([A-Z]{2,}(?:[-–][0-9A-Za-z]+)?|[A-Z][a-z0-9]+(?:[-–][A-Za-z0-9]+)+|X线)(?![A-Za-z0-9])/g;

  textNodes.forEach((node) => {
    const raw = node.textContent;
    if (!raw) return;

    const hasSlash = raw.includes("／");
    const hasMetric = metricRe.test(raw);
    metricRe.lastIndex = 0;
    const hasEn = enRe.test(raw);
    enRe.lastIndex = 0;

    if (!hasSlash && !hasMetric && !hasEn) return;

    let html = escapeHtml(raw);

    if (hasSlash) {
      html = html.replace(/／/g, '<span class="oral-focus-source-separator">／</span>');
    }

    if (hasMetric) {
      html = html.replace(metricRe, '<span class="of-metric-num of-cloze-item" title="点击遮罩/翻开">$1</span>');
    }

    if (hasEn) {
      html = html.replace(enRe, '<span class="of-term-en of-cloze-item" title="点击遮罩/翻开">$1</span>');
    }

    const span = document.createElement("span");
    span.innerHTML = html;
    node.replaceWith(span);
  });

  // Wire up cloze item click events
  root.querySelectorAll(".of-cloze-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      el.classList.toggle("is-revealed");
    });
  });

  // Pass 3: Extract Outline Stream (提纲骨架徽章流) for multi-point questions
  const badges = [...root.querySelectorAll(".of-outline-badge")];
  if (badges.length >= 2 && !root.querySelector(".of-outline-stream")) {
    const streamEl = document.createElement("div");
    streamEl.className = "of-outline-stream";
    streamEl.setAttribute("role", "navigation");
    streamEl.setAttribute("aria-label", "考点提纲速览");

    const titleEl = document.createElement("span");
    titleEl.className = "of-stream-title";
    titleEl.innerHTML = `<i data-lucide="compass"></i> 提纲骨架`;
    streamEl.appendChild(titleEl);

    const chipsContainer = document.createElement("div");
    chipsContainer.className = "of-stream-chips";

    badges.forEach((badge, bIdx) => {
      const chip = document.createElement("button");
      chip.type = "button";
      const badgeClass = [...badge.classList].find((c) => c.startsWith("of-badge-")) || "";
      chip.className = `of-stream-chip ${badgeClass}`;
      chip.textContent = badge.textContent.trim();

      const targetParent = badge.closest(".oral-focus-structured-point, .of-section-header") || badge;
      if (!targetParent.id) {
        targetParent.id = `of-point-${Math.random().toString(36).slice(2, 7)}-${bIdx}`;
      }

      chip.addEventListener("click", (e) => {
        e.stopPropagation();
        targetParent.scrollIntoView({ behavior: "smooth", block: "center" });
        targetParent.classList.add("is-highlight-target");
        window.setTimeout(() => targetParent.classList.remove("is-highlight-target"), 1400);
      });
      chipsContainer.appendChild(chip);
    });

    streamEl.appendChild(chipsContainer);
    root.prepend(streamEl);
  }
}

export function renderOralFocusChapterCards(focusItemId = "") {
  const payload = state.oralFocusChapter; if (!payload) return;
  const items = payload.items || [];
  const completed = items.filter((item) => item.progress?.memory_note?.trim() || item.progress?.answer?.trim() || item.progress?.mastery !== "unseen").length;
  $("oralFocusChapterTitle").textContent = payload.chapter?.title || "未分章";
  $("oralFocusChapterSummary").textContent = `${formatInteger(completed)} / ${formatInteger(items.length)}`;
  $("oralFocusChapterAnswerToggle").setAttribute("aria-checked", String(state.oralFocusReferenceVisible));
  $("oralFocusChapterAnswerToggle").querySelector("span").textContent = state.oralFocusReferenceVisible ? "完整答案" : "只看题目";
  const clozeToggle = $("oralFocusClozeToggle");
  if (clozeToggle) {
    clozeToggle.setAttribute("aria-checked", String(state.oralFocusClozeMode));
    clozeToggle.classList.toggle("active", Boolean(state.oralFocusClozeMode));
    const span = clozeToggle.querySelector("span");
    if (span) span.textContent = state.oralFocusClozeMode ? "遮罩已开" : "背诵遮罩";
  }
  $("oralFocusItems").classList.toggle("answers-visible", state.oralFocusReferenceVisible);
  $("oralFocusItems").classList.toggle("cloze-mode-active", Boolean(state.oralFocusClozeMode));
  $("oralFocusItems").innerHTML = items.map((item, index) => {
    const mode = state.oralFocusCardModes.get(item.id) || "answer";
    const noteExpanded = state.oralFocusExpandedNotes.has(item.id);
    const showBody = state.oralFocusReferenceVisible || noteExpanded;
    const note = item.progress?.memory_note || "";
    const hasNote = Boolean(note.trim());
    const star = item.star_level ? `<span class="oral-focus-card-stars" aria-label="${item.star_level} 星">${"★".repeat(item.star_level)}</span>` : "";
    const tags = (item.source_tags && item.source_tags.length)
      ? `<div class="oral-focus-card-tags">${item.source_tags.map((t) => `<span class="of-tag">${escapeHtml(t)}</span>`).join("")}</div>`
      : "";
    const missingBadge = item.answer_status === "source_missing"
      ? `<span class="of-badge-missing" title="原资料未提供参考答案">原资料无答案</span>`
      : "";
    const bilingualHint = item.type === "definition" && /^[A-Za-z]/.test(item.title || "")
      ? `<div class="of-bilingual-hint-box"><span class="of-bilingual-tag">英文名解</span><small>先回忆中文译名，再阐述核心定义</small></div>`
      : "";
    const body = !showBody ? "" : `<div class="oral-focus-card-body">
      <nav class="oral-focus-card-tabs" aria-label="答案与笔记">
        <button type="button" data-oral-card-mode="answer" data-oral-card-id="${escapeHtml(item.id)}" class="${mode === "answer" ? "active" : ""}" ${state.oralFocusReferenceVisible ? "" : "disabled"}>权威解析</button>
        <button type="button" data-oral-card-mode="note" data-oral-card-id="${escapeHtml(item.id)}" class="${mode === "note" ? "active" : ""}">学习笔记 ${hasNote ? "•" : ""}</button>
      </nav>
      <section class="${mode === "answer" ? "" : "hidden"}" data-oral-card-answer>${state.oralFocusReferenceVisible ? oralFocusAnswerHtml(item) : ""}</section>
      <section class="oral-focus-card-note ${mode === "note" ? "" : "hidden"}" data-oral-card-note>
        ${hasNote ? `<article class="knowledge-article of-saved-note">${renderMarkdown(note)}</article>` : `<div class="of-note-empty-hint"><p>这道题还没有补充笔记。</p><button type="button" class="of-add-note-inline-btn" data-oral-note-open="${escapeHtml(item.id)}"><i data-lucide="edit-3"></i> 立即记录笔记</button></div>`}
      </section>
    </div>`;

    return `<article class="oral-focus-study-card${focusItemId === item.id ? " is-focused" : ""}" data-oral-card="${escapeHtml(item.id)}">
      <header>
        <span class="oral-card-index">${String(index + 1).padStart(2, "0")}</span>
        <div class="oral-card-header-main">
          <h4>${escapeHtml(item.title)}</h4>
          ${bilingualHint}
          ${tags}
        </div>
        <div class="oral-focus-card-tools">
          ${missingBadge}
          ${star}
          <button type="button" class="oral-card-note-btn${hasNote ? " has-note" : ""}" data-oral-note-open="${escapeHtml(item.id)}" aria-label="编辑《${escapeHtml(item.title)}》的 Obsidian 笔记" title="${hasNote ? "已记录笔记 · 点击查看或编辑" : "补充笔记"}">
            <img src="/assets/obsidian.svg" alt="" aria-hidden="true">
            ${hasNote ? '<span class="oral-note-dot" title="已有笔记"></span>' : ""}
          </button>
        </div>
      </header>
      ${body}
    </article>`;
  }).join("");
  $("oralFocusItems").querySelectorAll("[data-oral-card-mode]").forEach((button) => button.addEventListener("click", () => { state.oralFocusCardModes.set(button.dataset.oralCardId, button.dataset.oralCardMode); renderOralFocusChapterCards(button.dataset.oralCardId); }));
  $("oralFocusItems").querySelectorAll("[data-oral-note-open]").forEach((button) => button.addEventListener("click", () => openOralFocusCardNote(button.dataset.oralNoteOpen)));
  $("oralFocusItems").querySelectorAll(".oral-focus-answer-copy").forEach(enhanceOralFocusSource);
  refreshIcons();
  if (focusItemId) window.setTimeout(() => $("oralFocusItems").querySelector(`[data-oral-card="${focusItemId}"]`)?.scrollIntoView({ block: "center", behavior: "auto" }), 0);
}

export async function openOralFocusChapter(chapterId, focusItemId = "", initialMode = "list") {
  if (!chapterId) return;
  state.oralFocusChapterId = chapterId;
  $("oralFocusChapterList").classList.add("hidden");
  $("oralFocusChapterPanel").classList.remove("hidden");
  $("oralFocusItems").innerHTML = `<div class="practice-reading-loading">正在读取章节题目…</div>`;
  try {
    if (chapterId === "due-session") {
      const response = await fetch("/api/oral-focus/due-session", { cache: "no-store" });
      if (!response.ok) throw new Error("due session unavailable");
      state.oralFocusChapter = await response.json();
    } else {
      const typeQuery = state.oralFocusTypeFilter ? `&type=${encodeURIComponent(state.oralFocusTypeFilter)}` : "";
      const revealQuery = state.oralFocusReferenceVisible ? "&reveal=1" : "";
      const response = await fetch(`/api/oral-focus/chapter?subject_id=${encodeURIComponent(state.oralFocusSubjectId)}&chapter_id=${encodeURIComponent(chapterId)}${typeQuery}${revealQuery}`, { cache: "no-store" });
      if (!response.ok) throw new Error("chapter unavailable");
      state.oralFocusChapter = await response.json();
    }
    setOralFocusViewMode(initialMode || (chapterId === "due-session" ? "card" : "list"));
    renderOralFocusChapterCards(focusItemId);
    const firstItem = (state.oralFocusChapter.items || []).find((it) => it.id === focusItemId) || state.oralFocusChapter.items?.[0] || null;
    if (firstItem) {
      state.oralFocusItem = firstItem;
      $("oralFocusNote").value = firstItem.progress?.memory_note || "";
      $("oralFocusObsidian").href = firstItem.obsidian_uri || "obsidian://open";
      $("oralFocusNoteSaved").textContent = firstItem.progress?.memory_note?.trim() ? (firstItem.progress?.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
    }
    $("oralFocusNoteFloat")?.classList.remove("hidden");
    const subject = state.oralFocusChapter.subject || {};
    startWorkspaceTimer({ activity_type: "subjective_practice", domain: "medicine", subject_id: subject.title || subject.id, resource_id: `oral-focus:${subject.id}`, item_id: focusItemId || `chapter:${chapterId}`, resume_target: { view: "oral_focus", resource_id: `oral-focus:${subject.id}`, item_id: focusItemId || "" } });
  } catch {
    $("oralFocusItems").innerHTML = `<div class="knowledge-index-empty"><strong>暂时无法读取该章节题目</strong></div>`;
  }
}

export async function toggleOralFocusChapterAnswers() {
  state.oralFocusReferenceVisible = !state.oralFocusReferenceVisible;
  try { localStorage.setItem(ORAL_REFERENCE_STORAGE_KEY, String(state.oralFocusReferenceVisible)); } catch {}
  if (state.oralFocusReferenceVisible && !state.oralFocusChapter?.reference_revealed && state.oralFocusChapterId) {
    await openOralFocusChapter(state.oralFocusChapterId);
    return;
  }
  renderOralFocusChapterCards();
}

export function toggleOralFocusClozeMode() {
  state.oralFocusClozeMode = !state.oralFocusClozeMode;
  try { localStorage.setItem(ORAL_CLOZE_STORAGE_KEY, String(state.oralFocusClozeMode)); } catch {}
  renderOralFocusChapterCards();
}

export async function openOralFocusCardNote(itemId) {
  const item = state.oralFocusChapter?.items?.find((entry) => entry.id === itemId);
  if (!item) return;
  state.oralFocusItem = item;
  state.oralFocusCardModes.set(itemId, "note");
  state.oralFocusExpandedNotes.add(itemId);
  renderOralFocusChapterCards(itemId);
  $("oralFocusNote").value = item.progress?.memory_note || "";
  $("oralFocusObsidian").href = item.obsidian_uri || "obsidian://open";
  $("oralFocusNoteSaved").textContent = item.progress?.memory_note?.trim() ? (item.progress?.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
  setOralFocusNoteOpen(true);
}

export function renderOralFocusNoteContent() {
  const markdown = $("oralFocusNote")?.value || state.oralFocusItem?.progress?.memory_note || "";
  $("oralFocusNoteContent").classList.toggle("hidden", !markdown.trim());
  $("oralFocusNoteBody").innerHTML = markdown.trim() ? renderMarkdown(markdown) : "";
}

export async function loadOralFocus() {
  const response = await fetch("/api/oral-focus", { cache: "no-store" });
  if (!response.ok) throw new Error("oral focus unavailable");
  state.oralFocus = await response.json();
  if (!state.oralFocusSubjectId) state.oralFocusSubjectId = state.oralFocus.subjects?.[0]?.id || "";
  return state.oralFocus;
}

export async function openOralFocusIndex(subjectId = "", type = null) {
  setRouteHash("library/oral-focus"); stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("oralFocus");
  setOralFocusNoteOpen(false); $("oralFocusNoteFloat").classList.add("hidden");
  $("oralFocusDirectory").classList.remove("hidden");
  try {
    if (!state.oralFocus?.available) await loadOralFocus();
    if (type !== null) {
      if (type !== state.oralFocusTypeFilter) {
        state.oralFocusChapterId = ""; state.oralFocusChapter = null;
      }
      state.oralFocusTypeFilter = type;
      try { localStorage.setItem(ORAL_FOCUS_TYPE_STORAGE_KEY, type); } catch {}
    } else if (!state.oralFocusTypeFilter) {
      try {
        state.oralFocusTypeFilter = localStorage.getItem(ORAL_FOCUS_TYPE_STORAGE_KEY) || "definition";
      } catch {
        state.oralFocusTypeFilter = "definition";
      }
    }
    if (subjectId && subjectId !== state.oralFocusSubjectId) {
      state.oralFocusChapterId = ""; state.oralFocusChapter = null;
      state.oralFocusSubjectId = subjectId;
    }
    renderOralFocusDirectory();
  } catch {
    state.oralFocus = { available: false, subjects: [] }; renderOralFocusDirectory();
  }
  window.scrollTo({ top: 0, behavior: "auto" });
}

export async function openOralFocusItem(itemId) {
  if (!itemId) return;
  setRouteHash("library/oral-focus"); stopReadingTimer(); closeNotePopover(); $("sectionNoteFloat").classList.add("hidden"); setActiveView("oralFocus");
  $("oralFocusDirectory").classList.remove("hidden");
  try {
    if (!state.oralFocus?.available) await loadOralFocus();
    const response = await fetch(`/api/oral-focus/item?item_id=${encodeURIComponent(itemId)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("item unavailable");
    const item = await response.json(); state.oralFocusSubjectId = item.subject?.id || state.oralFocusSubjectId;
    state.oralFocusTypeFilter = item.type || state.oralFocusTypeFilter; renderOralFocusDirectory();
    await openOralFocusChapter(item.chapter?.id, itemId);
  } catch { $("oralFocusChapterList").innerHTML = `<div class="knowledge-index-empty"><strong>暂时无法读取这道题</strong></div>`; }
}

export async function toggleOralFocusReference() {
  const item = state.oralFocusItem; if (!item) return;
  state.oralFocusReferenceVisible = !state.oralFocusReferenceVisible;
  try { localStorage.setItem(ORAL_REFERENCE_STORAGE_KEY, String(state.oralFocusReferenceVisible)); } catch {}
  if (state.oralFocusReferenceVisible && !item.reference_revealed) {
    const response = await fetch(`/api/oral-focus/item?item_id=${encodeURIComponent(item.id)}&reveal=1`, { cache: "no-store" });
    if (!response.ok) { state.oralFocusReferenceVisible = false; showToast("暂时无法读取标准答案"); return; }
    const revealed = await response.json();
    state.oralFocusItem = { ...revealed, progress: item.progress };
  }
  renderOralFocusChapterCards();
}

export async function saveOralFocusNote() {
  const item = state.oralFocusItem; if (!item || !state.oralFocusNoteDirty) return;
  window.clearTimeout(state.oralFocusSaveTimer); state.oralFocusSaveTimer = null;
  const memoryNote = $("oralFocusNote").value;
  $("oralFocusNoteSaved").textContent = "保存中…";
  try {
    const response = await fetch("/api/oral-focus/progress", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ item_id: item.id, answer: item.progress?.answer || "", memory_note: memoryNote, mastery: item.progress?.mastery || "unseen" }) });
    if (!response.ok) throw new Error("save failed");
    const result = await response.json(); item.progress = result.progress; state.oralFocusNoteDirty = false;
    const directoryItem = (state.oralFocus?.subjects || []).flatMap((subject) => subject.chapters || []).flatMap((chapter) => chapter.items || []).find((entry) => entry.id === item.id);
    if (directoryItem) directoryItem.completed = result.saved;
    const chapterItem = state.oralFocusChapter?.items?.find((entry) => entry.id === item.id);
    if (chapterItem) chapterItem.progress = result.progress;
    $("oralFocusObsidian").href = result.obsidian_uri || item.obsidian_uri || "obsidian://open";
    $("oralFocusNoteSaved").textContent = memoryNote.trim() ? (result.storage === "obsidian" ? "已保存到 Obsidian" : "已自动保存") : "输入后自动保存";
    const cardEl = $("oralFocusItems")?.querySelector(`[data-oral-card="${item.id}"]`);
    if (cardEl) {
      const noteBtn = cardEl.querySelector(".oral-card-note-btn");
      const hasNote = Boolean(memoryNote.trim());
      noteBtn?.classList.toggle("has-note", hasNote);
      if (!noteBtn?.querySelector(".oral-note-dot") && hasNote) {
        const dot = document.createElement("span");
        dot.className = "oral-note-dot";
        noteBtn?.appendChild(dot);
      } else if (noteBtn?.querySelector(".oral-note-dot") && !hasNote) {
        noteBtn?.querySelector(".oral-note-dot")?.remove();
      }
    }
  } catch { $("oralFocusNoteSaved").textContent = "保存失败，请稍后重试"; }
}

export function scheduleOralFocusNoteSave() {
  if (!state.oralFocusItem) return;
  state.oralFocusItem.progress.memory_note = $("oralFocusNote").value;
  renderOralFocusNoteContent();
  state.oralFocusNoteDirty = true; $("oralFocusNoteSaved").textContent = "保存中…"; window.clearTimeout(state.oralFocusSaveTimer);
  state.oralFocusSaveTimer = window.setTimeout(saveOralFocusNote, 420);
}

export function setOralFocusNoteOpen(open) {
  state.oralFocusNoteOpen = open;
  const floatEl = $("oralFocusNoteFloat");
  const popover = $("oralFocusNotePopover");
  if (open) {
    floatEl?.classList.remove("hidden");
    floatEl?.classList.add("note-is-open");
    popover?.classList.add("is-open");
    popover?.setAttribute("aria-hidden", "false");
    $("toggleOralFocusNote")?.setAttribute("aria-expanded", "true");
    window.setTimeout(() => $("oralFocusNote")?.focus(), 120);
  } else {
    floatEl?.classList.remove("note-is-open");
    popover?.classList.remove("is-open");
    popover?.setAttribute("aria-hidden", "true");
    $("toggleOralFocusNote")?.setAttribute("aria-expanded", "false");
  }
}

export async function navigateOralFocus(step) {
  const index = state.oralFocusFlatItems.findIndex((entry) => entry.id === state.oralFocusItem?.id);
  const target = state.oralFocusFlatItems[index + step]; if (!target) return;
  await saveOralFocusNote(); openOralFocusItem(target.id);
}

let flashcardIndex = 0;
let isFlashcardFlipped = false;
let oralViewMode = "list";

export function setOralFocusViewMode(mode) {
  oralViewMode = mode;
  $("oralModeListBtn")?.classList.toggle("active", mode === "list");
  $("oralModeCardBtn")?.classList.toggle("active", mode === "card");
  $("oralFocusItems")?.classList.toggle("hidden", mode !== "list");
  $("oralFocusFlashcardDeck")?.classList.toggle("hidden", mode !== "card");

  if (mode === "card") {
    flashcardIndex = 0;
    renderOralFlashcard();
  }
}

export function renderOralFlashcard() {
  const items = state.oralFocusChapter?.items || [];
  const deck = $("oralFocusFlashcardDeck");
  if (!deck || !items.length) return;

  if (flashcardIndex < 0) flashcardIndex = 0;
  if (flashcardIndex >= items.length) flashcardIndex = items.length - 1;

  const item = items[flashcardIndex];
  isFlashcardFlipped = false;
  $("fcCard")?.classList.remove("is-flipped");

  if ($("fcCounterText")) $("fcCounterText").textContent = `第 ${flashcardIndex + 1} / ${items.length} 题`;
  if ($("fcMetaText")) {
    const starText = item.star_level ? "★".repeat(item.star_level) + " 重点" : "";
    const masteryText = item.progress?.mastery === "mastered" ? "🟢 已熟记" : item.progress?.mastery === "fuzzy" ? "🟡 需巩固" : "⚪ 未掌握";
    $("fcMetaText").textContent = [starText, masteryText].filter(Boolean).join(" · ");
  }
  if ($("fcCardType")) $("fcCardType").textContent = item.type === "definition" ? "名词解释" : "简答论述";
  if ($("fcCardSubject")) $("fcCardSubject").textContent = state.oralFocusChapter?.subject?.title || "医学全书";
  if ($("fcFrontStem")) {
    const isBilingual = item.type === "definition" && /^[A-Za-z]/.test(item.title || "");
    const tagsHtml = (item.source_tags && item.source_tags.length)
      ? `<div class="fc-front-tags">${item.source_tags.map((t) => `<span class="of-tag">${escapeHtml(t)}</span>`).join("")}</div>`
      : "";
    $("fcFrontStem").innerHTML = `<div class="fc-front-title">${escapeHtml(item.title || "")}</div>${isBilingual ? `<div class="fc-bilingual-hint">先在心中回忆【中文译名】与【核心定义】</div>` : ""}${tagsHtml}`;
  }
  if ($("fcBackContent")) {
    $("fcBackContent").innerHTML = oralFocusAnswerHtml(item);
    enhanceOralFocusSource($("fcBackContent"));
  }

  if ($("fcPrevBtn")) $("fcPrevBtn").disabled = flashcardIndex <= 0;
  if ($("fcNextBtn")) $("fcNextBtn").disabled = flashcardIndex >= items.length - 1;

  refreshIcons();
}

export function flipFlashcard(forceState = null) {
  if (forceState !== null) {
    isFlashcardFlipped = forceState;
  } else {
    isFlashcardFlipped = !isFlashcardFlipped;
  }
  $("fcCard")?.classList.toggle("is-flipped", isFlashcardFlipped);
}

export function stepFlashcard(delta) {
  const items = state.oralFocusChapter?.items || [];
  const next = flashcardIndex + delta;
  if (next >= 0 && next < items.length) {
    flashcardIndex = next;
    renderOralFlashcard();
  }
}

export async function submitFlashcardRating(rating, days) {
  const items = state.oralFocusChapter?.items || [];
  const item = items[flashcardIndex];
  if (!item) return;

  try {
    const res = await fetch("/api/oral-focus/progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        item_id: item.id,
        mastery: rating,
        eb_interval_days: days,
        answer: item.progress?.answer || "",
        memory_note: item.progress?.memory_note || "",
      }),
    });
    if (!res.ok) throw new Error("progress failed");
    const result = await res.json();
    item.progress = result.progress;

    if (rating === "mastered") {
      showToast(`🟢 已掌握！艾宾浩斯排程：+${days}天后复查`);
    } else if (rating === "fuzzy") {
      showToast(`🟡 模糊犹豫！排程：明天(+${days}天)重点复习`);
    } else {
      showToast(`🔴 完全遗忘！已移入今日待背队列`);
    }

    if (flashcardIndex < items.length - 1) {
      flashcardIndex += 1;
      renderOralFlashcard();
    } else {
      renderOralFlashcard();
      showToast("🎉 本章所有重点词条背诵完成！");
    }
  } catch {
    showToast("保存进度失败，请重试");
  }
}

let flashcardEventsBound = false;
export function bindFlashcardEvents() {
  if (flashcardEventsBound) return;

  $("oralModeListBtn")?.addEventListener("click", () => setOralFocusViewMode("list"));
  $("oralModeCardBtn")?.addEventListener("click", () => setOralFocusViewMode("card"));
  $("fcCard")?.addEventListener("click", (e) => {
    if (e.target.closest("button") || e.target.closest("a")) return;
    flipFlashcard();
  });
  $("fcUnflipBtn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    flipFlashcard(false);
  });
  $("fcPrevBtn")?.addEventListener("click", () => stepFlashcard(-1));
  $("fcNextBtn")?.addEventListener("click", () => stepFlashcard(1));

  document.querySelectorAll("#fcEbbinghausControls [data-eb-rating]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rating = btn.dataset.ebRating;
      const days = parseInt(btn.dataset.ebDays || "1", 10);
      submitFlashcardRating(rating, days);
    });
  });

  window.addEventListener("keydown", (e) => {
    const deck = $("oralFocusFlashcardDeck");
    if (!deck || deck.classList.contains("hidden") || $("oralFocusView")?.classList.contains("hidden")) return;
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.code === "Space") {
      e.preventDefault();
      flipFlashcard();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      stepFlashcard(-1);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      stepFlashcard(1);
    } else if (e.key === "1") {
      submitFlashcardRating("learning", 1);
    } else if (e.key === "2") {
      submitFlashcardRating("fuzzy", 2);
    } else if (e.key === "3") {
      submitFlashcardRating("mastered", 4);
    }
  });

  flashcardEventsBound = true;
}

window.openOralFocusIndex = openOralFocusIndex;
window.renderOralFocusDueBanner = renderOralFocusDueBanner;
