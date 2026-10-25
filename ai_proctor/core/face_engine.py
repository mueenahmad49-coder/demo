"""Pinned YuNet and SFace; embeddings exist only in memory."""
import cv2
import numpy as np
from .identity_policy import Sample


def frontal_enough(face):
    """Conservative 2D alignment checks, not a calibrated head-pose estimator."""
    points = np.asarray(face[4:14], np.float64).reshape(5, 2)
    left, right = sorted(points[:2], key=lambda p: p[0])
    eye = right-left
    span = float(np.linalg.norm(eye))
    if span <= 0 or span/face[2] < .25 or abs(eye[1])/span > .35:
        return False
    nose_fraction = float(np.dot(points[2]-left, eye)/(span*span))
    return .2 <= nose_fraction <= .8 and points[2, 1] > min(left[1], right[1])


class Engine:
    def __init__(self, paths, settings):
        self.s = settings
        self.detector = cv2.FaceDetectorYN.create(str(paths['yunet']), '', (320, 320), settings.detector_threshold, .3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(paths['sface']), '')

    def inspect(self, image):
        if image is None or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 32:
            return None, Sample(None, 'invalid_frame'), {}
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(image)
        count = 0 if faces is None else len(faces)
        if count != 1:
            return None, Sample(count, 'no_face' if count == 0 else 'multiple_faces'), {}
        face = faces[0]
        if face.shape != (15,) or not np.isfinite(face).all():
            return None, Sample(None, 'invalid_detection'), {}
        x, y, width, height = map(float, face[:4])
        info = dict(face_width=round(width), face_height=round(height))
        if min(width, height) < self.s.min_face:
            return None, Sample(1, 'face_too_small'), info
        if x < 0 or y < 0 or x+width > w or y+height > h:
            return None, Sample(1, 'face_clipped'), info
        landmarks = face[4:14].reshape(5, 2)
        if np.any(landmarks < [x, y]) or np.any(landmarks > [x+width, y+height]):
            return None, Sample(1, 'landmarks_uncertain'), info
        gray = cv2.cvtColor(image[int(y):int(y+height), int(x):int(x+width)], cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        info.update(sharpness=round(sharpness, 1), brightness=round(brightness, 1))
        if not self.s.min_brightness <= brightness <= self.s.max_brightness:
            return None, Sample(1, 'lighting_uncertain'), info
        if sharpness < self.s.min_sharpness:
            return None, Sample(1, 'blur_uncertain'), info
        if not frontal_enough(face):
            return None, Sample(1, 'face_angle_uncertain'), info
        return face, Sample(1, 'quality_ok'), info

    def feature(self, image, face):
        feature = self.recognizer.feature(self.recognizer.alignCrop(image, face))
        if feature.shape != (1, 128) or not np.isfinite(feature).all() or np.linalg.norm(feature) < 1e-8:
            raise ValueError('Invalid recognition output')
        return feature.copy()

    def reference(self, path):
        # imdecode handles Windows paths containing non-ASCII characters.
        data = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
        face, sample, _ = self.inspect(image)
        if face is None:
            raise ValueError('Reference rejected: '+sample.reason)
        return self.feature(image, face)

    def evaluate(self, image, reference):
        face, sample, info = self.inspect(image)
        if face is None:
            return sample, info, None
        try:
            feature = self.feature(image, face)
            score = float(self.recognizer.match(reference, feature, cv2.FaceRecognizerSF_FR_COSINE))
            if not np.isfinite(score) or not -1 <= score <= 1:
                raise ValueError('Invalid recognition score')
        except (ValueError, cv2.error):
            return Sample(1, 'recognition_unavailable'), info, face[:4]
        return Sample(1, 'quality_ok', score), info, face[:4]
