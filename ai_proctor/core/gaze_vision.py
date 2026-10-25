"""Face landmarks -> generic-camera PnP pose and experimental iris-position ratios."""
from pathlib import Path
import cv2
import numpy as np

from .gaze_policy import Measurement

POSE_IDS = (1, 152, 33, 263, 61, 291)
EYES = ((33, 133, 160, 144, 158, 153, 468), (362, 263, 385, 380, 387, 373, 473))


def canonical_points(path):
    vertices = [list(map(float, line.split()[1:4])) for line in Path(path).read_text().splitlines() if line.startswith('v ')]
    if len(vertices) != 468:
        raise ValueError('Canonical face geometry must contain 468 vertices')
    # MediaPipe canonical coordinates: y up, z toward viewer. OpenCV: y down, z forward.
    return np.asarray(vertices, np.float64)[list(POSE_IDS)] * np.array([1., -1., -1.])


def camera_matrix(width, height):
    focal = float(max(width, height))
    return np.array([[focal, 0, width/2], [0, focal, height/2], [0, 0, 1]], np.float64)


def solve_pose(image_points, object_points, width, height, face_width, max_error_ratio, diagnostics=None):
    """Fit each frame independently; uncertain geometry never inherits an old pose."""
    details = diagnostics if diagnostics is not None else {}
    details['pose_solver'] = 'sqpnp_lm'

    def reject(reason):
        details['pose_failure'] = reason
        return None

    image_points = np.asarray(image_points, np.float64)
    object_points = np.asarray(object_points, np.float64)
    if (image_points.ndim != 2 or image_points.shape[1] != 2 or
            object_points.shape != (len(image_points), 3) or len(image_points) < 6 or
            not np.isfinite(image_points).all() or not np.isfinite(object_points).all() or
            not np.isfinite([width, height, face_width, max_error_ratio]).all() or
            min(width, height, face_width, max_error_ratio) <= 0 or
            np.linalg.matrix_rank(image_points-image_points.mean(axis=0)) < 2):
        return reject('pose_invalid_points')
    matrix = camera_matrix(width, height)
    try:
        # Six facial correspondences are sensitive to the default ITERATIVE/DLT
        # initialization: slightly noisy valid faces can produce negative depth.
        # SQPnP supplies a geometric initial estimate; LM refines its pixel fit.
        ok, rvec, tvec = cv2.solvePnP(object_points, np.asarray(image_points, np.float64), matrix,
                                   np.zeros(5), flags=cv2.SOLVEPNP_SQPNP)
        if not ok:
            return reject('pose_solver_failed')
        if not np.isfinite(rvec).all() or not np.isfinite(tvec).all():
            return reject('pose_nonfinite_solution')
        rvec, tvec = cv2.solvePnPRefineLM(object_points, image_points, matrix, np.zeros(5), rvec, tvec)
        if not np.isfinite(rvec).all() or not np.isfinite(tvec).all():
            return reject('pose_nonfinite_solution')
        rotation, _ = cv2.Rodrigues(rvec)
        if np.min((rotation @ object_points.T + tvec)[2]) <= 0:
            return reject('pose_behind_camera')
        projected, _ = cv2.projectPoints(object_points, rvec, tvec, matrix, np.zeros(5))
        error = float(np.sqrt(np.mean(np.sum((projected.reshape(-1, 2)-image_points)**2, axis=1))))
        if not np.isfinite(error):
            return reject('pose_nonfinite_solution')
        details['reprojection_ratio'] = round(error/face_width, 4)
        if error/face_width > max_error_ratio:
            return reject('pose_fit_error')
        pitch, yaw, roll = cv2.RQDecomp3x3(rotation)[0]
        if max(abs(pitch), abs(yaw), abs(roll)) > 75:
            return reject('pose_angle_out_of_range')
        return float(pitch), float(yaw), float(roll), error/face_width
    except cv2.error:
        return reject('pose_solver_failed')


