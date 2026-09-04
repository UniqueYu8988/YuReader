import { $, state } from "../core/state.js";
import { escapeHtml, formatInteger, refreshIcons, showToast } from "../core/utils.js";
import { openPractice } from "../modules/practice.js";

let mistakesFilter = "all";

export async function loadMistakes() {
  try {
    const response = await fetch("/api/practice/mistakes", { cache: "no-store" });
    if (!response.ok) throw new Error("mistakes unavailable");
    const payload = await response.json();
    state.mistakes = payload;
    updateMistakesBadge();
    renderMistakes();
  } catch {
    renderMistakes();
  }
}

export function updateMistakesBadge() {
  const badge = $("mistakesBadge");
  if (!badge) return;
  const pending = Number(state.mistakes?.pending || 0);
  if (pending > 0) {
    badge.textContent = pending > 99 ? "99+" : String(pending);
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

export function renderMistakes() {
  const container = $("mistakesCardList");
  if (!container) return;

  const payload = state.mistakes || { total: 0, pending: 0, resolved: 0, items: [] };
  if ($("mistakesTotalCount")) $("mistakesTotalCount").textContent = formatInteger(payload.total);
  if ($("mistakesPendingCount")) $("mistakesPendingCount").textContent = formatInteger(payload.pending);
  if ($("mistakesResolvedCount")) $("mistakesResolvedCount").textContent = formatInteger(payload.resolved);

  let items = payload.items || [];
  if (mistakesFilter === "politics") items = items.filter((q) => q.domain === "politics");
  else if (mistakesFilter === "english") items = items.filter((q) => q.domain === "english");
  else if (mistakesFilter === "pending") items = items.filter((q) => !q.resolved);
  else if (mistakesFilter === "resolved") items = items.filter((q) => q.resolved);

  if (!items.length) {
    container.innerHTML = `<div class="mistakes-empty-box">
      <i data-lucide="check-circle-2"></i>
      <strong>当前分类下暂无错题</strong>
      <span>${mistakesFilter === "pending" ? "太棒了！所有错题均已被攻破斩杀。" : "在做题中遇到错题后，将自动归纳至此处。"}</span>
    </div>`;
    refreshIcons();
    return;
  }

  container.innerHTML = items.map((q) => {
    const optionsHtml = (q.options || []).map((opt) => {
      const isCorrect = (q.correct_answers || []).includes(opt.label);
      const isSelected = (q.selected_answers || []).includes(opt.label);
      let optClass = "mistake-opt";
      let icon = "";
      if (isCorrect) {
        optClass += " is-correct";
        icon = '<i data-lucide="check"></i>';
      } else if (isSelected) {
        optClass += " is-wrong";
        icon = '<i data-lucide="x"></i>';
      }
      return `<div class="${optClass}">
        <span class="opt-label">${escapeHtml(opt.label || "")}</span>
        <span class="opt-text">${escapeHtml(opt.text || opt.content || "")}</span>
        ${icon}
      </div>`;
    }).join("");

    const analysisHtml = q.source_analysis_md || q.personal_analysis ? `
      <details class="mistake-analysis-drawer">
        <summary><i data-lucide="help-circle"></i> 查看权威解析与笔记</summary>
        <div class="drawer-inner">
          ${q.source_analysis_md ? `<div class="src-analysis"><strong>原书解析：</strong><p>${escapeHtml(q.source_analysis_md)}</p></div>` : ""}
          ${q.personal_analysis ? `<div class="my-analysis"><strong>个人笔记：</strong><p>${escapeHtml(q.personal_analysis)}</p></div>` : ""}
        </div>
      </details>
    ` : "";

    return `
      <article class="mistake-card ${q.resolved ? "is-resolved" : "is-pending"}" data-qid="${escapeHtml(q.question_id)}">
        <div class="mc-header">
          <div class="mc-tags">
            <span class="mc-domain-tag ${q.domain}">${escapeHtml(q.domain_label || "题库")}</span>
            <span class="mc-subject-tag">${escapeHtml(q.subject_label || q.bank_title || "")}</span>
          </div>
          <span class="mc-status-pill ${q.resolved ? "resolved" : "pending"}">
            <i data-lucide="${q.resolved ? "shield-check" : "flame"}"></i>
            ${q.resolved ? "已攻克斩杀" : "待二刷攻坚"}
          </span>
        </div>
        <div class="mc-stem">${escapeHtml(q.stem_md || "")}</div>
        <div class="mc-options">${optionsHtml}</div>
        ${analysisHtml}
        <div class="mc-footer">
          <button type="button" class="mc-redo-btn" data-redo-bank="${escapeHtml(q.bank_id)}" data-redo-qid="${escapeHtml(q.question_id)}">
            <i data-lucide="refresh-cw"></i> 重新作答
          </button>
          <button type="button" class="mc-toggle-resolve-btn" data-qid="${escapeHtml(q.question_id)}" data-current-resolved="${q.resolved ? "true" : "false"}">
            <i data-lucide="${q.resolved ? "rotate-ccw" : "check"}"></i>
            ${q.resolved ? "移入待攻坚" : "标记已斩杀"}
          </button>
        </div>
      </article>
    `;
  }).join("");

  bindCardActions();
  refreshIcons();
}

function bindCardActions() {
  document.querySelectorAll(".mc-redo-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const bankId = btn.dataset.redoBank;
      const qid = btn.dataset.redoQid;
      if (bankId && qid) {
        openPractice({ bank_id: bankId, question_id: qid }, "mistakes", 0);
      }
    });
  });

  document.querySelectorAll(".mc-toggle-resolve-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const qid = btn.dataset.qid;
      const current = btn.dataset.currentResolved === "true";
      const next = !current;
      btn.disabled = true;
      try {
        const res = await fetch("/api/practice/mistakes/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question_id: qid, resolved: next }),
        });
        if (!res.ok) throw new Error("resolve failed");
        showToast(next ? "⚔️ 已斩杀并归档此错题！" : "已重新移入待攻坚清单");
        await loadMistakes();
      } catch {
        showToast("操作失败，请重试");
        btn.disabled = false;
      }
    });
  });
}

let mistakesEventsBound = false;
export function bindMistakesEvents() {
  if (mistakesEventsBound) return;
  document.querySelectorAll("#mistakesFilterTabs [data-mistake-filter]").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("#mistakesFilterTabs [data-mistake-filter]").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      mistakesFilter = tab.dataset.mistakeFilter || "all";
      renderMistakes();
    });
  });

  $("mistakesBatchTrainBtn")?.addEventListener("click", () => {
    let domainParam = "";
    if (mistakesFilter === "politics") domainParam = "politics";
    else if (mistakesFilter === "english") domainParam = "english";
    openPractice({ bank_id: "mistakes-session", knowledge_id: "mistakes", match_level: "mistakes", is_mistakes_session: true, domain: domainParam }, "mistakes", 0);
  });

  mistakesEventsBound = true;
}
