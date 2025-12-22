import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional, Tuple

import torch

try:
    import folder_paths
except Exception:  # pragma: no cover
    folder_paths = None


_MEM_QUEUES: Dict[str, Deque[Tuple[Any, Any, Any]]] = {}
_MEM_LOCKS: Dict[str, threading.Lock] = {}
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


def _get_mem_queue(queue_name: str) -> Tuple[Deque[Tuple[Any, Any, Any]], threading.Lock]:
    queue_name = _sanitize_queue_name(queue_name)
    with _GLOBAL_LOCK:
        if queue_name not in _MEM_QUEUES:
            _MEM_QUEUES[queue_name] = deque()
            _MEM_LOCKS[queue_name] = threading.Lock()
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


def _disk_pop_oldest(queue_name: str, *, consume: bool) -> Tuple[str, dict]:
    directory = _get_disk_dir(queue_name)
    entries = [f for f in os.listdir(directory) if f.endswith(".pt")]
    if not entries:
        raise RuntimeError(f"Queue '{_sanitize_queue_name(queue_name)}' is empty (disk).")
    entries.sort()
    path = os.path.join(directory, entries[0])
    payload = torch.load(path, map_location="cpu")
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
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT",),
                "positive": ("CONDITIONING",),
                "negative": ("CONDITIONING",),
                "storage": (["memory", "disk"], {"default": "memory"}),
                "queue_name": ("STRING", {"default": "default"}),
                "store_device": (["cpu", "keep"], {"default": "cpu"}),
            }
        }

    RETURN_TYPES = ("LATENT", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("latent", "positive", "negative")
    FUNCTION = "save"
    CATEGORY = "save-load-lat-cond"

    def save(self, latent, positive, negative, storage, queue_name, store_device):
        queue_name = _sanitize_queue_name(queue_name)

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
                latent=_to_cpu(latent) if store_device == "cpu" else latent,
                positive=_to_cpu(positive) if store_device == "cpu" else positive,
                negative=_to_cpu(negative) if store_device == "cpu" else negative,
            )
            q, lock = _get_mem_queue(queue_name)
            with lock:
                q.append((triplet.latent, triplet.positive, triplet.negative))

        return (latent, positive, negative)


class LoadLatentCond:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "storage": (["memory", "disk"], {"default": "memory"}),
                "queue_name": ("STRING", {"default": "default"}),
                "consume": ("BOOLEAN", {"default": True}),
                "load_device": (["auto", "cpu"], {"default": "auto"}),
            }
        }

    RETURN_TYPES = ("LATENT", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("latent", "positive", "negative")
    FUNCTION = "load"
    CATEGORY = "save-load-lat-cond"

    def load(self, storage, queue_name, consume, load_device):
        queue_name = _sanitize_queue_name(queue_name)
        device = _get_auto_device() if load_device == "auto" else "cpu"

        if storage == "disk":
            _, payload = _disk_pop_oldest(queue_name, consume=consume)
            latent = payload["latent"]
            positive = payload["positive"]
            negative = payload["negative"]
        else:
            q, lock = _get_mem_queue(queue_name)
            with lock:
                if not q:
                    raise RuntimeError(f"Queue '{queue_name}' is empty (memory).")
                if consume:
                    latent, positive, negative = q.popleft()
                else:
                    latent, positive, negative = q[0]

        return (_to_device(latent, device), _to_device(positive, device), _to_device(negative, device))

