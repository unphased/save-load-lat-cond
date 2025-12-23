import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple

import torch

try:
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None


_MEM_QUEUES: Dict[str, List[Tuple[Any, Any, Any, Any]]] = {}
_MEM_LOCKS: Dict[str, threading.Lock] = {}
_MEM_CURSORS: Dict[str, int] = {}
_GLOBAL_LOCK = threading.Lock()


def _sanitize_queue_name(name: str) -> str:
    name = (name or "default").strip()
    if not name:
        return "default"
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name)
    return name[:80] or "default"


def _map_tensors(obj: Any, fn) -> Any:
    if torch.is_tensor(obj):
        return fn(obj)
    if isinstance(obj, dict):
        return {k: _map_tensors(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_map_tensors(v, fn) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_map_tensors(v, fn) for v in obj)
    return obj


def _to_cpu(obj: Any) -> Any:
    return _map_tensors(obj, lambda t: t.detach().to("cpu"))


def _detach(obj: Any) -> Any:
    return _map_tensors(obj, lambda t: t.detach())


def _to_device(obj: Any, device: str) -> Any:
    if device == "cpu":
        return _to_cpu(obj)
    return _map_tensors(obj, lambda t: t.detach().to(device))


def _get_auto_device() -> str:
    try:
        import comfy.model_management  # type: ignore

        return str(comfy.model_management.get_torch_device())
    except Exception:  # pragma: no cover
        return "cpu"


def _get_mem_queue(queue_name: str) -> Tuple[List[Tuple[Any, Any, Any, Any]], threading.Lock]:
    queue_name = _sanitize_queue_name(queue_name)
    with _GLOBAL_LOCK:
        if queue_name not in _MEM_QUEUES:
            _MEM_QUEUES[queue_name] = []
            _MEM_LOCKS[queue_name] = threading.Lock()
            _MEM_CURSORS[queue_name] = 0
        return _MEM_QUEUES[queue_name], _MEM_LOCKS[queue_name]


def _get_disk_dir(queue_name: str) -> str:
    queue_name = _sanitize_queue_name(queue_name)
    base_dir: str
    if folder_paths is not None:
        base_dir = folder_paths.get_output_directory()
    else:  # pragma: no cover
        base_dir = os.path.join(os.getcwd(), "output")

    path = os.path.join(base_dir, "save_load_lat_cond", queue_name)
    os.makedirs(path, exist_ok=True)
    return path


def _disk_item_path(queue_name: str) -> str:
    queue_name = _sanitize_queue_name(queue_name)
    stamp = time.time_ns()
    pid = os.getpid()
    filename = f"{stamp}_{pid}.pt"
    return os.path.join(_get_disk_dir(queue_name), filename)


def _disk_cursor_path(queue_name: str) -> str:
    directory = _get_disk_dir(queue_name)
    return os.path.join(directory, ".cursor")


def _disk_read_cursor(queue_name: str) -> str:
    path = _disk_cursor_path(queue_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _disk_write_cursor(queue_name: str, cursor: str) -> None:
    path = _disk_cursor_path(queue_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(cursor)


def _disk_clear_cursor(queue_name: str) -> None:
    path = _disk_cursor_path(queue_name)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _disk_pop_next(queue_name: str, *, consume: bool, reset_cursor: bool) -> Tuple[str, dict]:
    directory = _get_disk_dir(queue_name)
    if reset_cursor:
        _disk_clear_cursor(queue_name)
    entries = [f for f in os.listdir(directory) if f.endswith(".pt")]
    if not entries:
        raise RuntimeError(f"Queue '{_sanitize_queue_name(queue_name)}' is empty (disk).")
    entries.sort()
    cursor = "" if reset_cursor else _disk_read_cursor(queue_name)
    idx = 0
    if cursor:
        for i, name in enumerate(entries):
            if name == cursor:
                idx = i + 1
                break
            if name > cursor:
                idx = i
                break
        else:
            idx = len(entries)
    if idx >= len(entries):
        raise RuntimeError(f"Queue '{_sanitize_queue_name(queue_name)}' has no more unread items (disk).")

    filename = entries[idx]
    path = os.path.join(directory, filename)
    payload = torch.load(path, map_location="cpu")
    _disk_write_cursor(queue_name, filename)
    if consume:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    return path, payload


def _format_ns_timestamp(ns: int) -> str:
    if not ns:
        return "unknown-time"
    return datetime.fromtimestamp(ns / 1_000_000_000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _disk_next_unread_index(entries: List[str], cursor: str) -> int:
    if not cursor:
        return 0
    for i, name in enumerate(entries):
        if name == cursor:
            return i + 1
        if name > cursor:
            return i
    return len(entries)


def _disk_cursor_to_next_index(entries: List[str], cursor: str) -> int:
    cursor = (cursor or "").strip()
    if cursor.isdigit():
        try:
            return max(0, min(int(cursor), len(entries)))
        except Exception:  # pragma: no cover
            return 0
    return _disk_next_unread_index(entries, cursor)


def _disk_set_cursor_from_next_index(queue_name: str, next_index: int) -> None:
    directory = _get_disk_dir(queue_name)
    entries = [f for f in os.listdir(directory) if f.endswith(".pt")]
    entries.sort()
    next_index = max(0, min(int(next_index), len(entries)))
    if next_index <= 0:
        _disk_clear_cursor(queue_name)
        return
    cursor_filename = entries[next_index - 1]
    _disk_write_cursor(queue_name, cursor_filename)


def _disk_counts(queue_name: str, *, reset_cursor: bool) -> Tuple[int, int]:
    directory = _get_disk_dir(queue_name)
    entries = [f for f in os.listdir(directory) if f.endswith(".pt")]
    entries.sort()
    total = len(entries)
    cursor = "" if reset_cursor else _disk_read_cursor(queue_name)
    idx = 0 if reset_cursor else _disk_cursor_to_next_index(entries, cursor)
    unread = max(0, total - idx)
    return total, unread


def _mem_counts(queue_name: str, *, reset_cursor: bool) -> Tuple[int, int, int]:
    queue_name = _sanitize_queue_name(queue_name)
    q, lock = _get_mem_queue(queue_name)
    with lock:
        if reset_cursor:
            _MEM_CURSORS[queue_name] = 0
        cursor = _MEM_CURSORS.get(queue_name, 0)
        total = len(q)
        unread = max(0, total - cursor)
        return total, cursor, unread


def _disk_list_lines(queue_name: str, *, next_index: int, max_items: int = 200) -> List[str]:
    directory = _get_disk_dir(queue_name)
    entries = [f for f in os.listdir(directory) if f.endswith(".pt")]
    entries.sort()
    if not entries:
        return ["(empty)"]

    next_index = max(0, min(int(next_index), len(entries)))
    lines: List[str] = []
    remaining = entries[next_index:]
    if not remaining:
        return ["(no unread items)"]

    show = remaining[:max_items]
    for i, name in enumerate(show, start=next_index):
        ns = 0
        match = re.match(r"^(\d+)_\d+\.pt$", name)
        if match:
            try:
                ns = int(match.group(1))
            except Exception:  # pragma: no cover
                ns = 0
        if not ns:
            try:
                ns = int(os.path.getmtime(os.path.join(directory, name)) * 1_000_000_000)
            except Exception:  # pragma: no cover
                ns = 0
        lines.append(f"[{i}] {_format_ns_timestamp(ns)}  {name}")
    more = len(remaining) - len(show)
    if more > 0:
        lines.append(f"... and {more} more")
    return lines


def _mem_list_lines(queue_name: str, *, next_index: int, max_items: int = 200) -> List[str]:
    queue_name = _sanitize_queue_name(queue_name)
    q, lock = _get_mem_queue(queue_name)
    with lock:
        if not q:
            return ["(empty)"]
        next_index = max(0, min(int(next_index), len(q)))
        remaining = q[next_index:]
        if not remaining:
            return ["(no unread items)"]
        show = remaining[:max_items]
        lines: List[str] = []
        for i, item in enumerate(show, start=next_index):
            ts_ns = 0
            if isinstance(item, tuple) and len(item) == 4:
                try:
                    ts_ns = int(item[0]) or 0
                except Exception:  # pragma: no cover
                    ts_ns = 0
            lines.append(f"[{i}] {_format_ns_timestamp(ts_ns)}")
        more = len(remaining) - len(show)
        if more > 0:
            lines.append(f"... and {more} more")
        return lines


@dataclass(frozen=True)
class _Triplet:
    latent: Any
    positive: Any
    negative: Any


class SaveLatentCond:
    DESCRIPTION = (
        "Queues a (latent, positive, negative) triplet for later reuse.\n"
        "mode=cpu/gpu keeps items in-process (cpu frees VRAM; gpu keeps on current device).\n"
        "mode=disk writes .pt files under ComfyUI's output directory:\n"
        "  <output>/save_load_lat_cond/<queue_name>/\n"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "mode": (["cpu", "gpu", "disk"], {"default": "cpu"}),
                "queue_name": ("STRING", {"default": "default"}),
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = "save-load-lat-cond"

    def save(self, latent, positive, negative, mode, queue_name):
        queue_name = _sanitize_queue_name(queue_name)

        if mode == "disk":
            path = _disk_item_path(queue_name)
            payload = {
                "latent": _to_cpu(latent),
                "positive": _to_cpu(positive),
                "negative": _to_cpu(negative),
            }
            torch.save(payload, path)
            entries = [f for f in os.listdir(_get_disk_dir(queue_name)) if f.endswith(".pt")]
            entries.sort()
            next_idx = _disk_cursor_to_next_index(entries, _disk_read_cursor(queue_name))
            total = len(entries)
            unread = max(0, total - next_idx)
            header = f"Queue '{queue_name}' (disk): {unread} unread / {total} total (cursor={next_idx})"
            lines = [header, "Unread items:"] + _disk_list_lines(queue_name, next_index=next_idx)
        else:
            store_mode = "cpu" if mode == "cpu" else "keep"
            triplet = _Triplet(
                latent=_to_cpu(latent) if store_mode == "cpu" else _detach(latent),
                positive=_to_cpu(positive) if store_mode == "cpu" else _detach(positive),
                negative=_to_cpu(negative) if store_mode == "cpu" else _detach(negative),
            )
            ts_ns = time.time_ns()
            q, lock = _get_mem_queue(queue_name)
            with lock:
                q.append((ts_ns, triplet.latent, triplet.positive, triplet.negative))
                total = len(q)
                cursor = _MEM_CURSORS.get(queue_name, 0)
                unread = max(0, total - cursor)
            header = f"Queue '{queue_name}' ({mode}): {unread} unread / {total} total (cursor={cursor})"
            lines = [header, "Unread items:"] + _mem_list_lines(queue_name, next_index=cursor)

        return {"ui": {"text": lines}, "result": ()}


class LoadLatentCond:
    DESCRIPTION = (
        "Loads the next queued (latent, positive, negative) triplet.\n"
        "mode=disk reads .pt files from:\n"
        "  <output>/save_load_lat_cond/<queue_name>/\n"
        "When consume=false, a per-queue cursor advances so repeated loads return successive items (cursor stored as .cursor for disk).\n"
        "mode=cpu returns CPU tensors; mode=gpu moves tensors to ComfyUI's active torch device."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["cpu", "gpu", "disk"], {"default": "gpu"}),
                "queue_name": ("STRING", {"default": "default"}),
                "consume": ("BOOLEAN", {"default": True}),
                "reset_cursor": ("BOOLEAN", {"default": False}),
                "cursor": ("INT", {"default": -1, "min": -1, "max": 1_000_000_000}),
            }
        }

    RETURN_TYPES = ("LATENT", "CONDITIONING", "CONDITIONING", "INT")
    RETURN_NAMES = ("latent", "positive", "negative", "cursor")
    FUNCTION = "load"
    CATEGORY = "save-load-lat-cond"

    @classmethod
    def IS_CHANGED(cls, mode, queue_name, consume, reset_cursor, cursor):
        queue_name = _sanitize_queue_name(queue_name)
        if mode == "disk":
            directory = _get_disk_dir(queue_name)
            try:
                entries = [f for f in os.listdir(directory) if f.endswith(".pt")]
            except FileNotFoundError:
                entries = []
            entries.sort()
            cursor = str(cursor) if int(cursor) >= 0 else ("" if reset_cursor else _disk_read_cursor(queue_name))
            last = entries[-1] if entries else ""
            return f"{mode}:{queue_name}:{len(entries)}:{last}:{cursor}:{consume}:{reset_cursor}"

        q, lock = _get_mem_queue(queue_name)
        with lock:
            total = len(q)
            cursor_val = int(cursor) if int(cursor) >= 0 else _MEM_CURSORS.get(queue_name, 0)
        return f"{mode}:{queue_name}:{total}:{cursor_val}:{consume}:{reset_cursor}"

    def load(self, mode, queue_name, consume, reset_cursor, cursor):
        queue_name = _sanitize_queue_name(queue_name)
        device = "cpu" if mode == "cpu" else _get_auto_device()
        cursor = int(cursor)

        if mode == "disk":
            directory = _get_disk_dir(queue_name)
            entries = [f for f in os.listdir(directory) if f.endswith(".pt")]
            entries.sort()
            effective_reset_cursor = bool(reset_cursor) and cursor < 0
            next_idx = 0 if effective_reset_cursor else _disk_cursor_to_next_index(entries, _disk_read_cursor(queue_name))
            if cursor >= 0:
                next_idx = max(0, min(cursor, len(entries)))
                _disk_set_cursor_from_next_index(queue_name, next_idx)

            before_total = len(entries)
            before_unread = max(0, before_total - next_idx)
            _, payload = _disk_pop_next(queue_name, consume=consume, reset_cursor=effective_reset_cursor)
            latent = payload["latent"]
            positive = payload["positive"]
            negative = payload["negative"]
            entries_after = [f for f in os.listdir(directory) if f.endswith(".pt")]
            entries_after.sort()
            after_total = len(entries_after)
            after_next_idx = _disk_cursor_to_next_index(entries_after, _disk_read_cursor(queue_name))
            after_unread = max(0, after_total - after_next_idx)
            after_cursor = after_next_idx
            list_lines = _disk_list_lines(queue_name, next_index=after_next_idx)
        else:
            q, lock = _get_mem_queue(queue_name)
            with lock:
                if reset_cursor:
                    _MEM_CURSORS[queue_name] = 0
                if cursor >= 0:
                    _MEM_CURSORS[queue_name] = max(0, cursor)
                cursor_val = _MEM_CURSORS.get(queue_name, 0)
                before_total = len(q)
                before_unread = max(0, before_total - cursor_val)
                if not q:
                    raise RuntimeError(f"Queue '{queue_name}' is empty (memory).")
                if cursor_val >= len(q):
                    raise RuntimeError(f"Queue '{queue_name}' has no more unread items (memory).")
                item = q[cursor_val]
                if isinstance(item, tuple) and len(item) == 4:
                    _, latent, positive, negative = item
                else:  # backward compat for older in-memory entries
                    latent, positive, negative = item
                if consume:
                    q.pop(cursor_val)
                else:
                    _MEM_CURSORS[queue_name] = cursor_val + 1
                after_total = len(q)
                after_cursor = _MEM_CURSORS.get(queue_name, cursor_val)
                after_unread = max(0, after_total - after_cursor)
                list_lines = _mem_list_lines(queue_name, next_index=after_cursor)

        header = (
            f"Queue '{queue_name}' ({mode}): {before_unread}→{after_unread} unread / "
            f"{before_total}→{after_total} total (cursor={after_cursor})"
        )

        return {
            "ui": {"text": [header, "Unread items:"] + list_lines},
            "result": (
                _to_device(latent, device),
                _to_device(positive, device),
                _to_device(negative, device),
                int(after_cursor),
            ),
        }
