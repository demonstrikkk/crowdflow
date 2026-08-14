---
description: Run the CrowdFlow visual verification loop — capture screenshots of the live app, then have the vision-capable reviewer judge them against the product rubric.
agent: build
---

Run the CrowdFlow visual verification loop. The user's intent is to verify the
RENDERED application, not source code. Follow these steps:

1. Ensure the backend and frontend are running (or pass `--serve` to start them):
   - Backend: `python -m uvicorn app.main:app --port 8000 --app-dir backend` (from repo root)
   - Frontend: `npm run dev` (from `frontend/`)

2. Capture screenshots of the real app:
   `node scripts/capture-screenshots.mjs --serve`
   Output lands in `frontend/artifacts/screenshots/` with a `manifest.json`
   describing each shot and any console errors.

3. Delegate visual judgment to the vision-capable reviewer agent
   `crowdflow-visual-reviewer` (uses a GPT vision model). Give it the paths of
   the captured PNG files plus the relevant `manifest.json`. It returns a
   scored rubric, the top-3 highest-impact problems, and a verdict.

4. For each high-impact problem found, implement the fix in the codebase.

5. Re-run capture + review, compare against the previous state, and repeat
   until the reviewer's verdict is no longer BLOCKER.

Honesty rule: if the reviewer cannot actually interpret the images (e.g. it is
running on a text-only model), say so and do not claim visual verification.
$ARGUMENTS
