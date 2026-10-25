import hashlib
import json
from django.conf import settings


def verify_assets():
    root = settings.BASE_DIR/'model_assets'
    records = json.loads((root/'manifest.json').read_text())
    paths = {}
    for record in records:
        path = root/record['file']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Model missing or changed: '+record['file'])
        paths[record['file']] = path
    return paths


def face_paths(paths):
    return dict(yunet=paths['face_detection_yunet_2023mar.onnx'], sface=paths['face_recognition_sface_2021dec.onnx'])