def eye_ratios(points, ids, settings):
    a, b, u1, l1, u2, l2, iris = points[list(ids)]
    if a[0] > b[0]:
        a, b = b, a
    axis = b-a
    width = float(np.linalg.norm(axis))
    if width < settings.min_eye_width:
        return None
    openness = (np.linalg.norm(u1-l1)+np.linalg.norm(u2-l2))/(2*width)
    if openness < settings.min_eye_open_ratio:
        return None
    axis /= width
    down = np.array([-axis[1], axis[0]])
    center = (u1+l1+u2+l2)/4
    x = float(np.dot(iris-(a+b)/2, axis)/width)
    y = float(np.dot(iris-center, down)/width)
    if abs(x) > .65 or abs(y) > .3:
        return None
    return x, y


class Vision:
    def __init__(self, model_path, geometry_path, settings):
        import mediapipe as mp
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        self.mp, self.settings = mp, settings
        self.object_points = canonical_points(geometry_path)
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO, num_faces=2,
            min_face_detection_confidence=.6, min_face_presence_confidence=.6,
            min_tracking_confidence=.6, output_face_blendshapes=False,
            output_facial_transformation_matrixes=False)
        self.detector = vision.FaceLandmarker.create_from_options(options)
        self.last_ms = -1

    def read(self, frame, captured_at):
        s = self.settings
        h, w = frame.shape[:2]
        timestamp = max(self.last_ms+1, int(captured_at*1000))
        self.last_ms = timestamp
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.detector.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), timestamp)
        count = len(result.face_landmarks)
        info = dict(faces=count, reason='no_face' if count == 0 else 'multiple_faces')
        if count != 1:
            return None, info, []
        landmarks = result.face_landmarks[0]
        if len(landmarks) < 478:
            return None, dict(faces=1, reason='missing_iris_landmarks'), []
        pts = np.array([[p.x*w, p.y*h] for p in landmarks], np.float64)
        if not np.isfinite(pts).all():
            return None, dict(faces=1, reason='invalid_landmarks'), []
        lo, hi = pts[:468].min(axis=0), pts[:468].max(axis=0)
        face_width = float(hi[0]-lo[0])
        if face_width < s.min_face_width:
            return None, dict(faces=1, reason='face_too_small'), []
        if lo[0] < 0 or lo[1] < 0 or hi[0] >= w or hi[1] >= h:
            return None, dict(faces=1, reason='face_partly_out_of_frame'), []
        x1, y1 = lo.astype(int)
        x2, y2 = np.ceil(hi).astype(int)
        gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(gray.mean())
        info = dict(faces=1, reason='valid', sharpness=round(sharpness, 1), brightness=round(brightness, 1))
        if sharpness < s.min_sharpness or not s.min_brightness <= brightness <= s.max_brightness:
            info['reason'] = 'image_quality_uncertain'
            info['quality_failure'] = 'image_blurred' if sharpness < s.min_sharpness else 'image_brightness_out_of_range'
            return None, info, []
        pose = solve_pose(pts[list(POSE_IDS)], self.object_points, w, h, face_width, s.max_reprojection_ratio, info)
        if pose is None:
            info['reason'] = 'head_pose_uncertain'
            return None, info, []
        eyes = [eye_ratios(pts, ids, s) for ids in EYES]
        eye_x = eye_y = None
        if all(e is not None for e in eyes) and abs(eyes[0][0]-eyes[1][0]) <= .18 and abs(eyes[0][1]-eyes[1][1]) <= .10:
            eye_x, eye_y = np.mean(eyes, axis=0).tolist()
        else:
            info['eye_reason'] = 'eyes_closed_small_or_inconsistent'
        info['reprojection_ratio'] = round(pose[3], 4)
        measurement = Measurement(*pose[:3], eye_x, eye_y, face_width/w)
        overlay = pts[list(POSE_IDS)+[468, 473]].astype(int).tolist()
        return measurement, info, overlay

    def close(self):
        self.detector.close()
