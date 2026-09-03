import { $ } from "../core/state.js";
import { escapeHtml, refreshIcons } from "../core/utils.js";
import { openSection } from "../views/reader.js";
import { openOralFocusItem } from "./oral_focus.js";
import { openPractice } from "./practice.js";

let searchDebounceTimer = null;
let currentSearchCategory = "";
let searchResults = [];
let selectedIndex = 0;

export function openGlobalSearch() {
  const modal = $("globalSearchModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  const input = $("globalSearchInput");
  if (input) {
    input.value = "";
    input.focus();
  }
  searchResults = [];
  selectedIndex = 0;
  renderSearchResults();
}

export function closeGlobalSearch() {
  const modal = $("globalSearchModal");
  if (!modal) return;
  modal.classList.add("hidden");
}

export async function executeSearch(query) {
  const q = (query || "").trim();
  if (!q) {
    searchResults = [];
    selectedIndex = 0;
    renderSearchResults();
    return;
  }

  try {
    const params = new URLSearchParams({ q });
    if (currentSearchCategory) params.set("category", currentSearchCategory);
    const res = await fetch(`/api/search?${params}`, { cache: "no-store" });
    if (!res.ok) throw new Error("search failed");
    const data = await res.json();
    searchResults = data.results || [];
    selectedIndex = 0;
    renderSearchResults(q);
  } catch {
    searchResults = [];
    renderSearchResults(q);
  }
}

export function renderSearchResults(query = "") {
  const list = $("globalSearchResults");
  if (!list) return;

  if (!query) {
    list.innerHTML = `<div class="gs-hint-box">
      <i data-lucide="compass"></i>
      <strong>输入关键词穿透秒搜</strong>
      <span>支持检索：医学教材各章节、口腔重点名词解释与论述、政治理论真题、考研英语阅读与真题。</span>
    </div>`;
    refreshIcons();
    return;
  }

  if (!searchResults.length) {
    list.innerHTML = `<div class="gs-empty-box">
      <i data-lucide="search-x"></i>
      <strong>未找到与 “${escapeHtml(query)}” 相关的资料</strong>
      <span>请尝试更短的关键词、拼音或切换分类筛选。</span>
    </div>`;
    refreshIcons();
    return;
  }

  list.innerHTML = searchResults.map((item, idx) => {
    const isSelected = idx === selectedIndex;
    return `
      <div class="gs-result-item ${isSelected ? "is-active" : ""}" data-result-index="${idx}">
        <div class="gs-item-icon"><i data-lucide="${escapeHtml(item.icon || "file-text")}"></i></div>
        <div class="gs-item-content">
          <div class="gs-item-top">
            <span class="gs-item-type">${escapeHtml(item.category_label || "")}</span>
            <strong class="gs-item-title">${highlightMatch(escapeHtml(item.title), query)}</strong>
          </div>
          ${item.snippet ? `<p class="gs-item-snippet">${highlightMatch(escapeHtml(item.snippet), query)}</p>` : ""}
          ${item.subtitle ? `<span class="gs-item-sub">${escapeHtml(item.subtitle)}</span>` : ""}
        </div>
        <div class="gs-item-jump"><i data-lucide="corner-down-left"></i></div>
      </div>
    `;
  }).join("");

  list.querySelectorAll(".gs-result-item").forEach((el) => {
    el.addEventListener("click", () => {
      const idx = parseInt(el.dataset.resultIndex, 10);
      selectResult(idx);
    });
  });

  refreshIcons();
}

function highlightMatch(text, query) {
  if (!query) return text;
  const escapedQuery = query.replace(/[-\/\\^$*+?.()|[\]{}]/g, "\\$&");
  const regex = new RegExp(`(${escapedQuery})`, "gi");
  return text.replace(regex, "<mark>$1</mark>");
}

function selectResult(index) {
  const item = searchResults[index];
  if (!item || !item.target) return;

  closeGlobalSearch();
  const target = item.target;

  if (target.view === "reader") {
    openSection(target.section_id);
  } else if (target.view === "oral_focus") {
    openOralFocusItem(target.item_id);
  } else if (target.view === "practice") {
    openPractice({ bank_id: target.resource_id, question_id: target.question_id }, "all", 0);
  }
}

let searchBound = false;
export function bindGlobalSearch() {
  if (searchBound) return;

  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      const modal = $("globalSearchModal");
      if (modal?.classList.contains("hidden")) {
        openGlobalSearch();
      } else {
        closeGlobalSearch();
      }
    }
  });

  $("globalSearchBackdrop")?.addEventListener("click", closeGlobalSearch);
  $("globalSearchClose")?.addEventListener("click", closeGlobalSearch);
  $("topSearchTrigger")?.addEventListener("click", openGlobalSearch);
  $("homeSearchTrigger")?.addEventListener("click", openGlobalSearch);
  $("homeSearchTrigger")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openGlobalSearch();
    }
  });

  const input = $("globalSearchInput");
  input?.addEventListener("input", () => {
    window.clearTimeout(searchDebounceTimer);
    searchDebounceTimer = window.setTimeout(() => {
      executeSearch(input.value);
    }, 160);
  });

  input?.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeGlobalSearch();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (searchResults.length) {
        selectedIndex = (selectedIndex + 1) % searchResults.length;
        updateActiveItem();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (searchResults.length) {
        selectedIndex = (selectedIndex - 1 + searchResults.length) % searchResults.length;
        updateActiveItem();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (searchResults.length && selectedIndex >= 0) {
        selectResult(selectedIndex);
      }
    }
  });

  document.querySelectorAll("#gsCategoryFilter [data-gs-cat]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#gsCategoryFilter [data-gs-cat]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentSearchCategory = btn.dataset.gsCat || "";
      executeSearch(input?.value || "");
    });
  });

  searchBound = true;
}

function updateActiveItem() {
  const items = document.querySelectorAll("#globalSearchResults .gs-result-item");
  items.forEach((item, idx) => {
    const isActive = idx === selectedIndex;
    item.classList.toggle("is-active", isActive);
    if (isActive) {
      item.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
}
