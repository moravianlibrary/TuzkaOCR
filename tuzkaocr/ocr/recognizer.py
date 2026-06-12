from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple

import numpy as np
import onnxruntime as ort

from .vocab import load_vocab

WordSpan = Tuple[str, int, int]
LineResult = Tuple[str, List[WordSpan], float]


def _greedy_ctc(logits: np.ndarray, chars: List[str]) -> LineResult:
    best = logits.argmax(axis=-1)

    m = logits.max(axis=-1, keepdims=True)
    probs = np.exp(logits - m)
    probs /= probs.sum(axis=-1, keepdims=True)
    pmax = probs.max(axis=-1)

    char_events: List[Tuple[str, int]] = []
    confs: List[float] = []
    prev = 0
    for t, idx in enumerate(best):
        if idx != 0 and idx != prev:
            char_events.append((chars[idx - 1], t))
            confs.append(float(pmax[t]))
        prev = idx

    transcription = "".join(c for c, _ in char_events)
    confidence = float(np.mean(confs)) if confs else 0.0

    word_spans: List[WordSpan] = []
    word_chars: List[str] = []
    word_t_start: int | None = None

    for char, t in char_events:
        if char == ' ':
            if word_chars:
                word_spans.append(("".join(word_chars), word_t_start, t - 1))
                word_chars = []
                word_t_start = None
        else:
            if word_t_start is None:
                word_t_start = t
            word_chars.append(char)

    if word_chars:
        word_spans.append(("".join(word_chars), word_t_start, t))

    return transcription, word_spans, confidence


class OnnxRecognizer:
    def __init__(self, model_path: str | Path, vocab_path: str | Path | None = None,
                 device: str = "cpu", threads: int = 4, max_width: int = 1600,
                 cpu_mem_arena: bool = True):
        self.chars, _ = load_vocab(vocab_path)
        self.max_width = max_width

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = max(1, threads // 2)
        opts.enable_cpu_mem_arena = cpu_mem_arena

        if device == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        self.session = ort.InferenceSession(
            str(model_path), sess_options=opts, providers=providers
        )
        self._input_name = self.session.get_inputs()[0].name

    def run_line(self, crop_gray: np.ndarray) -> LineResult:
        w = min(crop_gray.shape[1], self.max_width)
        crop = crop_gray[:, :w]
        x = crop.astype(np.float32)[None, None] / 255.0
        logits = self.session.run(None, {self._input_name: x})[0][0]
        return _greedy_ctc(logits, self.chars)

    def run_lines(self, crops: List[np.ndarray],
                  workers: int = 4) -> List[LineResult]:
        if not crops:
            return []
        if workers <= 1 or len(crops) == 1:
            return [self.run_line(c) for c in crops]

        results = [None] * len(crops)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.run_line, c): i for i, c in enumerate(crops)}
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return results
