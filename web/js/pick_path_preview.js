import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

if (globalThis.__saveLoadLatCondPickPathPreviewLoaded) {
  // avoid double-registering if ComfyUI loads both root + /js scripts
} else {
  globalThis.__saveLoadLatCondPickPathPreviewLoaded = true;

function coerceLines(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.join("\n");
  return String(value);
}

function attachPreviewWidget(node) {
  if (node.__saveLoadLatCondPickPathPreviewAttached) return;
  node.__saveLoadLatCondPickPathPreviewAttached = true;

  node.__saveLoadLatCondPickPathPreviewLines = [];
}

function setPreviewLines(node, value) {
  const text = coerceLines(value);
  node.__saveLoadLatCondPickPathPreviewLines = text ? text.split("\n") : [];
  app.canvas?.setDirty(true, true);
}

function truncateToWidth(ctx, text, maxWidth) {
  if (ctx.measureText(text).width <= maxWidth) return text;
  const ellipsis = "…";
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    const candidate = text.slice(0, mid) + ellipsis;
    if (ctx.measureText(candidate).width <= maxWidth) lo = mid + 1;
    else hi = mid;
  }
  return text.slice(0, Math.max(0, lo - 1)) + ellipsis;
}

function wrapToWidth(ctx, text, maxWidth) {
  if (!text) return [""];
  if (ctx.measureText(text).width <= maxWidth) return [text];
  const out = [];
  let start = 0;
  while (start < text.length) {
    let lo = start + 1;
    let hi = text.length;
    while (lo < hi) {
      const mid = Math.floor((lo + hi) / 2);
      const slice = text.slice(start, mid);
      if (ctx.measureText(slice).width <= maxWidth) lo = mid + 1;
      else hi = mid;
    }
    const end = Math.max(start + 1, lo - 1);
    out.push(text.slice(start, end));
    start = end;
  }
  return out;
}

function widgetsEndY(node) {
  const widgets = node.widgets ?? [];
  const titleHeight = globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
  const widgetHeight = globalThis.LiteGraph?.NODE_WIDGET_HEIGHT ?? 20;
  const startY = typeof node.widgets_start_y === "number" ? node.widgets_start_y : titleHeight + 10;

  let endY = startY;
  const width = (node.size?.[0] ?? 320) - 20;

  for (let i = 0; i < widgets.length; i++) {
    const w = widgets[i] ?? {};
    const wy =
      typeof w.y === "number"
        ? w.y
        : typeof w.last_y === "number"
          ? w.last_y
          : startY + i * widgetHeight;

    let wh = 0;
    if (typeof w.computeSize === "function") {
      try {
        const size = w.computeSize(width);
        wh = Array.isArray(size) ? Number(size[1] ?? 0) : 0;
      } catch {
        wh = 0;
      }
    }
    if (!wh) wh = Number(w.options?.height ?? w.height ?? w.h ?? widgetHeight) || widgetHeight;

    endY = Math.max(endY, wy + wh);
  }

  return endY;
}

function drawPreviewBox(node, ctx) {
  const lines = node.__saveLoadLatCondPickPathPreviewLines ?? [];
  const pad = 10;
  const x = pad;
  const w = (node.size?.[0] ?? 0) - pad * 2;
  const widgetsEnd = widgetsEndY(node);
  const y = Math.max(widgetsEnd + pad, pad);
  const h = (node.size?.[1] ?? 0) - y - pad;
  if (w <= 40 || h <= 70) return;

  ctx.save();
  ctx.fillStyle = "rgba(10, 10, 10, 0.35)";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect?.(x, y, w, h, 6);
  if (!ctx.roundRect) ctx.rect(x, y, w, h);
  ctx.fill();
  ctx.stroke();

  ctx.beginPath();
  ctx.rect(x + 6, y + 6, w - 12, h - 12);
  ctx.clip();

  const title = "Selection preview";
  ctx.fillStyle = "rgba(255,255,255,0.75)";
  ctx.font = "12px sans-serif";
  ctx.fillText(title, x + 10, y + 18);

  ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
  const lineHeight = 14;
  const contentTop = y + 34;
  const maxLines = Math.max(1, Math.floor((h - 40) / lineHeight));
  const visible = [];
  const maxWidth = w - 20;
  for (const raw of lines) {
    if (visible.length >= maxLines) break;
    // Wrap only the header-ish lines; keep the indexed list rows single-line/truncated.
    if (raw.startsWith(" ") || raw.startsWith(">") || raw.startsWith("entries") || raw.startsWith("...")) {
      visible.push(truncateToWidth(ctx, raw, maxWidth));
      continue;
    }
    const wrapped = wrapToWidth(ctx, raw, maxWidth);
    for (const piece of wrapped) {
      if (visible.length >= maxLines) break;
      visible.push(piece);
    }
  }

  for (let i = 0; i < visible.length; i++) {
    const raw = visible[i] ?? "";
    const isSelected = raw.startsWith(">");
    const text = raw;
    ctx.fillStyle = isSelected ? "rgba(255,255,255,0.92)" : "rgba(220,220,220,0.72)";
    ctx.fillText(text, x + 10, contentTop + i * lineHeight);
  }

  if (lines.length > maxLines) {
    ctx.fillStyle = "rgba(255,255,255,0.5)";
    ctx.font = "11px sans-serif";
    ctx.fillText(`… more (raise node height or lower max_list_items)`, x + 10, y + h - 10);
  }

  ctx.restore();
}

