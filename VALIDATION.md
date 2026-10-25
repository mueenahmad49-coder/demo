# Integration validation

Checked 2026-10-24 in the shared Windows workspace. Source base: `3a5e31c64030325a1b9e90d05ba171f28047eb61`.

## Completed checks

| Check | Result / scope |
| --- | --- |
| Django system check | Passed with no reported issues. |
| Migration consistency | `makemigrations --check --dry-run`: no changes detected. |
| Fresh database migration | All original and additive AI migrations applied successfully to the separate runtime database. |
| Original question seed | Both original questions loaded with original IDs/text. |
| Backend regression/integration suite | **125 tests passed**. Includes adapted phase policy/geometry/transport tests and new Django API/session tests. |
| Actual local model smoke test | YuNet, SFace, MiniFASNetV2 and MediaPipe loaded and processed synthetic inputs; local asset hashes passed. |
| React production build | Passed. |
| Frontend lint | Passed. |
| Browser flow tests | **4 tests passed** using Chrome with a simulated camera and mocked API responses. |
| Original backend diff | Original models, views, routes, serializers, admin and migrations have no source changes. |
| Actual local HTTP startup | Django served AI capabilities and both original questions; unauthenticated AI review returned 403. Test server stopped afterwards. |
| Visual review | Exam screen inspected using a simulated camera; existing question/timer/warnings remain alongside the new status panel. |

The backend suite checks pre-exam enforcement, failed liveness, stale evidence, periodic re-verification, absence/recovery/mismatch observations, independent legacy warnings, enrollment-code rejection, token scope, revocation, staff access, malformed/replayed/oversized uploads, cleanup, restart behavior, bounded cloud work and secret-free failure responses. Policy regressions cover uncertain scores, pose geometry, full-turn tracking loss, repeated gaze episodes, object duplicate suppression and malformed hosted responses.

The browser tests cover: preparation before timer/questions, access-code and consent transport, disabled begin button while uncertain, answer persistence across navigation, existing snapshot calls, submission/cancellation cleanup, preserved copy-warning behavior, and the separate staff-only AI review panel. Model results are mocked in those browser tests; this is not a biometric accuracy test.

## Not claimed or performed

- The assistant did not open a real webcam, enroll the user's photo, or upload frames to Roboflow.
- No live Roboflow request was made during integration; an operator must supply the key locally and the student must consent to uploads. The hosted checkpoint remains unpinned.
- Genuine-match/impostor accuracy, passive-liveness attack resistance, eye-direction accuracy, multi-person/book recall, and false-alert rates remain unmeasured for the combined browser capture path.
- The previous standalone webcam successes are useful context, but they do not certify this new shared CPU/network/frame-encoding setup.
- No load/scalability test, production security audit, browser-lockdown certification, persistent answer-submission feature or production deployment was added or claimed.
- No GitHub branch, commit, push or publishing action was performed.

## Manual acceptance sequence

1. Follow `INTEGRATION.md`: configure local evaluation settings, register an approved reference, provide the Roboflow key if testing all four phases, and start both servers.
2. Enter the assigned ID/code. Check that the exam timer does not start during calibration and initial identity/liveness verification.
3. Complete preparation and begin the exam. Confirm the existing questions, navigation, answers and timer remain usable.
4. Stay frontal for a baseline, then leave the camera frame for several seconds and return. Confirm no-face observation and fresh reference matching, without an automatic cheating verdict.
5. Try moderate head turns with a return to the screen center, then a full profile. Moderate turns may support direction observations; a full profile may instead produce tracking loss.
6. Hold a phone visibly for several cloud samples and then remove it. Check request status and eventual observation/clear events. Test a book and a second consenting adult when available; leave these marked untested until then.
7. For a brief periodic trial, set the interval to 15 seconds and restart Django. Watch for a new identity/liveness check during the exam, then restore the normal interval.
8. Submit/cancel, confirm the webcam indicator stops, and review AI metadata as authenticated staff. Review legacy snapshots separately because their original storage feature remains enabled.

Keep a short action/time note with the events. Session completion alone is not proof that every model check passed. If reference or liveness remains uncertain, use a supervised alternative rather than tuning thresholds until it passes.
