/**
 * YuReader project safety rails for Pi.
 *
 * This is deliberately small: it prevents direct edits to original/user data
 * and immutable/runtime packages while leaving YuBook's supported commands
 * available. It is not a sandbox and does not replace Git or YuBook validation.
 */

import path from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const projectRoot = normalizePath(process.cwd());
const externalBookRoot = normalizePath("C:/Users/Yu/OneDrive/图片/Book/");

function normalizePath(value: string): string {
	return value.replace(/\\/g, "/").replace(/\/{2,}/g, "/").toLowerCase();
}

function absolutePath(value: string): string {
	return normalizePath(path.isAbsolute(value) ? value : path.resolve(process.cwd(), value));
}

function protectedReason(value: string): string | null {
	const absolute = absolutePath(value);
	if (absolute.startsWith(externalBookRoot)) return "OneDrive 原始书籍只读";
	if (!absolute.startsWith(`${projectRoot}/`)) return null;
	const relative = absolute.slice(projectRoot.length + 1);
	if (/^tools\/yubook\/workspace\/[^/]+\/source\//.test(relative)) return "YuBook 原始归档只读";
	if (/^tools\/yubook\/workspace\/[^/]+\/dist\//.test(relative)) return "YuBook 不可变候选只能由 build 生成";
	if (/^(content|question-banks|data)\//.test(relative)) return "正式内容与用户数据只能通过受支持的应用流程修改";
	if (/^(\.git|\.env(?:\.|$))/.test(relative)) return "项目控制与密钥文件受保护";
	return null;
}

function commandTouchesProtectedPath(command: string): string | null {
	const normalized = normalizePath(command);
	const supportedYuBookCommand = /yubook\.py\s+(?:init|validate|build|import)\b/.test(normalized);
	if (supportedYuBookCommand) return null;

	const mutates = /\b(?:remove-item|move-item|copy-item|rename-item|set-content|add-content|clear-content|out-file|rm|mv|cp|truncate|tee)\b|(?:^|\s)(?:>|>>)|\.write_(?:text|bytes)\s*\(/i.test(command);
	if (!mutates) return null;

	const markers = [
		"c:/users/yu/onedrive/图片/book/",
		"tools/yubook/workspace/",
		"/source/",
		"/dist/",
		"content/",
		"question-banks/",
		"data/",
	];
	return markers.some((marker) => normalized.includes(marker)) ? "命令试图直接改写受保护的书籍、候选包或用户数据" : null;
}

export default function (pi: ExtensionAPI) {
	pi.on("tool_call", async (event, ctx) => {
		let reason: string | null = null;
		if (event.toolName === "write" || event.toolName === "edit") {
			const target = typeof event.input.path === "string" ? event.input.path : "";
			reason = target ? protectedReason(target) : null;
		} else if (event.toolName === "bash" || event.toolName === "powershell") {
			const command = typeof event.input.command === "string" ? event.input.command : "";
			reason = command ? commandTouchesProtectedPath(command) : null;
		}

		if (!reason) return undefined;
		if (ctx.hasUI) ctx.ui.notify(`YuReader safety: ${reason}`, "warning");
		return { block: true, reason };
	});
}
