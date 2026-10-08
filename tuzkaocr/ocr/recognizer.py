from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, NamedTuple, Tuple

import numpy as np
import onnxruntime as ort

from .vocab import load_vocab


class WordSpan(NamedTuple):
    text: str
    t_start: int
    t_end: int
    char_ts: Tuple[int, ...] = ()
    char_conf: Tuple[float, ...] = ()


class LineResult(NamedTuple):
    text: str
    words: List[WordSpan]
    confidence: float


def _greedy_ctc(logits: np.ndarray, chars: List[str]) -> LineResult:
    best = logits.argmax(axis=-1)

    m = logits.max(axis=-1, keepdims=True)
    probs = np.exp(logits - m)
    probs /= probs.sum(axis=-1, keepdims=True)
    pmax = probs.max(axis=-1)

    events: List[Tuple[str, int, float]] = []
    prev = 0
    for t, idx in enumerate(best):
        if idx != 0 and idx != prev:
            events.append((chars[idx - 1], t, float(pmax[t])))
        prev = idx

    transcription = "".join(char for char, _, _ in events)
    confidence = float(np.mean([p for _, _, p in events])) if events else 0.0

    word_spans: List[WordSpan] = []
    word_chars: List[str] = []
    word_ts: List[int] = []
    word_ps: List[float] = []
    word_t_start: int | None = None

    for char, t, p in events:
        if char == ' ':
            if word_chars:
                word_spans.append(WordSpan("".join(word_chars), word_t_start, t - 1,
                                           tuple(word_ts), tuple(word_ps)))
                word_chars = []
                word_ts = []
                word_ps = []
                word_t_start = None
        else:
            if word_t_start is None:
                word_t_start = t
            word_chars.append(char)
            word_ts.append(t)
            word_ps.append(p)

    if word_chars:
        word_spans.append(WordSpan("".join(word_chars), word_t_start, word_ts[-1],
                                   tuple(word_ts), tuple(word_ps)))

    return LineResult(transcription, word_spans, confidence)


