import sqlite3
from contextlib import closing
import psycopg
import postgres_sync


def test_indisponivel_preserva_dados(tmp_path, monkeypatch):
    path = tmp_path / 'local.db'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE consultas (id INTEGER PRIMARY KEY, cidade TEXT, fonte TEXT, consultado_em TEXT, resposta_json TEXT)')
        db.execute("INSERT INTO consultas VALUES (1,'itajai','mock','2026-11-21T12:00:00Z','{}')")
    def fail(*args, **kwargs):
        raise psycopg.OperationalError('indisponível')
    monkeypatch.setattr(postgres_sync.psycopg, 'connect', fail)
    assert postgres_sync.sincronizar(path, 'host=invalid')['status'] == 'pendente'
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT count(*) FROM consultas').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM postgres_enviados').fetchone()[0] == 0


def test_origem_estavel(tmp_path):
    path = tmp_path / 'local.db'
    postgres_sync.preparar(path)
    with closing(sqlite3.connect(path)) as db:
        first = db.execute('SELECT valor FROM sync_metadata').fetchone()[0]
    postgres_sync.preparar(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT valor FROM sync_metadata').fetchone()[0] == first
    assert postgres_sync.sincronizar(path, '')['status'] == 'desativado'
