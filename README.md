# Cluster Home

A lightweight dark-themed home dashboard for the local Kubernetes cluster.

## Features

- Fast server-rendered dashboard
- Dark-mode card layout
- Built-in links for the human-facing cluster services
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
