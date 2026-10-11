import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import create_app  # noqa: E402
from app.config import TestConfig  # noqa: E402
from app.models import db  # noqa: E402


class StubOcr:
    """OCR falso: devolve um texto fixo (permite testar a API sem Tesseract)."""

    def __init__(self, text="BRASIL\nBRA2E19"):
        self.text = text

    def __call__(self, image):
        return self.text


@pytest.fixture
def app():
    app = create_app(TestConfig, ocr_engine=StubOcr())
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
