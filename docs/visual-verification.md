# CrowdFlow Visual Verification Loop

CrowdFlow's core value is a **living digital twin** that must be *seen* and
*felt*, not just functionally correct. Source code and DOM inspection cannot
judge spatial believability, crowd liveliness, hierarchy, or 3D coherence.
This loop verifies the **rendered application** with a vision-capable model.

## Actors

| Role | Model | Purpose |
| ---- | ----- | ------- |
| Builder | DeepSeek (text-only) | Code, backend, simulation, fixes |
| Reviewer | `crowdflow-visual-reviewer` (GPT vision) | Judges screenshots against the product rubric |

The reviewer agent is defined at `.opencode/agent/crowdflow-visual-reviewer.md`
and runs on `openai/gpt-5.1-codex` (image-capable). It must **not** be asked to
inspect the codebase — only screenshots + minimal context.

## The loop

```
start servers → capture screenshots → reviewer judges → fix top-3 → re-capture → compare → repeat
```

### 1. Start servers
- Backend: `python -m uvicorn app.main:app --port 8000 --app-dir backend` (repo root)
- Frontend: `npm run dev` (in `frontend/`)

### 2. Capture
```bash
cd frontend
node scripts/capture-screenshots.mjs --serve      # also starts servers if down
```
Writes PNGs + `manifest.json` to `frontend/artifacts/screenshots/`. The walker
drives the P0 flow: open → start event → live crowd → 2.5D → bottleneck →
density → final.

### 3. Review
Open the `crowdflow-visual-reviewer` agent and point it at the PNG paths +
`manifest.json`. It returns a scored rubric, top-3 impactful problems, and a
verdict (BLOCKER / IMPROVE / OK).

### 4. Fix + repeat
Implement the top fixes in code, re-capture, and compare. Stop when verdict is
no longer BLOCKER.

## One-shot
Run the whole thing as a command: `/visual-verify`

## Honesty rule
- The **Builder (DeepSeek) is text-only** and cannot judge images. It must not
  claim visual verification.
- Only the **Reviewer** (vision model) issues visual verdicts.
- If a claim can't be seen in the screenshots (e.g. no before/after pair), the
  reviewer marks it **unverified**, not passed.

## Requirements
- `playwright` devDependency (installed).
- A browser: script auto-uses system **Chrome**/Edge first; otherwise
  `npx playwright install chromium` once.
