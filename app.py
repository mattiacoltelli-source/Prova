"""Entrypoint per avviare la Web Dashboard Android / PWA."""
import os
from src.web_app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Avvio Dashboard su http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)
