import json
import sqlite3
from contextlib import contextmanager

@contextmanager
def conectar(path):
    db = sqlite3.connect(path, timeout=10)
    try:
        with db:
            yield db
    finally:
        db.close()

def iniciar(path):
    with conectar(path) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS consultas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cidade TEXT NOT NULL,
            fonte TEXT NOT NULL, consultado_em TEXT NOT NULL, resposta_json TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_cidade_id ON consultas(cidade,id)')
        db.execute('''CREATE TABLE IF NOT EXISTS relatorios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cidade TEXT NOT NULL,
            bucket TEXT NOT NULL, chave TEXT NOT NULL, criado_em TEXT NOT NULL)''')

def salvar_consulta(path, cidade, fonte, quando, resposta):
    with conectar(path) as db:
        db.execute('INSERT INTO consultas(cidade,fonte,consultado_em,resposta_json) VALUES (?,?,?,?)',
                   (cidade,fonte,quando,resposta))

def historico(path, cidade, limite):
    with conectar(path) as db:
        rows=db.execute('SELECT resposta_json FROM consultas WHERE cidade=? ORDER BY id DESC LIMIT ?', (cidade,limite)).fetchall()
    return [json.loads(row[0]) for row in rows]

def salvar_relatorio(path,cidade,bucket,chave,quando):
    with conectar(path) as db:
        db.execute('INSERT INTO relatorios(cidade,bucket,chave,criado_em) VALUES (?,?,?,?)',(cidade,bucket,chave,quando))
