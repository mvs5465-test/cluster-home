# Cluster Home

## Scope
- Lightweight Flask dashboard for human-friendly cluster entry points.
- Keep the app generic; cluster-specific links should live in the deploying repo through Helm values, not hardcoded here.

## Local Development
- Use the existing virtualenv at `.venv` when available.
- For normal local runs:
  - `.venv/bin/python app.py`
- For UI iteration with auto-reload:
  - `.venv/bin/python -m flask --app app:create_app --debug run --host 0.0.0.0 --port 8080`

## App Rules
- Preserve the current server-rendered Flask approach unless a larger architecture change is explicitly requested.
- Prefer editing `templates/home.html` and `static/styles.css` directly for UI work.
- Keep dependencies minimal and avoid adding client-side build tooling unless there is a clear need.
- The `Cluster Status` panel must degrade cleanly outside Kubernetes.

## Config And Deploy
- Keep the built-in `config/services.json` generic sample data only.
- Cluster-specific link sets should come from Helm `config.inlineJson` in the deploying repo.
- The chart owns the optional `ServiceAccount` and read-only RBAC used for live cluster info.

## Helm And Releases
- If a PR changes anything under `chart/`, bump `chart/Chart.yaml` `version` in the same PR.
- Bump `appVersion` when the deployed application behavior materially changes.
- Treat chart and app versions as release metadata, not deployment selectors; ArgoCD deploys from `main`.
- Use loose semver tracking:
  - bump `version` for chart changes, usually patch unless the chart interface changes materially
  - bump `appVersion` for meaningful app changes, including UI, config, or behavior changes
  - keeping `version` and `appVersion` aligned is acceptable when that is the simplest honest representation
- Keep chart defaults generic and push environment-specific overrides into the ArgoCD app manifest.

## Verification
- Run `python -m unittest discover -s tests` for app changes.
- Run `helm template cluster-home ./chart` for chart changes.
- For UI changes, verify the page locally in a browser before opening a PR.
