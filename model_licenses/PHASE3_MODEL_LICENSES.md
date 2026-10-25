# Phase 3 sources and licenses

Checked and downloaded 2026-10-24. Exact URLs, sizes and SHA-256 hashes are recorded in `assets.json`. Normal inference verifies the model bundle and canonical geometry hashes. Model cards and the upstream license text are retained in `licenses/`.

## Exact pretrained bundle

- Google-hosted [Face Landmarker float16 version 1](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task).
- Filename: `models/face_landmarker.task`; size: 3,758,596 bytes.
- SHA-256: `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`.
- Verified archive contents: `face_detector.tflite`, `face_landmarks_detector.tflite`, `geometry_pipeline_metadata_landmarks.binarypb`, and `face_blendshapes.tflite`.
- Official provenance: the [Face Landmarker model table](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker) links the bundle and the three model cards below. The download uses numeric version `1`, not a moving `latest` URL. No custom weights or third-party mirror are used.

| Bundled component | Primary license evidence |
| --- | --- |
| Face Mesh V2 | Page 1 of Google's [Face Mesh V2 model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20MediaPipe%20Face%20Mesh%20V2.pdf) explicitly lists Apache License 2.0. |
| BlazeFace short-range detector | Page 1 of Google's [short-range BlazeFace model card](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20%28Short%20Range%29.pdf) explicitly lists Apache License 2.0. |
| Blendshape model (bundled; output disabled here) | Page 1 of Google's [Blendshape V2 model card](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Blendshape%20V2.pdf) explicitly lists Apache License 2.0. |

These explicit model-card statements support permissive commercial use of the documented pretrained components, subject to Apache notice/license requirements. This is more specific evidence than assuming a code repository's license applies to its weights. Preserve the supplied license/notices when redistributing.

**Scope caveat:** the official guide associates the component cards with the bundle; the cards do not contain this exact bundle's SHA-256 or a separate signed license manifest. The guide lists a 192×192 detector input, while its linked older short-range detector card describes 128×128. That documentation/version mismatch is retained here rather than silently asserting byte-specific certification. The bundle itself has been pinned and hashed, but its training data lineage and accuracy for proctoring were not independently audited. A model card's out-of-scope use statements are suitability limits, separate from the Apache license permissions.

## Code and canonical face geometry

- Runtime: `mediapipe==0.10.32`, [official PyPI release](https://pypi.org/project/mediapipe/0.10.32/) and [source tag](https://github.com/google-ai-edge/mediapipe/tree/v0.10.32), Apache 2.0 with third-party notices in the upstream license.
- Canonical mesh: [official OBJ at v0.10.32](https://github.com/google-ai-edge/mediapipe/blob/v0.10.32/mediapipe/modules/face_geometry/data/canonical_face_model.obj), 468 vertices. File SHA-256: `8bac80443397e113f41a8b565ea72c59390bc031d9defab289dba7bc0c54e618`. This is geometry, not a learned checkpoint. The prototype selects six vertices and changes coordinate axes in memory for OpenCV.
- [Upstream license at the same tag](https://github.com/google-ai-edge/mediapipe/blob/v0.10.32/LICENSE) is copied unchanged as `licenses/mediapipe-APACHE-2.0.txt`, including its additional third-party license text.
- OpenCV and NumPy are installed dependencies with their own distributed license files. Their wheels and the Python runtime are not included in the project ZIP. `requirements-tested.txt` records the installed versions.
- Prototype source: MIT, see `LICENSE`. Third-party model/geometry/card/license files retain their upstream terms and are not relicensed under MIT.

No paid model license or cloud subscription is required for the selected local components based on this evidence. The prototype performs no training and does not introduce a separate gaze-model checkpoint. Approximate iris direction is a local geometric heuristic.

## Suitability and privacy limits

The linked model cards describe face/AR use and limitations with extreme pose, partial faces, poor lighting and other capture conditions. They do not establish gaze-to-screen accuracy or validated exam monitoring. Apache licensing does not establish privacy-law compliance, consent, or suitability for consequential decisions. The prototype has no misconduct decision or identity inference.

The [current MediaPipe privacy notice](https://pypi.org/project/mediapipe/) discusses on-device inputs and usage/performance metrics. See the README's pinned-runtime/offline caveat. Source licenses do not prove that a binary makes no telemetry attempts.
