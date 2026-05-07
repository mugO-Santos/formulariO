import os
import re
import ssl
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from flask import Flask
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from .extensions import db, login_manager
from .models import Usuario

try:
    SP = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:
    # Fallback para ambientes Windows sem base de timezones instalada.
    SP = timezone.utc


def _fmt_sp(dt, fmt="%d/%m/%Y %H:%M"):
    """Converte datetime UTC → horário de São Paulo e formata."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SP).strftime(fmt)


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    @app.get("/favicon.ico")
    def favicon():
        return ("", 204)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}, 200

    # ── Configuração ──────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    _db_url = os.environ.get("DATABASE_URL", "sqlite:///formulario.db")
    _engine_options = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "300")),
        "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", "30")),
    }

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

    if not app.debug:
        app.logger.setLevel(logging.INFO)

    def log_sqlalchemy_error(exception_context):
        app.logger.exception(
            "Erro de banco durante a requisicao.",
            exc_info=exception_context.original_exception,
        )

    @app.teardown_request
    def rollback_failed_transaction(exception=None):
        if exception is None:
            return
        try:
            db.session.rollback()
        except SQLAlchemyError:
            app.logger.exception("Falha ao desfazer transacao apos erro na requisicao.")

    @login_manager.user_loader
    def load_user(user_id):
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None

        for tentativa in range(2):
            try:
                usuario = db.session.get(Usuario, uid)
                if usuario and not usuario.ativo:
                    return None
                return usuario
            except SQLAlchemyError:
                db.session.rollback()
                db.session.remove()
                app.logger.warning(
                    "Falha ao carregar usuario da sessao. tentativa=%s",
                    tentativa + 1,
                    exc_info=True,
                )
                if tentativa == 0:
                    continue
        return None

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
        if not event.contains(db.engine, "handle_error", log_sqlalchemy_error):
            event.listen(db.engine, "handle_error", log_sqlalchemy_error)
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
                is_superadmin=True,
            )
        )
        db.session.commit()

    admin = Usuario.query.filter_by(nome=admin_nome).first()
    if admin and not admin.is_superadmin:
        admin.is_superadmin = True
        db.session.commit()


def _ensure_runtime_schema_updates():
    """Aplicar ajustes simples de schema em bancos já existentes."""
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()

    if "clinicas" not in table_names:
        return

    _ensure_column(inspector, "usuarios", "clinica_id", "INTEGER")
    _ensure_column(inspector, "usuarios", "is_superadmin", "BOOLEAN DEFAULT FALSE")
    _ensure_column(inspector, "medicos", "clinica_id", "INTEGER")
    _ensure_column(inspector, "pacientes", "clinica_id", "INTEGER")
    _ensure_column(inspector, "clinicas", "medico_responsavel_id", "INTEGER")
    _ensure_column(inspector, "clinicas", "eh_hospital", "BOOLEAN DEFAULT FALSE")

    if "pacientes" in table_names:
        colunas_pacientes = {col["name"] for col in inspector.get_columns("pacientes")}
        if "concluido_em" not in colunas_pacientes:
            try:
                db.session.execute(text("ALTER TABLE pacientes ADD COLUMN concluido_em TIMESTAMP"))
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                raise RuntimeError(
                    "Falha ao criar coluna 'concluido_em' na tabela 'pacientes'."
                ) from exc


def _ensure_column(inspector, table_name, column_name, column_sql):
    if table_name not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
    if column_name in existing_columns:
        return

    try:
        db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        raise RuntimeError(
            f"Falha ao criar coluna '{column_name}' na tabela '{table_name}'."
        ) from exc
