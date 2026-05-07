from sqlalchemy import and_, or_

from .extensions import db
from .models import Log, Medico, Paciente, Usuario


def clinica_escopo_id(usuario):
    if usuario is None or usuario.acesso_global:
        return None
    return usuario.clinica_id


def filtro_paciente_clinica(clinica_id):
    return or_(
        Paciente.clinica_id == clinica_id,
        and_(
            Paciente.clinica_id.is_(None),
            Paciente.medico.has(Medico.clinica_id == clinica_id),
        ),
    )


def scoped_pacientes(query, usuario):
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return query.filter(filtro_paciente_clinica(clinica_id))


def scoped_medicos(query, usuario):
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return query.filter(Medico.clinica_id == clinica_id)


def scoped_usuarios(query, usuario):
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return query.filter(Usuario.clinica_id == clinica_id)


def scoped_logs(query, usuario):
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return query
    return (
        query.outerjoin(Log.usuario)
        .outerjoin(Log.paciente)
        .filter(
            or_(
                Usuario.clinica_id == clinica_id,
                filtro_paciente_clinica(clinica_id),
            )
        )
    )


def pode_acessar_medico(usuario, medico):
    clinica_id = clinica_escopo_id(usuario)
    return clinica_id is None or medico.clinica_id == clinica_id


def pode_acessar_usuario(usuario, alvo):
    clinica_id = clinica_escopo_id(usuario)
    return clinica_id is None or alvo.clinica_id == clinica_id


def pode_acessar_paciente(usuario, paciente):
    clinica_id = clinica_escopo_id(usuario)
    if clinica_id is None:
        return True
    paciente_clinica_id = paciente.clinica_id or (paciente.medico.clinica_id if paciente.medico else None)
    return paciente_clinica_id == clinica_id


def sincronizar_clinica_pacientes_do_medico(medico):
    db.session.query(Paciente).filter(Paciente.medico_id == medico.id).update(
        {Paciente.clinica_id: medico.clinica_id},
        synchronize_session=False,
    )