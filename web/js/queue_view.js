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

  const widgetHeight = 190;
  const widget = node.addWidget("text", "Queue", "", () => {}, { multiline: true });
  widget.options = widget.options || {};
  widget.options.multiline = true;
  widget.options.height = widgetHeight;
  widget.options.serialize = false;
  widget.computeSize = (width) => [width, widgetHeight];

  node.__saveLoadLatCondQueueWidget = widget;

  const height = Math.max(node.size?.[1] ?? 0, 140 + widgetHeight);
  node.setSize([node.size?.[0] ?? 320, height]);
}

function updateQueueWidget(node, message) {
  const widget = node.__saveLoadLatCondQueueWidget;
  if (!widget) return;

  const ui = message?.ui ?? {};
  const text = coerceLines(ui.queue_lines ?? ui.text ?? ui.queue ?? "");
  if (text) widget.value = text;
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

    const originalOnExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function onExecuted(message) {
      originalOnExecuted?.apply(this, arguments);
      attachQueueWidget(this);
      updateQueueWidget(this, message);
    };
  },
});

}
