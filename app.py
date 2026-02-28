import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template


DEFAULT_CONFIG = Path(__file__).parent / "config" / "services.json"


def load_config(path: str | None = None) -> dict:
    requested_path = path or os.environ.get("HOME_CONFIG_PATH")
    config_path = Path(requested_path) if requested_path else DEFAULT_CONFIG
    if not config_path.exists():
        config_path = DEFAULT_CONFIG
    with config_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(SITE_CONFIG=load_config())

    if test_config:
        app.config.update(test_config)

    @app.get("/")
    def home():
        config = app.config["SITE_CONFIG"]
        groups = config.get("groups", [])
        link_count = sum(len(group.get("items", [])) for group in groups)
        return render_template(
            "home.html",
            title=config.get("title", "Cluster Home"),
            subtitle=config.get("subtitle", ""),
            groups=groups,
            link_count=link_count,
        )

    @app.get("/health")
    def health():
        config = app.config["SITE_CONFIG"]
        group_count = len(config.get("groups", []))
        link_count = sum(len(group.get("items", [])) for group in config.get("groups", []))
        return jsonify(
            {
                "status": "ok",
                "groups": group_count,
                "links": link_count,
            }
        )

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
