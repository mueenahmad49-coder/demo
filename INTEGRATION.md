# TrustMatrix: combined Django + React proctoring prototype

This folder integrates the four tested prototype phases into the supplied repository, based on commit `3a5e31c64030325a1b9e90d05ba171f28047eb61` from `https://github.com/mueenahmad49-coder/demo`. No GitHub branch or remote content was changed.

## What is connected

| Phase | Model / processing | Integration |
| --- | --- | --- |
| 1: identity and liveness | YuNet, SFace, MiniFASNetV2 | Before the exam, then at a configurable interval; bounded retries and review if uncertain. |
| 2: object observations | Your Roboflow workflow reporting RF-DETR Small | Sampled phone/book/person detection, separate cloud consent, one request at a time, request budget, duplicate suppression. |
| 3: head / eye direction | MediaPipe Face Landmarker and OpenCV pose geometry | Screen-center calibration, optional head-only mode, sustained/repeated deviation and tracking-loss observations. |
| 4: face presence and reference comparison | Shared YuNet and SFace inference | Sustained detection loss, multiple faces, fresh comparisons after loss, and sustained mismatch review. |

The browser owns one webcam stream. It supplies the existing preview/snapshots and sends sampled JPEG frames to Django. Django runs the local models on the server and sends selected samples to Roboflow only with separate consent. The server uses its own arrival times and enforces one frame at a time. No Python webcam process is launched.

## What was preserved

The original `proctor` models, views, URL contracts and migrations remain unchanged. The existing student-ID entry, questions, previous/next navigation, answers in React state, ten-minute timer, submission screen, browser-event warnings, three-warning termination behavior, snapshot endpoint, initial snapshot and 60-second snapshot interval, and teacher violation log remain available.

The React entry flow now performs AI preparation before starting the existing timer and browser-event monitoring. Camera access is shared and stopped when the exam ends or the page closes. New AI observations have their own panel and staff-only review records; they do not trigger the legacy warning counter or disqualification logic. Legacy browser warnings retain their original wording and policy.

The repository did not implement persistent answer submission or authenticated student login. Those features have not been invented or claimed here. AI enrollment adds an operator-issued access code for the registered reference. It does not convert the entire original application into a production authentication system.

## Quick start in this existing workspace (Windows)

Open a terminal inside `outputs\proctoring-integrated`. Its `run-python.cmd` can use the separate test runtime already prepared under `work\python-integrated`. On another computer, first follow the fresh installation below.

1. Create a local configuration if you have not done so:

   ```powershell
   Copy-Item .env.example .env
   ```

   Edit `.env` locally. Your earlier Phase 1 tests acknowledged the unresolved MiniFAS weight-license scope. To run that same prototype model here, set `AI_MINIFAS_LICENSE_ACKNOWLEDGED=true` after retaining the notice in `model_licenses/PHASE1_MODEL_LICENSES.md`. This does not resolve the ambiguity or grant a commercial license.

   For all four phases, add your **private server-side** `ROBOFLOW_API_KEY`. The workspace and saved workflow ID are already set to the values you supplied. Do not share the key in chat, place it in React code, prefix it with `VITE_`, or commit `.env`. Without the key, local checks still work and the UI explicitly reports object checks as unconfigured. The student must also agree to Roboflow uploads before they occur.

2. Prepare a fresh local database and load the two original questions:

   ```powershell
   .\run-python.cmd manage.py migrate
   .\run-python.cmd manage.py loaddata original_questions
   .\run-python.cmd manage.py createsuperuser
   .\run-python.cmd manage.py check_ai_models
   ```

   The default database is `runtime.sqlite3`, separate from the repository's original `db.sqlite3`. Load the seed only when setting up a fresh database; question IDs 1 and 2 are retained. The source ZIP excludes databases, credentials, photos and logs.

3. As the operator, register an approved reference for the student. For your own test, the existing reference path can be used:

   ```powershell
   .\run-python.cmd manage.py enroll_reference --student-id TEST-001 --reference "..\proctoring-phase1\My_Photo.jpeg" --consent-confirmed
   ```

   This explicitly copies the approved photo into private local storage and prints a new exam access code once. Give the code only to that student. The stored code is hashed. No enrollment or personal-photo access was performed automatically during implementation. For another student, use their independently approved reference and consent. A student cannot upload their own comparison reference through the exam page.

4. Start Django in one terminal:

   ```powershell
   .\run-python.cmd manage.py runserver 127.0.0.1:8000 --noreload
   ```

5. Start React in a second terminal:

   ```powershell
   cd frontend
   npm.cmd ci
   npm.cmd run dev
   ```

   Open **http://127.0.0.1:5173**. The Vite development proxy routes `/api`, `/admin`, and `/static` to Django. Use the same `127.0.0.1` hostname for staff login. Close earlier prototypes and browser camera tests first.

6. Enter the enrolled ID and access code, read the camera/snapshot consent, and optionally consent to Roboflow uploads. Run the camera check. Face the camera, look at the screen center and hold still. **Begin exam** becomes available after matching, liveness and calibration pass. If eye calibration fails, select head-only mode and retry. This disables the eye-direction heuristic explicitly.

7. Open the existing teacher dashboard to see legacy logs. Sign in through its **Staff sign-in** link to view the separate private AI observation list. Django admin also provides reference activation/deactivation and AI record review. Uncertainty requests supervised verification; AI observations do not automatically end the exam.

