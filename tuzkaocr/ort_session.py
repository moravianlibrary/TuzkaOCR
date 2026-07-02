"""Central ONNX Runtime CUDA provider construction.

On CUDA the ORT defaults grow GPU memory without bound as input shapes vary — and the OCR
pipeline feeds a different page size almost every time:
  - ``cudnn_conv_algo_search=EXHAUSTIVE`` (ORT default) benchmarks conv algorithms per unique
    spatial shape and caches a workspace for each → the working set ratchets up per new size;
  - ``arena_extend_strategy=kNextPowerOfTwo`` (default) over-reserves and never releases.
Across a varied corpus this climbs to the VRAM ceiling and OOMs (see bench/GPU_MEMORY.md).

``HEURISTIC`` + ``kSameAsRequested`` (and optionally a hard ``gpu_mem_limit``) bound it. The
values come from Config (env-overridable via TUZKAOCR_*), so the old behavior stays reproducible.
"""

from __future__ import annotations


def build_providers(device: str, cuda_opts: dict | None = None) -> list:
    """Provider list for an InferenceSession. On CUDA, attach the memory-bounding options."""
    if device != "cuda":
        return ["CPUExecutionProvider"]
    return [("CUDAExecutionProvider", cuda_opts or {}), "CPUExecutionProvider"]
