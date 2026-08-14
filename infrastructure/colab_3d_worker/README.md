# CrowdFlow Colab 3D Worker

Standalone remote GPU inference service for the **AI 3D Digital Twin** feature.
The CrowdFlow backend (`Colab3DProvider`) submits a blueprint image; this worker
produces the twin artifacts and serves them back:

| Artifact | Purpose |
| --- | --- |
| `venue.glb` | binary glTF 2.0 3D model (world frame matches the frontend renderer) |
| `semantic.json` | `crowdflow.twin.semantic.v1` venue graph (gates, exits, zones, paths) |
| `generation.metadata.json` | provenance / model / adapter / notes |

The worker is **self-contained** (no CrowdFlow backend imports) so it runs on a
Google Colab GPU with nothing but this directory.

## HTTP contract

| Endpoint | Body / returns |
| --- | --- |
| `GET /health` | `{status, models, default_model, active_jobs}` |
| `POST /jobs` | multipart `file` (blueprint), `job_id`, `model`, `params` → `{id, status}` |
| `GET /jobs/{id}` | `{id, status, stage, progress, message, error, provenance, model, adapter}` |
| `POST /jobs/{id}/cancel` | cancels the background task |
| `GET /jobs/{id}/artifacts/{name}` | `venue.glb` / `semantic.json` / `generation.metadata.json` |

Status values: `QUEUED | RUNNING | COMPLETE | FAILED | CANCELLED`. Stage names
(`ANALYZING`, `GENERATING_GEOMETRY`, …) map 1:1 onto the backend's
`_map_worker_stage`.

## Auth (optional)

No API key is required by default — the ngrok tunnel URL is the credential.
To add a shared secret: set `WORKER_API_KEY` on the Colab side and mirror it as
`TWIN_COLAB_API_KEY` on the backend (sent as `X-API-Key`). Every endpoint
returns 401 when a key is configured and the header is missing.

ngrok free tunnels return an HTML browser-warning page for any request that
does not carry the `ngrok-skip-browser-warning` header. The CrowdFlow backend
always sends it, so no extra configuration is needed there.

## Honest provenance

A completed job reports its **true** provenance:

- `AI` — a real 3D model produced the geometry:
  - **Hunyuan3D-2mini** — in-process GPU model via `hy3dgen`; auto-detected by
    import and used by default. Runs on the free Colab T4 (~6 GB VRAM for shape).
  - **TRELLIS** — NOT usable on Colab as of 2026: it pins `torch==2.4.0+cu121`,
    whose `nvidia-cudnn-cu12==9.1.0.70` dependency was removed from the PyTorch
    index, so the runtime keeps a newer torch and Kaolin's `_C.so` crashes with
    an ABI mismatch. The adapter remains for local setups that can build it.
  - **Tripo / Meshy** — hosted REST APIs; enabled with `TRIPO_API_KEY` /
    `MESHY_API_KEY`. The caller then ships the GLB in the semantic world frame.
- `PROCEDURAL` — the deterministic generator ran (no AI available on this
  instance). The backend stamps the job + venue + UI badge accordingly, so an
  AI label is never fabricated.

## Run locally (development / tests)

```bash
pip install -r requirements.txt
uvicorn worker:app --port 8097
curl http://127.0.0.1:8097/health
```

Point the backend at it:

```bash
TWIN_PROVIDER=colab
TWIN_COLAB_URL=http://127.0.0.1:8097
TWIN_COLAB_MODEL=hunyuan3d        # any key from /health/models
TWIN_COLAB_POLL_S=1
```

## Run on Google Colab

1. Upload `infrastructure/colab_3d_worker/` to the runtime.
2. Open `colab_worker.ipynb` and run cells 1→5 (installs `hy3dgen` / Hunyuan3D,
   starts the server on port 8097, prints an ngrok/cloudflared public URL).
3. Set `TWIN_COLAB_URL=<public url>` on the CrowdFlow backend and reload it.

The worker never blocks CrowdFlow: the backend creates the twin job instantly
and polls this service; if the worker is offline the job fails cleanly and the
app keeps working (see `TWIN_PROVIDER=procedural` for the offline fallback).

## Tests

```bash
python -m pytest tests -q
```

The contract test boots the worker on an ephemeral port and runs a full job
(submit → poll → download → validate GLB + semantic → provenance honesty).