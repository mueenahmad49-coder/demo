# Integration change map

Base repository: `mueenahmad49-coder/demo`, commit `3a5e31c64030325a1b9e90d05ba171f28047eb61`.

## Original features retained

- No edits to `proctor/models.py`, `proctor/views.py`, `proctor/urls.py`, `proctor/serializers.py`, `proctor/admin.py`, or the three original migrations.
- No redesign of the question, answer, navigation, timer, submission, violation-log or warning-popup components.
- Original browser event types and three-warning policy remain in the existing handlers. AI observations do not call those handlers.
- Initial and 60-second snapshots still use the original endpoint. Their storage behavior is disclosed before the exam.
- Original two question texts/IDs were exported to `proctor/fixtures/original_questions.json` without alteration. No original user accounts, stored snapshots or event logs were exported to the deliverable ZIP.

## Existing files changed

| File | Reason |
| --- | --- |
| `backend/settings.py` | Register the AI app and bounded upload middleware; add environment-driven integration settings; use a separate local runtime database. |
| `backend/urls.py` | Add `/api/ai/` without changing original routes. |
| `frontend/src/App.jsx` | Add preparation before exam start, reuse one camera stream, connect AI status/staff observations, stop capture at exam end, route existing API calls through the configured base. |
| `frontend/vite.config.js` | Proxy API/admin/static routes to the local backend. |
| `frontend/package.json` and lockfile | Add browser regression tests. Existing React/Vite application dependencies retained. |

## New code

- `ai_proctor/core`: adapted phase policy/vision/Roboflow modules with package-relative imports. The standalone camera and command-line loops are replaced by server session orchestration.
- `ai_proctor/inference.py`: shared face detector/recognizer and liveness preprocessing, MediaPipe inference, bounded JPEG decoding.
- `ai_proctor/runtime.py`, `checks.py`: per-session temporal evidence, calibration, retries, periodic verification, bounded asynchronous object requests and cleanup.
- `ai_proctor/models.py`, migration, API, admin, commands: trusted reference enrollment, hashed access codes, session-scoped capabilities, metadata events and staff review.
- `frontend/src/ai`: browser camera lifecycle, sequential frame uploads, preparation and status panels.
- Tests, public model files/notices, environment example, dependency manifests and setup/validation documentation.

## Deliberate integration choices

- This backend performs CPU inference for a single-process local prototype. Browser frames replace the standalone OpenCV webcam capture.
- Shared face quality uses a 100-pixel minimum face size, sharpness 20, and brightness 35–220. SFace matching uses 0.45; sustained mismatch review uses 0.25 with uncertainty in between. MiniFAS live score uses 0.90. These are experimental thresholds, not a demonstrated accuracy guarantee.
- Liveness requires five consecutive usable matching/live samples within 15-second windows, with up to three attempts separated by three seconds. During an exam, unresolved rechecks request review while preserving the existing exam flow.
- The shared network/CPU sample cadence differs from the standalone tools. Gaze calibration requires at least 12 usable samples and four seconds; evidence gaps over 1.5 seconds interrupt identity/gaze confirmation. Timing changes and failures are tested.
- Head-only calibration is explicit. It does not pretend eye direction was measured.
- The original public teacher violation list is retained. New AI review records require staff authentication and are not exposed by that legacy endpoint.
- `.env`, private references, runtime databases, node_modules, caches and browser-test output are excluded from the ZIP. Git history remains in the local checkout for a later branch/push.

## Dependency compatibility

The repository identifies Django 6.1.2. The integration pins that version and Django REST framework 3.18.3; the upstream 3.18 series added Django 6.1 support and replaced an incompatible cache-header import. [Official release notes](https://www.django-rest-framework.org/community/release-notes/#3180).

`requirements-tested.txt` records the resolved Python environment. Model dependencies reuse the pinned versions from the earlier prototypes. No TensorFlow or DeepFace stack was introduced.
