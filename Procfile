release: python -c "from app import create_app; app = create_app()" && python db_migrations.py
web: gunicorn run:app
