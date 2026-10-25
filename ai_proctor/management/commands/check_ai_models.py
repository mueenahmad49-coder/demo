from django.core.management.base import BaseCommand
from ai_proctor.assets import verify_assets, face_paths


class Command(BaseCommand):
    help = 'Verify public model hashes and smoke-test loading without personal images or a camera'

    def handle(self, **options):
        import numpy as np
        import onnxruntime as ort
        from ai_proctor.core.face_engine import Engine
        from ai_proctor.core.gaze_vision import Vision
        from ai_proctor.inference import identity_settings, gaze_settings
        paths = verify_assets()
        engine = Engine(face_paths(paths), identity_settings())
        _, sample, _ = engine.inspect(np.zeros((480, 640, 3), np.uint8))
        assert sample.faces == 0
        feature = engine.recognizer.feature(np.zeros((112, 112, 3), np.uint8))
        assert feature.shape == (1, 128) and np.isfinite(feature).all()
        pad = ort.InferenceSession(str(paths['MiniFASNetV2.onnx']), providers=['CPUExecutionProvider'])
        result = pad.run(None, {pad.get_inputs()[0].name: np.zeros((1, 3, 80, 80), np.float32)})[0]
        assert result.shape == (1, 3) and np.isfinite(result).all()
        vision = Vision(paths['face_landmarker.task'], paths['canonical_face_model.obj'], gaze_settings())
        try:
            measurement, _, _ = vision.read(np.zeros((480, 640, 3), np.uint8), 1.)
            assert measurement is None
        finally:
            vision.close()
        self.stdout.write('PASS: hashes and real local-model synthetic smoke checks. No camera, real identity accuracy, spoof test, or Roboflow call.')
