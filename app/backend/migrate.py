"""Migração aditiva da auditoria; --check apenas inspeciona, --apply altera o schema.

Nunca apaga dados ou resolve sobreposições existentes automaticamente.
"""
import argparse

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.backend.core.database import Base, engine
from app.backend import models  # noqa: F401: registra metadados
from app.backend.models.horario import SQLITE_OVERLAP_TRIGGERS

REVISION = "20261113_audit"


def _preflight(conn: Connection) -> None:
    tables = set(inspect(conn).get_table_names())
    if "horarios" in tables:
        conflicts = conn.execute(text("""SELECT count(*) FROM horarios a JOIN horarios b
            ON a.id < b.id AND a.medico_id=b.medico_id AND a.data=b.data
            AND a.hora_inicio < b.hora_fim AND a.hora_fim > b.hora_inicio""")).scalar_one()
        if conflicts:
            raise RuntimeError("Há intervalos sobrepostos existentes; revise-os antes da migração (nenhum dado foi apagado)")
        from datetime import date, time
        for day, start, end in conn.execute(text("SELECT data, hora_inicio, hora_fim FROM horarios")):
            try:
                valid = date.fromisoformat(day).isoformat() == day and time.fromisoformat(start) < time.fromisoformat(end)
                valid = valid and len(start) == 5 and len(end) == 5
            except (ValueError, TypeError):
                valid = False
            if not valid:
                raise RuntimeError("Há datas/intervalos inválidos na agenda; corrija-os antes da migração")
    if "usuarios" in tables:
        duplicates = conn.execute(text("SELECT lower(email) FROM usuarios GROUP BY lower(email) HAVING count(*)>1 LIMIT 1")).first()
        if duplicates:
            raise RuntimeError("Há e-mails duplicados sem considerar caixa; revise-os antes da migração")


def upgrade(target: Engine, *, apply: bool = False) -> None:
    with target.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            if apply:
                conn.execute(text("SELECT pg_advisory_xact_lock(71029042)"))
                tables = set(inspect(conn).get_table_names())
                existing = [name for name in ("usuarios", "medicos", "horarios") if name in tables]
                if existing:
                    conn.execute(text("LOCK TABLE " + ", ".join(existing) + " IN SHARE ROW EXCLUSIVE MODE"))
        _preflight(conn)
        if not apply:
            return
        tables = set(inspect(conn).get_table_names())
        for table in ("usuarios", "medicos"):
            if table not in tables:
                continue
            columns = {column["name"] for column in inspect(conn).get_columns(table)}
            if "ativo" not in columns:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN ativo BOOLEAN NOT NULL DEFAULT TRUE"))
            if table == "usuarios" and "token_version" not in columns:
                conn.execute(text("ALTER TABLE usuarios ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"))
        Base.metadata.create_all(bind=conn)
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_usuarios_email_lower ON usuarios (lower(email))"))
        if conn.dialect.name == "postgresql":
            conn.execute(text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ex_horario_sem_sobreposicao' AND conrelid='horarios'::regclass) THEN
                    ALTER TABLE horarios ADD CONSTRAINT ex_horario_sem_sobreposicao EXCLUDE USING gist
                    (medico_id WITH =, data WITH =,
                     int4range((substring(hora_inicio,1,2)::int*60+substring(hora_inicio,4,2)::int),
                     (substring(hora_fim,1,2)::int*60+substring(hora_fim,4,2)::int),'[)') WITH &&);
                END IF;
            END $$"""))
        elif conn.dialect.name == "sqlite":
            for trigger in SQLITE_OVERLAP_TRIGGERS:
                conn.execute(text(trigger))
        else:
            raise RuntimeError("Migração suportada somente em PostgreSQL ou SQLite de teste")
        conn.execute(text("CREATE TABLE IF NOT EXISTS app_schema_revisions (revision VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO app_schema_revisions (revision) VALUES (:revision) ON CONFLICT DO NOTHING"), {"revision": REVISION})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        upgrade(engine, apply=args.apply)
    except Exception as exc:
        # SQLAlchemy pode incluir parâmetros/URLs na exceção; não os exibe.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        raise SystemExit("Migração interrompida: " + message) from None
    print("Migração aplicada sem remoção de dados." if args.apply else "Pré-verificação concluída; nenhuma alteração. Use --apply após backup.")


if __name__ == "__main__":
    main()