function getWidgetValue(node, name, fallback) {
  const w = node.widgets?.find((x) => x?.name === name);
  if (!w) return fallback;
  return w.value ?? fallback;
}

function buildPayload(node) {
  return {
    root_dir: String(getWidgetValue(node, "root_dir", "")),
    kind: String(getWidgetValue(node, "kind", "dirs")),
    index: Number(getWidgetValue(node, "index", 0)),
    sort: String(getWidgetValue(node, "sort", "natural")),
    on_out_of_range: String(getWidgetValue(node, "on_out_of_range", "wrap")),
    include_regex: String(getWidgetValue(node, "include_regex", "")),
    exclude_regex: String(getWidgetValue(node, "exclude_regex", "")),
    extensions: String(getWidgetValue(node, "extensions", "")),
    max_list_items: Number(getWidgetValue(node, "max_list_items", 200)),
  };
}

async function fetchPreview(node) {
  const payload = buildPayload(node);
  if (!payload.root_dir) {
    setPreviewLines(node, "Set root_dir to preview selection.");
    return;
  }

  try {
    const resp = await api.fetchApi("/save_load_lat_cond/pick_path_preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const json = await resp.json();
    if (!json?.ok) {
      setPreviewLines(node, json?.error ?? "Preview failed.");
      return;
    }
    setPreviewLines(node, json.lines);
  } catch (e) {
    setPreviewLines(node, String(e));
  }
}

function schedulePreview(node) {
  if (!node) return;
  if (node.__saveLoadLatCondPickPathPreviewTimer) {
    clearTimeout(node.__saveLoadLatCondPickPathPreviewTimer);
  }
  node.__saveLoadLatCondPickPathPreviewTimer = setTimeout(() => {
    fetchPreview(node);
  }, 150);
}

function hookWidgetCallbacks(node) {
  const names = new Set([
    "root_dir",
    "kind",
    "index",
    "sort",
    "on_out_of_range",
    "include_regex",
    "exclude_regex",
    "extensions",
    "max_list_items",
  ]);

  for (const w of node.widgets ?? []) {
    if (!w?.name || !names.has(w.name)) continue;
    if (w.__saveLoadLatCondPickPathPreviewHooked) continue;
    w.__saveLoadLatCondPickPathPreviewHooked = true;

    const orig = w.callback;
    w.callback = function () {
      orig?.apply(this, arguments);
      schedulePreview(node);
    };
  }
}

app.registerExtension({
  name: "save-load-lat-cond.pick_path_preview",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== "PickPathByIndex") return;

    const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function onNodeCreated() {
      originalOnNodeCreated?.apply(this, arguments);
      attachPreviewWidget(this);
      hookWidgetCallbacks(this);
      schedulePreview(this);
    };

    const originalOnDrawForeground = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function onDrawForeground(ctx) {
      originalOnDrawForeground?.apply(this, arguments);
      drawPreviewBox(this, ctx);
    };

    const originalOnExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function onExecuted(message) {
      originalOnExecuted?.apply(this, arguments);
      attachPreviewWidget(this);
      hookWidgetCallbacks(this);
      setPreviewLines(this, message?.ui?.text ?? "");
    };
  },
});

}
