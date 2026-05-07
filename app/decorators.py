from functools import wraps
from flask import abort
from flask_login import current_user


def nivel_minimo(nivel: int):
    """Decorator que exige nível de acesso mínimo."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or current_user.nivel > nivel:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def superadmin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            abort(403)
        return f(*args, **kwargs)

    return wrapped