def _session_options(threads: int, cpu_mem_arena: bool) -> ort.SessionOptions:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = max(1, threads // 2)
    opts.enable_cpu_mem_arena = cpu_mem_arena
    return opts


def _providers(device: str) -> list[str]:
    if device == "cuda":
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


class OnnxRecognizer:
    def __init__(self, model_path: str | Path, vocab_path: str | Path | None = None,
                 device: str = "cpu", threads: int = 4, max_width: int = 1600,
                 cpu_mem_arena: bool = True):
        self.chars, _ = load_vocab(vocab_path)
        self.max_width = max_width

        self.session = ort.InferenceSession(
            str(model_path), sess_options=_session_options(threads, cpu_mem_arena),
            providers=_providers(device)
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


def _style_model_path(model_path: str | Path) -> Path:
    path = Path(model_path)
    for suffix in (".int8.onnx", ".fp32.onnx", ".onnx"):
        if path.name.endswith(suffix):
            return path.with_name(path.name[:-len(suffix)] + ".style" + suffix)
    return path.with_name(path.name + ".style.onnx")


def _require_style_model(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(
            f"Page-style recognizer requires style model {path}; the recognition and style "
            "files must ship together."
        )


class PageStyleRecognizer(OnnxRecognizer):
    def __init__(self, model_path: str | Path, vocab_path: str | Path | None = None,
                 device: str = "cpu", threads: int = 4, max_width: int = 1600,
                 cpu_mem_arena: bool = True, style_path: str | Path | None = None):
        super().__init__(model_path, vocab_path, device, threads, max_width, cpu_mem_arena)
        self._initialize_style_model(
            model_path, vocab_path, device, threads, cpu_mem_arena, style_path
        )

    def _initialize_style_model(self, model_path: str | Path,
                                vocab_path: str | Path | None,
                                device: str, threads: int, cpu_mem_arena: bool,
                                style_path: str | Path | None) -> None:
        resolved_style_path = (Path(style_path) if style_path is not None
                               else _style_model_path(model_path))
        _require_style_model(resolved_style_path)
        self.style_session = ort.InferenceSession(
            str(resolved_style_path),
            sess_options=_session_options(threads, cpu_mem_arena),
            providers=_providers(device),
        )
        style_shape = self.style_session.get_outputs()[0].shape
        style_dim = style_shape[-1] if style_shape else None
        if not isinstance(style_dim, (int, np.integer)) or style_dim <= 0:
            raise ValueError(f"Style model {resolved_style_path} has no static style dimension")
        self.style_dim = int(style_dim)
        self._validate_class_count(model_path, vocab_path)

    def _validate_class_count(self, model_path: str | Path,
                              vocab_path: str | Path | None) -> None:
        output_shape = self.session.get_outputs()[0].shape
        class_dim = output_shape[-1] if output_shape else None
        if not isinstance(class_dim, (int, np.integer)):
            input_names = {item.name for item in self.session.get_inputs()}
            if not {"image", "style", "has_style"}.issubset(input_names):
                raise ValueError(
                    f"Cannot validate output classes for model {model_path}: expected page-style "
                    "inputs image, style, and has_style."
                )
            image = np.zeros((1, 1, 40, 32), dtype=np.float32)
            style = np.zeros((1, self.style_dim), dtype=np.float32)
            has_style = np.zeros((1,), dtype=np.float32)
            output = self.session.run(None, {
                "image": image,
                "style": style,
                "has_style": has_style,
            })[0]
            class_dim = output.shape[-1]
        if int(class_dim) != len(self.chars) + 1:
            vocab_name = str(vocab_path) if vocab_path is not None else "vocab.json"
            raise ValueError(
                f"Model {model_path} has {int(class_dim)} output classes, but vocabulary "
                f"{vocab_name} has {len(self.chars)} characters and requires "
                f"{len(self.chars) + 1} classes including CTC blank."
            )

    @classmethod
    def _from_recognizer(cls, recognizer: OnnxRecognizer,
                         model_path: str | Path,
                         vocab_path: str | Path | None,
                         device: str, threads: int, cpu_mem_arena: bool,
                         style_path: str | Path | None = None) -> PageStyleRecognizer:
        instance = cls.__new__(cls)
        instance.__dict__.update(recognizer.__dict__)
        instance._initialize_style_model(
            model_path, vocab_path, device, threads, cpu_mem_arena, style_path
        )
        return instance

    def _prepare_crop(self, crop: np.ndarray) -> np.ndarray:
        if crop.ndim != 2 or crop.shape[0] != 40 or crop.shape[1] < 1:
            raise ValueError(f"production line crop must have shape (40, W), got {crop.shape}")
        return crop[:, :self.max_width]

    def _run_lines(self, crops: list[np.ndarray], run_one, workers: int):
        if workers <= 1 or len(crops) <= 1:
            return [run_one(crop) for crop in crops]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(run_one, crops))

    def run_lines(self, crops: List[np.ndarray],
                  workers: int = 4) -> List[LineResult]:
        if not crops:
            return []
        grays = [self._prepare_crop(crop) for crop in crops]
        if len(grays) >= 2:
            def run_style(gray: np.ndarray) -> np.ndarray:
                width = gray.shape[1]
                image = gray.astype(np.float32)[None, None] / 255.0
                lengths = np.asarray([(width + 1) // 2], dtype=np.int64)
                return self.style_session.run(None, {
                    "image": image,
                    "lengths": lengths,
                })[0]

            per_line_styles = self._run_lines(grays, run_style, workers)
            style_order = sorted(range(len(grays)), key=lambda index: grays[index].shape[1])
            page_style = np.concatenate(
                [per_line_styles[index] for index in style_order], axis=0
            ).mean(axis=0).astype(np.float32)
            has_style = 1.0
        else:
            page_style = np.zeros(self.style_dim, dtype=np.float32)
            has_style = 0.0

        def run_recognizer(gray: np.ndarray) -> LineResult:
            width = gray.shape[1]
            image = gray.astype(np.float32)[None, None] / 255.0
            logits = self.session.run(None, {
                "image": image,
                "style": page_style[None, :],
                "has_style": np.asarray([has_style], dtype=np.float32),
            })[0][0]
            length = min((width + 1) // 2, logits.shape[0])
            return _greedy_ctc(logits[:length], self.chars)

        return self._run_lines(grays, run_recognizer, workers)

    def run_line(self, crop: np.ndarray) -> LineResult:
        return self.run_lines([crop], workers=1)[0]


def create_recognizer(model_path: str | Path, vocab_path: str | Path | None = None,
                      device: str = "cpu", threads: int = 4, max_width: int = 1600,
                      cpu_mem_arena: bool = True) -> OnnxRecognizer:
    recognizer = OnnxRecognizer(
        model_path, vocab_path, device, threads, max_width, cpu_mem_arena
    )
    input_names = {item.name for item in recognizer.session.get_inputs()}
    if {"style", "has_style"}.issubset(input_names):
        return PageStyleRecognizer._from_recognizer(
            recognizer, model_path, vocab_path, device, threads, cpu_mem_arena
        )
    return recognizer
