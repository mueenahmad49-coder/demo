# Model source and licensing record

Checked 2026-10-24. This client connects to the user's saved Roboflow workflow; it contains no pretrained weights.

| Component | Source and license evidence | Exact-artifact status |
| --- | --- | --- |
| RF-DETR Small object detector | Roboflow's [model page](https://playground.roboflow.com/models/roboflow/rf-detr) explicitly describes Nano/Small/Medium/Large code and weights as Apache 2.0. The [official detection documentation](https://rfdetr.roboflow.com/latest/learn/run/detection/) lists `rfdetr-small` with that license. | The user's workflow editor reports `rfdetr-small`. The exact hosted checkpoint filename, revision, and SHA-256 were not exposed or independently verified. **Unpinned remote artifact.** |
| Roboflow Serverless Cloud API | [Official API documentation](https://docs.roboflow.com/deployment/roboflow-cloud/serverless-api) and [credit pricing](https://docs.roboflow.com/deployment/roboflow-cloud/serverless-api/pricing). | Account/service terms and credits apply separately from the model license. This is not a promise of free unlimited cloud inference. |
| Prototype Python source | `LICENSE` in this folder, MIT. | Source only; third-party dependencies retain their own licenses. |

RF-DETR Small is the selected permissively licensed model family, based on the explicit vendor statement for code **and weights**, not merely a repository's code license. The inference API response does not prove the exact checkpoint. The old workflow ID `yolo-world-small-demo` must not be used to infer the underlying model or its license. If the model changes, reassess the new model's weights and terms. RF-DETR XL/2XL do not share the Small model's license according to the cited vendor sources.

No Ultralytics YOLOv8 or YOLO-World weights are downloaded or bundled here. The prior YOLO-World cloud failure and replacement were observed in the user's supplied UI screenshots. This program neither owns nor changes that remote configuration. No additional commercial model license is indicated for RF-DETR Small by the cited sources; service costs and rights to any test/training images remain separate.

For reproducible deployment later, obtain an identifiable checkpoint and digest, retain its license/notice files, and freeze the workflow/model version. That verification is not claimed for this hosted prototype. The Phase 1 MiniFASNet weight ambiguity remains separate and is not resolved by selecting RF-DETR for Phase 2.

API implementation references: [Serverless API authentication and transport](https://docs.roboflow.com/deployment/roboflow-cloud/serverless-api), [Roboflow's workflow REST examples](https://github.com/roboflow/computer-vision-skills/blob/main/skills/roboflow-api-reference/inference.md). Requests use the documented `inputs.image` base64 object and HTTPS authorization header. Mocked responses cover parsing/errors. The user's supplied 2026-10-24 client log shows 10 successful hosted requests, confirming basic live authentication and inference for that workflow/account. It does not identify or pin the exact checkpoint.
