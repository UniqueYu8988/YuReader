(function exposeMarkdownRenderer(global) {
  "use strict";

  function create(escapeHtml) {
    function inlineMarkdown(value, imageBase = "") {
      let output = escapeHtml(value);
      output = output.replace(/&lt;br\s*\/??&gt;/gi, "<br>");
      output = output.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
        if (imageBase && /^(?:\.\/)?images\//.test(url)) url = `${imageBase}${url.replace(/^(?:\.\/)+/, "")}`;
        return `<img src="${escapeHtml(url)}" alt="${escapeHtml(alt)}">`;
      });
      output = output.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${label}</a>`);
      output = output.replace(/`([^`]+)`/g, "<code>$1</code>");
      output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
      output = output.replace(/__([^_]+)__/g, "<strong>$1</strong>");
      output = output.replace(/==([^=]+)==/g, "<mark>$1</mark>");
      return output;
    }

    function splitTableRow(line, imageBase = "") {
      return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => inlineMarkdown(cell.trim(), imageBase));
    }

    function isTableSeparator(line) {
      return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
    }

    function sanitizeTableHtml(value) {
      const documentNode = new DOMParser().parseFromString(String(value), "text/html");
      const table = documentNode.body.querySelector("table");
      if (!table) return `<p>${escapeHtml(value)}</p>`;
      const allowed = new Set(["table", "thead", "tbody", "tfoot", "tr", "th", "td", "br", "sup", "sub"]);
      function sanitizeNode(node) {
        if (node.nodeType === Node.TEXT_NODE) return escapeHtml(node.textContent || "");
        if (node.nodeType !== Node.ELEMENT_NODE) return "";
        const tag = node.tagName.toLowerCase();
        if (!allowed.has(tag)) return [...node.childNodes].map(sanitizeNode).join("");
        let attrs = "";
        if (tag === "td" || tag === "th") {
          ["rowspan", "colspan"].forEach((name) => {
            const raw = node.getAttribute(name);
            if (/^[1-9]\d?$/.test(raw || "")) attrs += ` ${name}="${raw}"`;
          });
        }
        if (tag === "br") return "<br>";
        return `<${tag}${attrs}>${[...node.childNodes].map(sanitizeNode).join("")}</${tag}>`;
      }
      return `<div class="knowledge-table-wrap">${sanitizeNode(table)}</div>`;
    }

    function renderMarkdown(markdown, imageBase = "") {
      const lines = String(markdown || "").replace(/\r/g, "").split("\n");
      const blocks = [];
      let index = 0;
      while (index < lines.length) {
        const line = lines[index];
        if (!line.trim()) { index += 1; continue; }
        const heading = line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
        if (heading) { const level = Math.min(6, heading[1].length); blocks.push(`<h${level}>${inlineMarkdown(heading[2], imageBase)}</h${level}>`); index += 1; continue; }
        if (/^\s*<table\b/i.test(line)) {
          const tableLines = [line]; index += 1;
          while (index < lines.length && !/<\/table>\s*$/i.test(tableLines[tableLines.length - 1])) tableLines.push(lines[index++]);
          blocks.push(sanitizeTableHtml(tableLines.join("\n"))); continue;
        }
        if (/^\s*>/.test(line)) { const quote = []; while (index < lines.length && /^\s*>/.test(lines[index])) quote.push(lines[index++].replace(/^\s*>\s?/, "")); blocks.push(`<blockquote>${inlineMarkdown(quote.join(" "), imageBase)}</blockquote>`); continue; }
        if (/^\s*\|/.test(line) && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
          const rows = []; while (index < lines.length && /^\s*\|/.test(lines[index])) rows.push(splitTableRow(lines[index++], imageBase));
          const head = rows[0] || []; const body = rows.slice(2);
          blocks.push(`<div class="knowledge-table-wrap"><table><thead><tr>${head.map((cell) => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${body.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
          continue;
        }
        const list = line.match(/^\s*([-*+] |\d+[.)]\s+)(.+)$/);
        if (list) {
          const ordered = /^\d/.test(list[1]); const items = [];
          while (index < lines.length) { const item = lines[index].match(/^\s*([-*+] |\d+[.)]\s+)(.+)$/); if (!item || /^\d/.test(item[1]) !== ordered) break; items.push(`<li>${inlineMarkdown(item[2], imageBase)}</li>`); index += 1; }
          blocks.push(`<${ordered ? "ol" : "ul"}>${items.join("")}</${ordered ? "ol" : "ul"}>`); continue;
        }
        const paragraph = [line.trim()]; index += 1;
        while (index < lines.length && lines[index].trim() && !/^(#{1,6})\s/.test(lines[index]) && !/^\s*<table\b/i.test(lines[index]) && !/^\s*([-*+] |\d+[.)]\s+|>|\|)/.test(lines[index])) paragraph.push(lines[index++].trim());
        blocks.push(`<p>${inlineMarkdown(paragraph.join(" "), imageBase)}</p>`);
      }
      return blocks.join("") || `<div class="section-material-empty"><i data-lucide="file-text"></i><strong>暂无内容</strong><span>这一节还没有可以展示的 Markdown。</span></div>`;
    }

    return { inlineMarkdown, renderMarkdown };
  }

  global.YuReaderMarkdown = Object.freeze({ create });
})(window);
