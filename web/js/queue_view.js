import { app } from "../../../scripts/app.js";

if (globalThis.__saveLoadLatCondQueueViewLoaded) {
  // avoid double-registering if ComfyUI loads both root + /js scripts
} else {
  globalThis.__saveLoadLatCondQueueViewLoaded = true;

function coerceLines(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.join("\n");
  return String(value);
}

function attachQueueWidget(node) {
  if (node.__saveLoadLatCondQueueWidgetAttached) return;
  node.__saveLoadLatCondQueueWidgetAttached = true;
  node.__saveLoadLatCondQueueLines = [];
}

function updateQueueWidget(node, message) {
  const ui = message?.ui ?? {};
  const text = coerceLines(ui.queue_lines ?? ui.text ?? ui.queue ?? "");
  node.__saveLoadLatCondQueueLines = text ? text.split("\n") : [];
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

function drawQueueBox(node, ctx) {
  const lines = node.__saveLoadLatCondQueueLines ?? [];
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

  ctx.fillStyle = "rgba(255,255,255,0.75)";
  ctx.font = "12px sans-serif";
  ctx.fillText("Queue", x + 10, y + 18);

  ctx.font = "12px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace";
  const lineHeight = 14;
  const contentTop = y + 34;
  const maxLines = Math.max(1, Math.floor((h - 40) / lineHeight));
  const visible = lines.slice(0, maxLines);

  for (let i = 0; i < visible.length; i++) {
    const raw = visible[i] ?? "";
    const text = truncateToWidth(ctx, raw, w - 20);
    ctx.fillStyle = "rgba(220,220,220,0.72)";
    ctx.fillText(text, x + 10, contentTop + i * lineHeight);
  }

  if (lines.length > maxLines) {
    ctx.fillStyle = "rgba(255,255,255,0.5)";
    ctx.font = "11px sans-serif";
    ctx.fillText(`… ${lines.length - maxLines} more (raise node height)`, x + 10, y + h - 10);
  }

  ctx.restore();
}

app.registerExtension({
  name: "save-load-lat-cond.queue_view",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== "SaveLatentCond" && nodeData?.name !== "LoadLatentCond") return;

    const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function onNodeCreated() {
      originalOnNodeCreated?.apply(this, arguments);
      attachQueueWidget(this);
    };

    const originalOnDrawForeground = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function onDrawForeground(ctx) {
      originalOnDrawForeground?.apply(this, arguments);
      drawQueueBox(this, ctx);
    };

    const originalOnExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function onExecuted(message) {
      originalOnExecuted?.apply(this, arguments);
      attachQueueWidget(this);
      updateQueueWidget(this, message);
    };
  },
});

}
