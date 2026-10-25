"""Model calls only. Frames and biometric measurements never enter database fields."""
import io
import numpy as np
import cv2
from PIL import Image, UnidentifiedImageError
from django.conf import settings
from .assets import verify_assets, face_paths
from .core.face_engine import Engine
from .core.identity_policy import Settings as IdentitySettings, Sample
from .core.gaze_policy import Settings as GazeSettings
from .core.gaze_vision import Vision
from .core.liveness import pad_tensor, live_probability


def decode_frame(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 1500000:
        raise ValueError('Send a JPEG frame smaller than 1.5 MB')
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'JPEG' or not (160 <= image.width <= 1600 and 120 <= image.height <= 1200):
                raise ValueError('JPEG dimensions must be between 160x120 and 1600x1200')
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('Invalid JPEG frame') from None
    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError('Invalid JPEG frame')
    return frame


def gaze_settings():
    # HTTP round trips share CPU with recognition; evidence time is still measured,
    # and gaps invalidate observations. No assumption of the desktop's 12 FPS.
    return GazeSettings(sample_period=.4, max_sample_gap=1.5, calibration_samples=12,
                        calibration_max_gap=1.5, confirm_samples=3, tracking_loss_samples=3)


def identity_settings():
    return IdentitySettings(sample_period=.4, max_sample_gap=1.5)


class Analyzer:
    def __init__(self, reference_path):
        import onnxruntime as ort
        paths = verify_assets()
        self.face = Engine(face_paths(paths), identity_settings())
        self.reference = self.face.reference(reference_path)
        self.gaze = None
        try:
            self.pad = ort.InferenceSession(str(paths['MiniFASNetV2.onnx']), providers=['CPUExecutionProvider'])
            inp = self.pad.get_inputs()[0]
            if inp.shape[1:] != [3, 80, 80] or inp.type != 'tensor(float)':
                raise ValueError('Unexpected MiniFAS input contract')
            self.pad_input = inp.name
            self.gaze = Vision(paths['face_landmarker.task'], paths['canonical_face_model.obj'], gaze_settings())
        except Exception:
            self.close()
            raise

    def analyze(self, frame, now, need_liveness):
        face, sample, _ = self.face.inspect(frame)
        liveness = 'not_due'
        if face is not None:
            try:
                feature = self.face.feature(frame, face)
                score = float(self.face.recognizer.match(self.reference, feature, cv2.FaceRecognizerSF_FR_COSINE))
                if not np.isfinite(score) or not -1 <= score <= 1:
                    raise ValueError('Invalid score')
                sample = Sample(1, 'quality_ok', score)
                if need_liveness:
                    probability = live_probability(self.pad.run(None, {self.pad_input: pad_tensor(frame, face)})[0])
                    liveness = 'verified_sample' if score >= .45 and probability >= .9 else (
                        'identity_unconfirmed' if score < .45 else 'liveness_unconfirmed')
            except (ValueError, cv2.error):
                sample = Sample(1, 'recognition_unavailable')
                liveness = 'recognition_unavailable'
        elif need_liveness:
            liveness = sample.reason
        measurement, quality, _ = self.gaze.read(frame, now)
        return sample, liveness, measurement, quality['reason']

    def close(self):
        self.reference.fill(0)
        if self.gaze is not None:
            self.gaze.close()
            self.gaze = None
        self.pad = None
