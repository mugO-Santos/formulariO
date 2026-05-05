import os
import re
import ssl
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Flask
from sqlalchemy import inspect, text
from .extensions import db, login_manager
from .models import Usuario

SP = ZoneInfo("America/Sao_Paulo")


def _fmt_sp(dt, fmt="%d/%m/%Y %H:%M"):
    """Converte datetime UTC → horário de São Paulo e formata."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SP).strftime(fmt)


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ── Configuração ──────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    _db_url = os.environ.get("DATABASE_URL", "sqlite:///formulario.db")
    _engine_options = {}

    # pg8000 requires postgresql+pg8000:// dialect prefix
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif _db_url.startswith("postgresql://"):
        _db_url = _db_url.replace("postgresql://", "postgresql+pg8000://", 1)

    # pg8000 não aceita sslmode/channel_binding na URL; usa ssl_context separadamente
    if "postgresql+pg8000://" in _db_url:
        _db_url = re.sub(r"[?&]sslmode=[^&]*", "", _db_url)
        _db_url = re.sub(r"[?&]channel_binding=[^&]*", "", _db_url)
        _db_url = re.sub(r"\?&", "?", _db_url).rstrip("?").rstrip("&")
        _engine_options["connect_args"] = {"ssl_context": ssl.create_default_context()}

    app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    if _engine_options:
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = _engine_options

    # ── Extensões ─────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar esta página."
    login_manager.login_message_category = "warning"

    app.jinja_env.filters["horario_sp"] = _fmt_sp

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Usuario, int(user_id))

    # ── Blueprints ────────────────────────────────────────────────
    from .routes.formulario import bp as formulario_bp
    from .routes.auth import bp as auth_bp
    from .routes.painel import bp as painel_bp
    from .routes.medicos import bp as medicos_bp
    from .routes.usuarios import bp as usuarios_bp
    from .routes.logs import bp as logs_bp

    app.register_blueprint(formulario_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(painel_bp)
    app.register_blueprint(medicos_bp)
    app.register_blueprint(usuarios_bp)
    app.register_blueprint(logs_bp)

    # ── Criação do banco e seed do Admin ──────────────────────────
    with app.app_context():
        db.create_all()
        _ensure_runtime_schema_updates()
        _seed_admin()

    return app


def _seed_admin():
    """Cria o admin e os cargos padrão na primeira execução."""
    from .models import Cargo, Usuario
    from werkzeug.security import generate_password_hash

    cargos_padrao = [
        {"nome": "Admin", "nivel": 0},
        {"nome": "Gestão", "nivel": 1},
        {"nome": "Recepção", "nivel": 2},
    ]
    for c in cargos_padrao:
        if not Cargo.query.filter_by(nome=c["nome"]).first():
            db.session.add(Cargo(nome=c["nome"], nivel=c["nivel"]))
    db.session.commit()

    admin_nome = os.environ.get("ADMIN_USER", "admin")
    admin_senha = os.environ.get("ADMIN_PASS", "admin123")

    if not Usuario.query.filter_by(nome=admin_nome).first():
        cargo_admin = Cargo.query.filter_by(nivel=0).first()
        db.session.add(
            Usuario(
                nome=admin_nome,
                senha_hash=generate_password_hash(admin_senha),
                cargo_id=cargo_admin.id,
            )
        )
        db.session.commit()


def _ensure_runtime_schema_updates():
    """Aplicar ajustes simples de schema em bancos já existentes."""
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()

    if "pacientes" in table_names:
        colunas_pacientes = {col["name"] for col in inspector.get_columns("pacientes")}
        if "concluido_em" not in colunas_pacientes:
            try:
                db.session.execute(text("ALTER TABLE pacientes ADD COLUMN concluido_em TIMESTAMP"))
                db.session.commit()
            except Exception:
                db.session.rollback()
