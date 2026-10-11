import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'placas.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # uploads de até 16 MB

    # Dados do recebedor PIX (usados no BR Code "copia e cola")
    PIX_KEY = os.environ.get("PIX_KEY", "pagamentos@exemplo.com.br")
    PIX_MERCHANT_NAME = os.environ.get("PIX_MERCHANT_NAME", "PLACAS PAGAMENTOS")
    PIX_MERCHANT_CITY = os.environ.get("PIX_MERCHANT_CITY", "SAO PAULO")

    SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "1") == "1"


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SEED_DEMO_DATA = False
