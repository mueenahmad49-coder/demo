# Exact model sources and licensing review

Reviewed 2026-10-24. `models.json` identifies the exact artifacts, URLs, source
commits and SHA-256 hashes. Copies of the applicable repository/directory license
texts are in `licenses/`. A permissive software/model license is not proof that
training data, biometric processing or every downstream use is cleared.

| Exact artifact | Evidence | Assessment |
|---|---|---|
| `face_detection_yunet_2023mar.onnx` | OpenCV Zoo model README explicitly covers all directory files under MIT | Commercially permissive model license verified at the pinned revision; retain notice |
| `face_recognition_sface_2021dec.onnx` | OpenCV Zoo model README explicitly covers all directory files under Apache-2.0 | Commercially permissive model license verified at the pinned revision; retain license and applicable notices |
| `MiniFASNetV2.onnx` from yakhyo release `weights` | Conversion repository and minivision upstream each contain Apache-2.0 licenses | **Ambiguous exact-weight scope/provenance**; not represented as commercially cleared |

## Primary sources

OpenCV revision: `48b10fa505aeb51fbd127fc60a5c660040e823b7`.

- [YuNet model directory README and license scope](https://github.com/opencv/opencv_zoo/blob/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet/README.md)
- [YuNet MIT license](https://github.com/opencv/opencv_zoo/blob/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet/LICENSE)
- [SFace model directory README and license scope](https://github.com/opencv/opencv_zoo/blob/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_recognition_sface/README.md)
- [SFace Apache-2.0 license](https://github.com/opencv/opencv_zoo/blob/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_recognition_sface/LICENSE)

MiniFAS upstream revision: `b6d5f04ad78778917853b25c778acef6d5626d15`.
Converter source reviewed: `01a38903f4f2680bb59d32a994a6c7b5ae56f49b`.

- [Original Silent-Face-Anti-Spoofing project](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/tree/b6d5f04ad78778917853b25c778acef6d5626d15)
- [Upstream Apache-2.0 license](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/blob/b6d5f04ad78778917853b25c778acef6d5626d15/LICENSE)
- [Original V2 checkpoint](https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/blob/b6d5f04ad78778917853b25c778acef6d5626d15/resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.pth)
- [Converter README](https://github.com/yakhyo/face-anti-spoofing/blob/01a38903f4f2680bb59d32a994a6c7b5ae56f49b/README.md)
- [Converter Apache-2.0 license](https://github.com/yakhyo/face-anti-spoofing/blob/01a38903f4f2680bb59d32a994a6c7b5ae56f49b/LICENSE)
- [Release asset and publisher digest](https://api.github.com/repos/yakhyo/face-anti-spoofing/releases/tags/weights)
- [Selected ONNX release](https://github.com/yakhyo/face-anti-spoofing/releases/tag/weights)
- [ONNX inference contract](https://github.com/yakhyo/face-anti-spoofing/blob/01a38903f4f2680bb59d32a994a6c7b5ae56f49b/onnx_inference.py)
- [Export implementation](https://github.com/yakhyo/face-anti-spoofing/blob/01a38903f4f2680bb59d32a994a6c7b5ae56f49b/onnx_export.py)

The release URL/tag is mutable; the digest pins its content independently.
The converter commit identifies reviewed source, **not a verified build commit
for that release**. The repository references upstream MiniFAS, but this review
has not reproduced the conversion or proven numerical equivalence to the
original checkpoint. No separate, artifact-specific commercial weight grant or
complete training-data rights statement was located in the reviewed sources.
Repository Apache-2.0 is favorable evidence, not sufficient to erase those gaps.
This project deliberately marks MiniFAS as ambiguous and requires an explicit
evaluation acknowledgement for downloading and running it.

For an unambiguously commercially cleared deployment, obtain weight-scope and
provenance clarification from the relevant maintainers, or replace/train the
PAD model using documented permissive weights and properly licensed data. Free
licensing clarification may be possible; paying a separate license is not
assumed necessary, but this prototype cannot promise that the entire stack is
cleared without it. Acknowledging the ambiguity is not permission from a rights
holder. The code does not contact maintainers or send data.

No InsightFace/RetinaFace model is used or downloaded. The converter's detector
dependency is replaced by YuNet. No upstream training code or pickle/PyTorch
checkpoint is executed. Only the pinned ONNX artifact is loaded for PAD.

## Attribution

YuNet: Shiqi Yu and contributors; OpenCV Zoo distribution.
SFace: Yaoyao Zhong and contributors; OpenCV Zoo ONNX conversion/distribution.
MiniFASNet: minivision-ai / Minivision contributors; ONNX conversion by yakhyo.
The PAD crop/preprocessing follows the converter's published algorithm; this
implementation is adapted for YuNet and the standalone policy. Preserve the
included third-party license texts with model redistribution. This report
distinguishes model licensing from dependency licensing; package license notices
remain included in their installed distributions.
