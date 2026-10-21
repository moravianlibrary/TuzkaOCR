from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from . import _models


IMAGE_SIZE = 320
CLASS_ANGLES = (0, 90, 180, 270)


def gray_median(page: np.ndarray) -> int:
    histogram = cv2.calcHist([page], [0], None, [256], [0, 256]).reshape(-1)
    cumulative = np.cumsum(histogram)
    count = page.size
    lower = int(np.searchsorted(cumulative, (count + 1) // 2))
    upper = int(np.searchsorted(cumulative, count // 2 + 1))
    return int(round((lower + upper) / 2))


def preprocess_page(page: np.ndarray) -> np.ndarray:
    array = np.asarray(page)
    if array.ndim == 3:
        if array.shape[2] == 1:
            array = array[:, :, 0]
        elif array.shape[2] == 3:
            if np.array_equal(array[:, :, 0], array[:, :, 1]) and np.array_equal(
                array[:, :, 0], array[:, :, 2]
            ):
                array = array[:, :, 0]
            else:
                array = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError(f"Expected a grayscale or BGR page, got shape {array.shape}")
    if array.ndim != 2:
        raise ValueError(f"Expected a grayscale page, got shape {array.shape}")
    if array.dtype != np.uint8:
        if np.issubdtype(array.dtype, np.floating):
            scale = 255.0 if float(np.nanmax(array)) <= 1.0 else 1.0
            array = np.clip(array * scale, 0, 255).astype(np.uint8)
        else:
            array = np.clip(array, 0, 255).astype(np.uint8)
    height, width = array.shape
    if height < 1 or width < 1:
        raise ValueError(f"Empty page shape {array.shape}")
    scale = IMAGE_SIZE / max(height, width)
    resized_height = max(1, min(IMAGE_SIZE, int(round(height * scale))))
    resized_width = max(1, min(IMAGE_SIZE, int(round(width * scale))))
    resized = cv2.resize(array, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    fitted = np.full((IMAGE_SIZE, IMAGE_SIZE), gray_median(resized), dtype=np.uint8)
    top = (IMAGE_SIZE - resized_height) // 2
    left = (IMAGE_SIZE - resized_width) // 2
    fitted[top : top + resized_height, left : left + resized_width] = resized
    return fitted.astype(np.float32)[None, None, :, :] / 255.0


class OrientationClassifier:
    def __init__(self, model_path: str | Path = "orient-A.onnx"):
        resolved = _models.resolve(model_path)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(resolved), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.input_name = self.session.get_inputs()[0].name

    def predict(self, page: np.ndarray) -> tuple[int, float, list[float]]:
        tensor = preprocess_page(page)
        logits = np.asarray(self.session.run(None, {self.input_name: tensor})[0][0],
                            dtype=np.float64)
        stable = logits - np.max(logits)
        probabilities = np.exp(stable)
        probabilities /= probabilities.sum()
        index = int(np.argmax(probabilities))
        return CLASS_ANGLES[index], float(probabilities[index]), probabilities.tolist()
