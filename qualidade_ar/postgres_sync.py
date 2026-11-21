
import json
import logging
import os
import sqlite3
from contextlib import closing
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)


def preparar(sqlite_path):
    with closing(sqlite3.connect(sqlite_path, timeout=10)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS sync_metadata (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)')
        db.execute("INSERT OR IGNORE INTO sync_metadata VALUES ('origem', ?)", (str(uuid4()),))
       
        db.execute('''CREATE TABLE IF NOT EXISTS postgres_enviados (
            destino TEXT NOT NULL, consulta_id INTEGER NOT NULL,
            PRIMARY KEY (destino, consulta_id))''')


def sincronizar(sqlite_path, dsn=None):
    dsn = os.getenv('POSTGRES_DSN', '') if dsn is None else dsn
    if not dsn:
        return {'status': 'desativado', 'enviadas': 0}
    import hashlib
    destino = hashlib.sha256(dsn.encode()).hexdigest()
    preparar(sqlite_path)
    total = 0
    try:
        with closing(sqlite3.connect(sqlite_path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            origem = db.execute("SELECT valor FROM sync_metadata WHERE chave='origem'").fetchone()[0]
            with psycopg.connect(dsn, connect_timeout=3, options='-c statement_timeout=10000') as pg:
                pg.execute('''CREATE TABLE IF NOT EXISTS consultas (
                    origem UUID NOT NULL, sqlite_id BIGINT NOT NULL,
                    cidade TEXT NOT NULL, fonte TEXT NOT NULL,
                    consultado_em TIMESTAMPTZ NOT NULL, resposta_json JSONB NOT NULL,
                    sincronizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY(origem, sqlite_id))''')
                pg.execute('CREATE INDEX IF NOT EXISTS idx_consultas_cidade ON consultas(cidade, consultado_em DESC)')
        
            while True:
                rows = db.execute('''SELECT c.* FROM consultas c WHERE NOT EXISTS (
                    SELECT 1 FROM postgres_enviados e WHERE e.consulta_id=c.id AND e.destino=?)
                    ORDER BY c.id LIMIT 200''', (destino,)).fetchall()
                if not rows:
                    break
                with psycopg.connect(dsn, connect_timeout=3, options='-c statement_timeout=10000') as pg:
                    for row in rows:
                        pg.execute('''INSERT INTO consultas
                            (origem,sqlite_id,cidade,fonte,consultado_em,resposta_json)
                            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(origem,sqlite_id) DO NOTHING''',
                            (origem,row['id'],row['cidade'],row['fonte'],row['consultado_em'],
                             Jsonb(json.loads(row['resposta_json']))))
                with db:
                    db.executemany('INSERT OR IGNORE INTO postgres_enviados VALUES (?,?)',
                                   [(destino,row['id']) for row in rows])
                total += len(rows)
        return {'status': 'sincronizado', 'enviadas': total}
    except (psycopg.Error, sqlite3.Error, ValueError):
     
        log.warning('Sincronização PostgreSQL pendente; dados preservados no SQLite.')
        return {'status': 'pendente', 'enviadas': total}


if __name__ == '__main__':
    from pathlib import Path
    from dotenv import load_dotenv
    base = Path(__file__).resolve().parent
    load_dotenv(base / '.env')
    result = sincronizar(os.getenv('DB_PATH', str(base / 'qualidade_ar.db')))
    print(json.dumps(result))
    raise SystemExit(1 if result['status'] == 'pendente' else 0)
