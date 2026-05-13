#!/usr/bin/env python
"""
Database migration script to add performance indexes.
Applies to both SQLite (development) and PostgreSQL (production).
Run this after updating models but before deploying.
"""

from app import create_app, db
from sqlalchemy import text, inspect


def add_usuario_clinicas():
    """Create usuario_clinicas many-to-many table and populate from existing clinica_id."""
    app = create_app()

    with app.app_context():
        inspector = inspect(db.engine)
        db_dialect = db.engine.dialect.name
        print(f"Database dialect: {db_dialect}")
        print("=" * 60)

        if "usuario_clinicas" in inspector.get_table_names():
            print("✓ Table 'usuario_clinicas' already exists, skipping creation.")
        else:
            create_sql = """
                CREATE TABLE usuario_clinicas (
                    usuario_id INTEGER NOT NULL,
                    clinica_id INTEGER NOT NULL,
                    PRIMARY KEY (usuario_id, clinica_id),
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id),
                    FOREIGN KEY (clinica_id) REFERENCES clinicas(id)
                )
            """
            db.session.execute(text(create_sql))
            db.session.commit()
            print("✓ Table 'usuario_clinicas' created.")

        # Populate from existing clinica_id (skip duplicates)
        rows = db.session.execute(
            text("SELECT id, clinica_id FROM usuarios WHERE clinica_id IS NOT NULL")
        ).fetchall()

        inserted = 0
        for usuario_id, clinica_id in rows:
            exists = db.session.execute(
                text("SELECT 1 FROM usuario_clinicas WHERE usuario_id=:u AND clinica_id=:c"),
                {"u": usuario_id, "c": clinica_id},
            ).fetchone()
            if not exists:
                db.session.execute(
                    text("INSERT INTO usuario_clinicas (usuario_id, clinica_id) VALUES (:u, :c)"),
                    {"u": usuario_id, "c": clinica_id},
                )
                inserted += 1

        db.session.commit()
        print(f"✓ Populated {inserted} existing user→clinic links from clinica_id column.")
        print("=" * 60)


def add_indexes():
    """Add performance indexes to frequently queried columns."""
    app = create_app()
    
    with app.app_context():
        inspector = inspect(db.engine)
        db_dialect = db.engine.dialect.name
        
        print(f"Database dialect: {db_dialect}")
        print("=" * 60)
        
        # Define indexes: (table, column(s), index_name, is_composite)
        indexes = [
            # Paciente table - HIGH PRIORITY
            ("pacientes", ["clinica_id"], "idx_pacientes_clinica_id", False),
            ("pacientes", ["medico_id"], "idx_pacientes_medico_id", False),
            ("pacientes", ["concluido_em"], "idx_pacientes_concluido_em", False),
            ("pacientes", ["excluido_em"], "idx_pacientes_excluido_em", False),
            
            # Log table - HIGH PRIORITY (header notification count + logs view)
            ("logs", ["criado_em"], "idx_logs_criado_em", False),
            ("logs", ["usuario_id"], "idx_logs_usuario_id", False),
            ("logs", ["usuario_id", "criado_em"], "idx_logs_usuario_criado", True),
            
            # Agendamento table
            ("agendamentos", ["clinica_id"], "idx_agendamentos_clinica_id", False),
            ("agendamentos", ["paciente_id"], "idx_agendamentos_paciente_id", False),
            ("agendamentos", ["status"], "idx_agendamentos_status", False),
            ("agendamentos", ["clinica_id", "status"], "idx_agendamentos_clinica_status", True),
            
            # Notificacao table - HIGH PRIORITY (unread count)
            ("notificacoes", ["usuario_id"], "idx_notificacoes_usuario_id", False),
            ("notificacoes", ["usuario_id", "lida"], "idx_notificacoes_usuario_lida", True),
            
            # Medico table
            ("medicos", ["clinica_id"], "idx_medicos_clinica_id", False),
            
            # Usuario table
            ("usuarios", ["clinica_id"], "idx_usuarios_clinica_id", False),
            
            # Encaminhamento table
            ("encaminhamentos", ["paciente_id"], "idx_encaminhamentos_paciente_id", False),
            ("encaminhamentos", ["clinica_destino_id"], "idx_encaminhamentos_clinica_destino_id", False),
        ]
        
        created_count = 0
        skipped_count = 0
        
        for table_name, columns, index_name, is_composite in indexes:
            # Check if table exists
            if table_name not in inspector.get_table_names():
                print(f"⚠️  Table '{table_name}' does not exist, skipping index '{index_name}'")
                continue
            
            # Check if all columns exist
            table_columns = [col["name"] for col in inspector.get_columns(table_name)]
            if not all(col in table_columns for col in columns):
                missing = [col for col in columns if col not in table_columns]
                print(f"⚠️  Column(s) {missing} not found in '{table_name}', skipping index '{index_name}'")
                continue
            
            # Check if index already exists
            existing_indexes = inspector.get_indexes(table_name)
            existing_index_names = {idx["name"] for idx in existing_indexes}
            
            if index_name in existing_index_names:
                print(f"✓ Index '{index_name}' already exists on {table_name}({', '.join(columns)})")
                skipped_count += 1
                continue
            
            # Build CREATE INDEX statement
            columns_str = ", ".join(columns)
            create_index_sql = f"CREATE INDEX {index_name} ON {table_name} ({columns_str})"
            
            try:
                db.session.execute(text(create_index_sql))
                db.session.commit()
                print(f"✓ Created index '{index_name}' on {table_name}({columns_str})")
                created_count += 1
            except Exception as e:
                print(f"✗ Failed to create index '{index_name}': {str(e)}")
                db.session.rollback()
        
        print("=" * 60)
        print(f"Results: {created_count} indexes created, {skipped_count} already existed")
        print("\nIndexing complete! Your database is now optimized for frequent queries.")
        print("Expected improvements:")
        print("  • Faster patient list filtering by clinic/doctor")
        print("  • Faster logs retrieval and ordering")
        print("  • Faster notification queries (header count)")
        print("  • Faster appointment filtering by status/clinic")


def verify_indexes():
    """Verify that indexes are properly created and being used."""
    app = create_app()
    
    with app.app_context():
        inspector = inspect(db.engine)
        db_dialect = db.engine.dialect.name
        
        print("\n" + "=" * 60)
        print("INDEX VERIFICATION REPORT")
        print("=" * 60)
        
        tables_to_check = [
            "pacientes",
            "logs",
            "agendamentos",
            "notificacoes",
            "medicos",
            "usuarios",
            "encaminhamentos",
        ]
        
        for table_name in tables_to_check:
            if table_name not in inspector.get_table_names():
                continue
            
            indexes = inspector.get_indexes(table_name)
            if indexes:
                print(f"\n📊 Table: {table_name}")
                for idx in indexes:
                    columns = ", ".join(idx["column_names"])
                    unique = " (UNIQUE)" if idx.get("unique", False) else ""
                    print(f"   • {idx['name']}: ({columns}){unique}")
            else:
                print(f"\n📊 Table: {table_name} - No indexes found")


if __name__ == "__main__":
    import sys
    
    print("📦 Database Migration: Adding Performance Indexes + usuario_clinicas table")
    print()
    
    try:
        add_usuario_clinicas()
        add_indexes()
        verify_indexes()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
