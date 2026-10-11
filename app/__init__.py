from pathlib import Path

from flask import Flask

from .config import Config
from .models import db


def create_app(config_object=Config, ocr_engine=None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from .recognition import PlateRecognizer
    app.extensions["plate_recognizer"] = PlateRecognizer(ocr_engine)

    from .api import api
    from .web import web
    app.register_blueprint(api, url_prefix="/api")
    app.register_blueprint(web)

    with app.app_context():
        db.create_all()
        if app.config.get("SEED_DEMO_DATA"):
            from .seed import seed_demo_data
            seed_demo_data()

    return app
