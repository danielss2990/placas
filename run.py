"""Inicia o servidor.

    python run.py                 # http://0.0.0.0:5000
    python run.py --https         # HTTPS autoassinado (câmera ao vivo no celular)
"""
import argparse

from app import create_app

app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--https", action="store_true",
                        help="usa certificado autoassinado (requer 'pip install cryptography')")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug,
            ssl_context="adhoc" if args.https else None)
