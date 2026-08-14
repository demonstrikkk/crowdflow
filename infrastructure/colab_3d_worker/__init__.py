"""CrowdFlow Colab 3D worker — standalone remote GPU inference service.

Contract with the CrowdFlow backend (``Colab3DProvider``):

    GET  /health                          -> 200 when the worker is alive
    POST /jobs                            -> multipart {job_id, model, params, input}
    GET  /jobs/{id}                       -> {id, status, stage, progress, message, error, provenance, model}
    POST /jobs/{id}/cancel
    GET  /jobs/{id}/artifacts/{name}      -> venue.glb | semantic.json | generation.metadata.json | preview.png

The worker is fully self-contained so it can run inside a Google Colab runtime
with only a tunnel (ngrok/cloudflared). It never blocks on network calls from
CrowdFlow; the backend polls job status the same way it polls any provider.
"""