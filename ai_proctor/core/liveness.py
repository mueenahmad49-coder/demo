"""Pinned Phase 1 MiniFAS preprocessing and score interpretation."""
import cv2
import numpy as np

def pad_tensor(image, face):
    # Contract of the pinned yakhyo ONNX release: BGR float32 0..255,
    # NOT RGB and NOT /255. Match its clipped 2.7x context crop.
    height, width = image.shape[:2]
    x, y, w, h = map(int, face[:4])
    if w <= 0 or h <= 0:
        raise ValueError('Invalid face box')
    scale = min(2.7, (height - 1) / h, (width - 1) / w)
    cx, cy = x + w / 2, y + h / 2
    x1, y1 = max(0, int(cx - w * scale / 2)), max(0, int(cy - h * scale / 2))
    x2, y2 = min(width - 1, int(cx + w * scale / 2)), min(height - 1, int(cy + h * scale / 2))
    crop = image[y1:y2 + 1, x1:x2 + 1]
    if not crop.size:
        raise ValueError('Empty context crop')
    resized = cv2.resize(crop, (80, 80))
    return np.ascontiguousarray(resized.transpose(2, 0, 1)[None], dtype=np.float32)


def live_probability(logits):
    scores = np.asarray(logits, dtype=np.float64)
    if scores.shape != (1, 3) or not np.isfinite(scores).all():
        raise ValueError('Invalid MiniFAS logits')
    exp = np.exp(scores[0] - scores.max())
    return float((exp / exp.sum())[1])