## Fresh installation / ZIP on another computer

Use 64-bit Python **3.12**, Node.js **24**, and a desktop browser with webcam support. In the extracted root folder:

```powershell
py --list
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-tested.txt
Copy-Item .env.example .env
```

If `py -3.12` reports no suitable runtime, install Python 3.12 first or use the full path to an existing Python 3.12 executable. The earlier prototypes used Python 3.12; Python 3.14 is not the tested model runtime. Only one OpenCV distribution is installed here: `opencv-contrib-python`, shared with MediaPipe.

Continue with database setup, enrollment and both servers above. Public local model files are bundled and hash-checked; no weights download is needed. Python and npm dependency installation needs internet. Monitoring needs a connection from browser to Django; the object phase additionally needs Roboflow internet access and account credits.

## Tests and examples

```powershell
.\run-python.cmd manage.py check
.\run-python.cmd manage.py test ai_proctor
.\run-python.cmd manage.py check_ai_models
cd frontend
npm.cmd run lint
npm.cmd run build
npm.cmd run test:e2e
```

The browser tests use an installed Chrome browser, a simulated webcam and mocked API responses. They never open your real camera or send frames to Roboflow. Backend tests cover real Django routing/database behavior with simulated model results; synthetic smoke checks load the real local models. See `VALIDATION.md` for the completed checks and their limits.

For a quick periodic verification trial, set `AI_REVERIFY_SECONDS=15` in `.env` and restart Django. Restore `300` for the original five-minute interval. Frame sampling targets 400 ms after each completed request; actual speed depends on CPU and network. Identity/gaze gaps over 1.5 seconds interrupt evidence, rather than claiming continuous observations. Gaze confirmation uses elapsed time plus sample counts adjusted for shared HTTP processing. No thresholds were tuned using a claimed accuracy benchmark.

Roboflow requests are asynchronous, at most one per session, no faster than once every five seconds, and capped by `AI_CLOUD_MAX_REQUESTS` (default 120). Old, failed, missing or malformed responses are unknown rather than an empty scene. Phone/book/person observations may take several successful cloud samples to confirm; the exact hosted checkpoint remains unverified.

## Model licensing and limits

The exact local model hashes and sources are in `model_assets/manifest.json`. Preserve the notices in `model_licenses/` when distributing:

- YuNet and SFace retain the Phase 1 model-directory MIT and Apache 2.0 evidence.
- MiniFASNetV2 retains its explicit weight-specific licensing ambiguity. The acknowledgement setting is required for evaluation; it is not a commercial-clearance claim.
- MediaPipe uses the pinned Face Landmarker bundle, canonical geometry, model cards and version caveats from Phase 3.
- Phase 2 uses the saved workflow reporting RF-DETR Small. The old `yolo-world-small-demo` workflow name does not establish the model identity. Hosted model weights cannot be hash-verified here; service terms and credits are separate from model licensing.

No extra YOLOv8-face/DeepFace models were introduced. Recognition scores and iris/head geometry are not probabilities of cheating. Photos/replays can still fool passive anti-spoofing; passing the check is not proof of secure identity. Full sideways turns can cause tracking or face-detection loss, without proving that a person left. Gaze is approximate calibrated geometry, not a validated measure of attention or a measured screen point.

## Privacy, retention and deployment boundaries

The new inference endpoints do not save webcam images, face embeddings, landmarks, or similarity scores. Reference photos are saved only by explicit operator enrollment under `private_data/references` and are never served through a media URL. Session tokens stay in browser memory; the database stores their hashes. AI event records contain timestamps, session/student links and observation metadata.

**The original snapshot feature is intentionally preserved:** it stores an initial JPEG and another every 60 seconds through the existing endpoint. The consent text states this. Those existing snapshots and legacy logs have their own retention needs; the new AI cleanup command does not silently delete them.

```powershell
.\run-python.cmd manage.py purge_ai_records --days 7
.\run-python.cmd manage.py revoke_reference --student-id TEST-001 --confirm-delete
```

The first command removes old AI session/event records only. The second revokes an enrollment and deletes its private photo plus related AI records; active API access is then rejected. Stop the associated browser session. Disconnected runtime buffers expire within two minutes. Python/native buffers, paging and process crashes mean secure memory erasure is not guaranteed. Keep private folders/database access restricted and use HTTPS outside localhost.

This is a **single-process local integration prototype**, with at most two live AI sessions. Run Django with `--noreload`; process restarts require a fresh precheck. Multiple production workers need shared durable session coordination and separate bounded inference workers. This implementation does not claim production scalability, secure exam lockdown, camera-source attestation or an anti-tampering client.

Existing public legacy endpoints, broad development CORS, the original development secret fallback and the original student-ID/admin-view design remain inherited limitations. The new staff AI review API requires authenticated staff, but it does not secure all legacy endpoints by implication. Production authentication/authorization, HTTPS, deployment settings, retention policy, model calibration and human review need a separate agreed change. Set a fresh `DJANGO_SECRET_KEY` and disable debug for deployment.

## Preparing the later GitHub branch

This local folder retains the original Git history. No commit or push was made. The ZIP is a clean source/model deliverable without `.git`, dependencies, private data or databases. When you request the next step, create the agreed `codex/...` branch, review the diff and tracked upstream database/cache files, then commit and push. `.gitignore` does not untrack files already committed by the original repository.
