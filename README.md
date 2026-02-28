# Cluster Home

A lightweight dark-themed home dashboard for the local Kubernetes cluster.

## Features

- Fast server-rendered dashboard
- Dark-mode card layout
- Generic default config with support for external per-cluster config
- One-container deployment with a bundled Helm chart

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The app listens on `http://127.0.0.1:8080`.

## Kubernetes

The Helm chart lives in `chart/`. The default service listens on port `80` and forwards to the app on `8080`.

To provide cluster-specific links from the deploying repo, set `config.inlineJson` in Helm values:

```yaml
config:
  inlineJson: |
    {
      "title": "My Cluster",
      "subtitle": "Links for my environment",
      "groups": []
    }
```
