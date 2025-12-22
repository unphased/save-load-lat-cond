import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import torch

try:
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None


_MEM_QUEUES: Dict[str, List[Tuple[Any, Any, Any]]] = {}
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


def _get_mem_queue(queue_name: str) -> Tuple[List[Tuple[Any, Any, Any]], threading.Lock]:
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


@dataclass(frozen=True)
class _Triplet:
    latent: Any
    positive: Any
    negative: Any


class SaveLatentCond:
    DESCRIPTION = (
        "Queues a (latent, positive, negative) triplet for later reuse.\n"
        "storage=memory keeps items in-process; storage=disk writes .pt files under ComfyUI's output directory:\n"
        "  <output>/save_load_lat_cond/<queue_name>/\n"
        "store_device (memory only): cpu moves tensors to CPU to free VRAM; keep leaves them on their current device."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "storage": (["memory", "disk"], {"default": "memory"}),
                "queue_name": ("STRING", {"default": "default"}),
                "store_device": (
                    ["cpu (free VRAM)", "keep (as-is)", "cpu", "keep"],
                    {"default": "cpu (free VRAM)"},
                ),
            }
        }

    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = "save-load-lat-cond"

    def save(self, latent, positive, negative, storage, queue_name, store_device):
        queue_name = _sanitize_queue_name(queue_name)
        store_mode = "cpu" if str(store_device).startswith("cpu") else "keep"

        if storage == "disk":
            path = _disk_item_path(queue_name)
            payload = {
                "latent": _to_cpu(latent),
                "positive": _to_cpu(positive),
                "negative": _to_cpu(negative),
            }
            torch.save(payload, path)
        else:
            triplet = _Triplet(
                latent=_to_cpu(latent) if store_mode == "cpu" else _detach(latent),
                positive=_to_cpu(positive) if store_mode == "cpu" else _detach(positive),
                negative=_to_cpu(negative) if store_mode == "cpu" else _detach(negative),
            )
            q, lock = _get_mem_queue(queue_name)
            with lock:
                q.append((triplet.latent, triplet.positive, triplet.negative))

        return ()


class LoadLatentCond:
    DESCRIPTION = (
        "Loads the next queued (latent, positive, negative) triplet.\n"
        "storage=disk reads .pt files from:\n"
        "  <output>/save_load_lat_cond/<queue_name>/\n"
        "When consume=false, a per-queue cursor advances so repeated loads return successive items (cursor stored as .cursor for disk)."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "storage": (["memory", "disk"], {"default": "memory"}),
                "queue_name": ("STRING", {"default": "default"}),
                "consume": ("BOOLEAN", {"default": True}),
                "reset_cursor": ("BOOLEAN", {"default": False}),
                "load_device": (["auto (comfy device)", "cpu", "auto"], {"default": "auto (comfy device)"}),
            }
        }

    RETURN_TYPES = ("LATENT", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("latent", "positive", "negative")
    FUNCTION = "load"
    CATEGORY = "save-load-lat-cond"

    def load(self, storage, queue_name, consume, reset_cursor, load_device):
        queue_name = _sanitize_queue_name(queue_name)
        load_mode = "auto" if str(load_device).startswith("auto") else "cpu"
        device = _get_auto_device() if load_mode == "auto" else "cpu"

        if storage == "disk":
            _, payload = _disk_pop_next(queue_name, consume=consume, reset_cursor=reset_cursor)
            latent = payload["latent"]
            positive = payload["positive"]
            negative = payload["negative"]
        else:
            q, lock = _get_mem_queue(queue_name)
            with lock:
                if reset_cursor:
                    _MEM_CURSORS[queue_name] = 0
                cursor = _MEM_CURSORS.get(queue_name, 0)
                if not q:
                    raise RuntimeError(f"Queue '{queue_name}' is empty (memory).")
                if cursor >= len(q):
                    raise RuntimeError(f"Queue '{queue_name}' has no more unread items (memory).")
                latent, positive, negative = q[cursor]
                if consume:
                    q.pop(cursor)
                else:
                    _MEM_CURSORS[queue_name] = cursor + 1

        return (_to_device(latent, device), _to_device(positive, device), _to_device(negative, device))
