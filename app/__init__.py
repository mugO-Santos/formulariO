import os
from flask import Flask
from .extensions import db, login_manager
from .models import Usuario


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ── Configuração ──────────────────────────────────────────────
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///formulario.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # ── Extensões ─────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Faça login para acessar esta página."
    login_manager.login_message_category = "warning"

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
