import json
from pathlib import Path
from typing import List, Tuple


def load_vocab(path: str | Path | None = None) -> Tuple[List[str], dict]:
    if path is None:
        default = Path(__file__).resolve().parents[3] / "models" / "vocab.json"
        if not default.exists():
            raise FileNotFoundError(
                "vocab.json not found. Place it in models/vocab.json "
                "or pass an explicit path."
            )
        path = default

    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    chars = data["characters"]
    char2idx = {c: i + 1 for i, c in enumerate(chars)}
    return chars, char2idx
