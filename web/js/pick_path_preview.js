import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

function coerceLines(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.join("\n");
  return String(value);
}

function attachPreviewWidget(node) {
  if (node.__saveLoadLatCondPickPathPreviewAttached) return;
  node.__saveLoadLatCondPickPathPreviewAttached = true;

  const widget = node.addWidget("text", "Selection", "", null, { multiline: true });
  widget.options = widget.options || {};
  widget.options.multiline = true;
  widget.options.serialize = false;
  node.__saveLoadLatCondPickPathPreviewWidget = widget;

  const height = Math.max(node.size?.[1] ?? 0, 260);
  node.setSize([node.size?.[0] ?? 340, height]);
}

function updatePreviewWidget(node, value) {
  const widget = node.__saveLoadLatCondPickPathPreviewWidget;
  if (!widget) return;
  widget.value = coerceLines(value);
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
    updatePreviewWidget(node, "Set root_dir to preview selection.");
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
      updatePreviewWidget(node, json?.error ?? "Preview failed.");
      return;
    }
    updatePreviewWidget(node, json.lines);
  } catch (e) {
    updatePreviewWidget(node, String(e));
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

    const originalOnExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function onExecuted(message) {
      originalOnExecuted?.apply(this, arguments);
      attachPreviewWidget(this);
      hookWidgetCallbacks(this);
      updatePreviewWidget(this, message?.ui?.text ?? "");
    };
  },
});
