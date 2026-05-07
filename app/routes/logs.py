from flask import Blueprint, render_template
from flask_login import current_user, login_required
from app.models import Log
from app.decorators import superadmin_required
from app.scope import scoped_logs

bp = Blueprint("logs", __name__, url_prefix="/painel/logs")


@bp.route("/")
@login_required
@superadmin_required
def index():
    logs = scoped_logs(Log.query, current_user).order_by(Log.criado_em.desc()).limit(500).all()
    return render_template("painel/logs.html", logs=logs)
