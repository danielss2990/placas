from flask import Blueprint, render_template, send_from_directory, current_app

web = Blueprint("web", __name__)


@web.get("/")
def index():
    return render_template("index.html")


@web.get("/manifest.webmanifest")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.webmanifest",
                               mimetype="application/manifest+json")


@web.get("/sw.js")
def service_worker():
    # Servido na raiz para que o service worker controle todo o app.
    resp = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp
