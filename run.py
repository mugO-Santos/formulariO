import os
from pathlib import Path


def _is_railway_runtime():
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"))


def _load_local_dotenv_if_available():
    if _is_railway_runtime():
        return

    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return

    try:
        from dotenv import load_dotenv
    except Exception:
        return

    load_dotenv(dotenv_path=env_file, override=False)


_load_local_dotenv_if_available()

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
