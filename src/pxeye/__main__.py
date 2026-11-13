"""PXEye process entry point."""

import argparse
import json
import os
from pathlib import Path
from http.server import ThreadingHTTPServer
from pxeye import __version__
from pxeye.bootstrap import Application

from pxeye.api.http import Handler


def main():
    parser = argparse.ArgumentParser(description="PXEye infrastructure operations console")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.parse_args()
    os.umask(0o077)
    config = json.loads(Path(os.environ.get("CONSOLE_CONFIG", "/config/site.json")).read_text())
    data_dir = Path(os.environ.get("CONSOLE_DATA", "/data"))
    config.setdefault(
        "site",
        {
            "name": "PXEye",
            "namespace": "nico-system",
            "deployment": "nico-system-pxeye",
        },
    )
    deployed_site = data_dir / "config" / "deployment-site.json"
    if deployed_site.exists():
        config.update(json.loads(deployed_site.read_text()))
    saved_site = data_dir / "config" / "site-settings.json"
    if saved_site.exists():
        saved = json.loads(saved_site.read_text())
        if isinstance(saved.get("name"), str) and isinstance(saved.get("core_url"), str):
            config["site"]["name"], config["core_url"] = saved["name"], saved["core_url"]
        concurrency = saved.get("default_install_concurrency", 5)
        if (
            isinstance(concurrency, int)
            and not isinstance(concurrency, bool)
            and 1 <= concurrency <= 50
        ):
            config["default_install_concurrency"] = concurrency
    config.setdefault("default_install_concurrency", 5)
    app = Application(
        config,
        os.environ.get("CONSOLE_SECRETS", "/secrets"),
        data_dir,
        os.environ.get("CONSOLE_STATIC", str(Path(__file__).with_name("web"))),
    )
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler)
    server.app = app
    server.serve_forever()


if __name__ == "__main__":
    main()
