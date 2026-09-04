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
      output = output.replace(/\$\\(?:to|rightarrow)\$/g, "→");
      output = output.replace(/\$\\leftarrow\$/g, "←");
      output = output.replace(/\$\\leftrightarrow\$/g, "↔");
      output = output.replace(/\$\\Rightarrow\$/g, "⇒");
      output = output.replace(/\$\\Leftarrow\$/g, "⇐");
      output = output.replace(/\$\\Leftrightarrow\$/g, "⇔");
      output = output.replace(/\$\\approx\$/g, "≈");
      output = output.replace(/\$\\pm\$/g, "±");
      output = output.replace(/\$\\times\$/g, "×");
      output = output.replace(/\$\\div\$/g, "÷");
      output = output.replace(/\$\\le(?:q)?\$/g, "≤");
      output = output.replace(/\$\\ge(?:q)?\$/g, "≥");
      output = output.replace(/\$\\neq\$/g, "≠");
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

    function renderListGroup(items, imageBase) {
      if (!items || items.length === 0) return "";
      let html = "";
      let i = 0;
      while (i < items.length) {
        const isOrdered = items[i].ordered;
        const tag = isOrdered ? "ol" : "ul";
        html += `<${tag}>`;
        while (i < items.length && items[i].ordered === isOrdered) {
          const item = items[i];
          const content = inlineMarkdown(item.lines.join(" "), imageBase);
          const subList = item.children.length > 0 ? renderListGroup(item.children, imageBase) : "";
          html += `<li>${content}${subList}</li>`;
          i += 1;
        }
        html += `</${tag}>`;
      }
      return html;
    }

    function parseListBlock(lines, startIndex, imageBase) {
      let index = startIndex;
      const root = { children: [] };
      const stack = [{ node: root, indent: -1 }];
      let lastItem = null;

      while (index < lines.length) {
        const rawLine = lines[index];

        if (!rawLine.trim()) {
          let peek = index + 1;
          let blankCount = 1;
          while (peek < lines.length && !lines[peek].trim()) {
            peek += 1;
            blankCount += 1;
          }
          if (blankCount >= 2 || peek >= lines.length) {
            break;
          }
          const nextLine = lines[peek];
          const nextItemMatch = nextLine.match(/^(\s*)([-*+]|\d+[.)])(?:\s+(.*)|\s*)$/);
          if (nextItemMatch) {
            index = peek;
            continue;
          } else {
            break;
          }
        }

        const itemMatch = rawLine.match(/^(\s*)([-*+]|\d+[.)])(?:\s+(.*)|\s*)$/);
        if (itemMatch) {
          const indentStr = itemMatch[1].replace(/\t/g, "  ");
          const indent = indentStr.length;
          const marker = itemMatch[2];
          const ordered = /^\d/.test(marker);
          const text = itemMatch[3] || "";

          const newItem = {
            ordered,
            indent,
            lines: text.trim() ? [text.trim()] : [],
            children: []
          };

          while (stack.length > 1 && indent <= stack[stack.length - 1].indent) {
            stack.pop();
          }

          const parent = stack[stack.length - 1].node;
          parent.children.push(newItem);
          stack.push({ node: newItem, indent });
          lastItem = newItem;
          index += 1;
          continue;
        }

        if (lastItem && /^(\s{2,}|\t)/.test(rawLine)) {
          if (/^\s*(#{1,6}\s|[-*_]{3,}\s*$|<table\b|\||>)/i.test(rawLine)) {
            break;
          }
          lastItem.lines.push(rawLine.trim());
          index += 1;
          continue;
        }

        break;
      }

      const html = renderListGroup(root.children, imageBase);
      return { html, nextIndex: index };
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
        if (/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(line)) { blocks.push("<hr>"); index += 1; continue; }
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
        if (/^\s*([-*+]|\d+[.)])(?:\s+.*|\s*)$/.test(line)) {
          const result = parseListBlock(lines, index, imageBase);
          blocks.push(result.html);
          index = result.nextIndex;
          continue;
        }
        const paragraph = [line.trim()]; index += 1;
        while (
          index < lines.length &&
          lines[index].trim() &&
          !/^(#{1,6})\s/.test(lines[index]) &&
          !/^\s*([-*_])(?:\s*\1){2,}\s*$/.test(lines[index]) &&
          !/^\s*<table\b/i.test(lines[index]) &&
          !/^\s*([-*+]|\d+[.)])(?:\s+.*|\s*)$/.test(lines[index]) &&
          !/^\s*(>|\|)/.test(lines[index])
        ) paragraph.push(lines[index++].trim());
        blocks.push(`<p>${inlineMarkdown(paragraph.join(" "), imageBase)}</p>`);
      }
      return blocks.join("") || `<div class="section-material-empty"><i data-lucide="file-text"></i><strong>暂无内容</strong><span>这一节还没有可以展示的 Markdown。</span></div>`;
    }

    return { inlineMarkdown, renderMarkdown };
  }

  global.YuReaderMarkdown = Object.freeze({ create });
})(window);
