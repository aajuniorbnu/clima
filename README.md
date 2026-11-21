# Monitor de Cidade Inteligente — Pessoa B

A Pessoa B mantém o serviço de qualidade do ar (porta 8081). A Pessoa A entrega clima (8001); a Pessoa C consulta ambos e produz alertas (8003).

## Responsabilidades e contrato

1. Acordar com C as rotas, campos, unidades, datas UTC e respostas de erro.
2. Consultar a OpenAQ v3 com chave guardada no servidor.
3. Associar cada cidade a uma estação de monitoramento verificada.
4. Normalizar os dados sem perder poluente, unidade, estação e horário da medição.
5. Persistir consultas no SQLite e disponibilizar histórico.
6. Disponibilizar mock explícito para os colegas e testar a integração.

| Rota | Função |
| --- | --- |
| GET /qualidade-ar?cidade=Itajai | Consulta, salva e retorna medições |
| GET /historico?cidade=Itajai&limite=20 | Últimas consultas salvas, máximo 100 |
| GET /saude | Status e modo de execução |
| GET /docs | Swagger gerado pelo FastAPI |

Resposta exemplificada (mock; datas ilustrativas):

```json
{
  "cidade": "Itajaí",
  "fonte": "mock",
  "estacao_id": null,
  "estacao_nome": "Estação fictícia para integração",
  "consultado_em": "2026-11-21T12:00:00Z",
  "medicoes": [
    {
      "sensor_id": 0,
      "poluente": "pm25",
      "valor": 12.0,
      "unidade": "µg/m³",
      "medido_em": "2026-11-21T12:00:00Z",
      "desatualizado": false
    }
  ]
}
```

Erros têm formato `{"detail": "mensagem"}`: 404 cidade desconhecida ou nenhuma medição válida; 422 parâmetros inválidos (detail é uma lista de validação); 502 falha externa; 503 configuração ausente ou limite externo; 504 timeout. C deve tratar erros como informação indisponível.

## Banco de dados

SQLite é suficiente para o trabalho e já vem no Python. O arquivo qualidade_ar/qualidade_ar.db e a tabela são criados ao iniciar o serviço:

```sql
CREATE TABLE consultas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cidade TEXT NOT NULL,
  fonte TEXT NOT NULL,
  consultado_em TEXT NOT NULL,
  resposta_json TEXT NOT NULL
);
CREATE INDEX idx_cidade_id ON consultas(cidade, id);
```

Cada linha é uma consulta bem-sucedida contendo todas as medições daquela resposta. Consultas repetidas geram novas linhas: é um histórico de consultas, não uma série de medições deduplicada. Falhas não são salvas. O JSON preserva unidades e horários individuais; mocks têm fonte distinta. O endpoint de histórico pode retornar ambas as fontes, identificadas por item. Não há cache nem atualização em segundo plano; /qualidade-ar busca a fonte a cada chamada. Para evolução, separar cidades, estações e medições em tabelas, deduplicar por sensor/data e adicionar cache e migrações.

## Executar

```bash
cd /Users/aajuniorbnu/Desktop/clima/qualidade_ar
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8081
```

Abra http://localhost:8081/docs. O mock de Itajaí funciona sem chave e sem conexão externa.

```bash
curl 'http://localhost:8081/qualidade-ar?cidade=Itajai'
curl 'http://localhost:8081/historico?cidade=Itajai&limite=5'
pytest -q
```

## Ativar a OpenAQ real

1. Crie uma chave em https://explore.openaq.org e coloque OPENAQ_API_KEY no .env.
2. Consulte GET https://api.openaq.org/v3/locations com o header X-API-Key; use os filtros geográficos documentados (coordinates e radius) e paginação para descobrir estações. Confira coordenadas, atividade, poluentes, provedor e licença. Não suponha cobertura para Itajaí: ela não foi verificada neste exemplo.
3. Substitua o null de estacao_id em cidades.json pelo ID de uma estação apropriada e verificada. Não use um ID aleatório ou de outra cidade para preencher a lacuna. Se não houver cobertura, mantenha indisponível e explique isso na apresentação.
4. Configure MODO_MOCK=false no .env e reinicie.

O serviço consulta /v3/locations/{id} para obter metadados dos sensores e /v3/locations/{id}/latest para os valores. Une ambos por sensorsId e preserva as unidades originais. Não inventa AQI: concentração de PM2.5 não é um índice AQI. Antes de disponibilizar dados publicamente, confira atribuição/licença do provedor da estação.

MAX_IDADE_HORAS=3 é uma regra técnica configurável do projeto, não um critério de saúde. Leituras antigas e datas mais de cinco minutos no futuro são sinalizadas. Valores negativos ou não finitos são descartados. Não há fallback silencioso para mock.

## Integração da Pessoa C

```python
import httpx

async def consultar_ar(cidade):
    async with httpx.AsyncClient(timeout=15) as client:
        resposta = await client.get(
            'http://localhost:8081/qualidade-ar', params={'cidade': cidade}
        )
        resposta.raise_for_status()
        return resposta.json()
```

C deve tratar RequestError/HTTPStatusError, rejeitar mock em uso real, verificar idade, unidades e presença dos poluentes exigidos antes de avaliar. Ausência de dados não significa ar bom. A regra sobre correr é responsabilidade de C e precisa de critério documentado, incluindo período de média; uma leitura isolada não substitui média diária nem permite automaticamente uma recomendação de saúde. Em Docker, localhost aponta para o próprio contêiner; use o nome do serviço, por exemplo http://qualidade-ar:8081.

## Arquivos

- qualidade_ar/main.py: modelos, integração, persistência e rotas.
- qualidade_ar/cidades.json: cadastro explícito de cidade/estação.
- qualidade_ar/.env.example: configuração inicial.
- qualidade_ar/requirements.txt: dependências.
- qualidade_ar/test_main.py: testes com banco temporário e OpenAQ simulada.

## Referências

- https://docs.openaq.org/using-the-api/api-key
- https://docs.openaq.org/resources/locations
- https://docs.openaq.org/resources/latest
- https://api.openaq.org/docs

Este é um MVP didático. A integração ao vivo depende de chave e cobertura verificadas; os testes automatizados simulam a OpenAQ.

## Acesso público com ngrok

Com a API rodando na porta 8081, abra outro terminal:

```bash
ngrok http 8081
```

Use o endereço HTTPS exibido pelo ngrok como URL base da Pessoa B. Por exemplo, a Pessoa C chama `https://SEU-DOMINIO.ngrok-free.app/qualidade-ar?cidade=Itajai`. O Swagger está em `/docs`. Mantenha os dois processos em execução para manter o acesso público. A API continua usando o modo definido no .env (mock por padrão).

## Frontend

Abra http://localhost:8081/ ou a URL pública do ngrok para acessar o painel Atmosfera. HTML, CSS e JavaScript ficam em qualidade_ar/static/. O FastAPI serve a interface e as APIs na mesma origem; não há build ou instalação extra. O painel consulta a cidade, mostra medições e as últimas dez consultas, identifica mocks e exibe erros. A abertura da página realiza uma consulta de Itajaí e salva no histórico.

## Previsão real, PDF e AWS S3

A previsão meteorológica usa Open-Meteo e independe do MODO_MOCK da qualidade do ar. Busque uma cidade no painel, escolha o resultado com estado e país e veja hoje mais seis dias. A busca aceita locais encontrados pelo geocodificador global; não pressupõe que a cidade tenha estação OpenAQ.

- `GET /api/locais?nome=Blumenau`: opções de localização.
- `GET /api/previsao?local_id=3460845`: sete dias para o local selecionado.
- `GET /api/previsao/pdf?local_id=3460845`: download do PDF.
- `POST /api/relatorios`, JSON `{"local_id":3460845}`: consulta previsão, gera PDF em memória e envia ao S3 com boto3.upload_fileobj. Retorna 201 somente após o upload.

Cada exportação consulta novamente a previsão, que pode ter mudado desde a exibição. O PDF inclui período, fuso, mínimas/máximas, probabilidade e volume de precipitação, vento e fonte. N/D indica valor ausente. Não salva arquivos em diretório público e não altera a política de acesso do bucket.

### Configurar AWS quando as credenciais estiverem prontas

Copie `.env.example` para `.env` se ainda não existir; preserve qualquer configuração existente. Defina:

```dotenv
S3_BUCKET=nome-do-seu-bucket
S3_PREFIX=previsoes
AWS_DEFAULT_REGION=sa-east-1
AWS_PROFILE=clima
```

Use a região real do bucket. AWS_PROFILE é opcional; use-o somente se esse perfil existir nas configurações locais AWS. O boto3 também aceita credenciais por variáveis de ambiente (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e `AWS_SESSION_TOKEN` quando temporárias), ou uma IAM role no ambiente de execução. Não envie segredos no chat, nem os adicione ao Git ou JavaScript. Reinicie a API após configurar.

Crie o bucket e conceda ao usuário/role `s3:PutObject` no recurso `arn:aws:s3:::NOME-DO-BUCKET/previsoes/*`. O aplicativo não cria buckets, não solicita ACL pública e não precisa de ListBucket para enviar. Buckets com SSE-KMS podem exigir permissões KMS adicionais. O endpoint fica acessível a quem tem o link ngrok; habilite upload somente para a demonstração controlada, ou adicione autenticação/limites antes de disponibilizar para terceiros.

Sem S3 configurado, o download do PDF funciona e o botão de envio informa a configuração pendente (HTTP 503). Credenciais/permissões inválidas produzem HTTP 502 sem expor segredos. Um timeout depois de iniciar upload pode deixar um arquivo no bucket; confira antes de reenviar. Cada upload usa chave única para evitar sobrescrita.

O histórico existente permanece em SQLite (`qualidade_ar.db`); PostgreSQL ainda não foi configurado. PDFs são objetos no S3, não linhas do banco. A previsão não é persistida em banco nesta versão.

Referências: https://open-meteo.com/en/docs | https://open-meteo.com/en/docs/geocoding-api | https://docs.aws.amazon.com/boto3/latest/guide/s3-uploading-files.html

## PostgreSQL integrado ao SQLite

Atualização: agora existe um banco PostgreSQL local `clima`, com usuário dedicado `clima_app` (sem privilégios de superusuário). Nesta máquina a conexão usa o socket `/tmp`, porta 5432, pela autenticação local já existente. Configure `POSTGRES_DSN` no `.env`; em outros computadores use host, usuário e senha apropriados. O banco e o usuário devem existir antes da primeira execução.

O SQLite continua sendo a origem e atende `/historico`. A API copia as consultas para PostgreSQL ao iniciar e a cada 30 segundos. Esta integração é unidirecional: alterar linhas no PostgreSQL não altera o SQLite. Mock e OpenAQ permanecem identificados pela coluna fonte. A previsão meteorológica continua consultada ao vivo e os PDFs continuam destinados ao S3.

A tabela PostgreSQL `consultas` contém origem UUID, sqlite_id, cidade, fonte, consultado_em (TIMESTAMPTZ), resposta_json (JSONB) e sincronizado_em. A chave `(origem, sqlite_id)` evita duplicações. O SQLite guarda sua identidade em `sync_metadata` e confirmações em `postgres_enviados`. Cada lote só é confirmado localmente após commit remoto; falhas deixam as linhas pendentes para tentar novamente. Mesmo se ocorrer uma falha entre os dois commits, o reenvio não duplica dados. A sincronização não é uma transação distribuída e pode haver atraso entre os bancos.

Para sincronizar manualmente:

```bash
cd /Users/aajuniorbnu/Desktop/clima/qualidade_ar
source .venv/bin/activate
python postgres_sync.py
```

Para consultar o espelho local:

```bash
psql -U clima_app -d clima
```

```sql
SELECT cidade, fonte, consultado_em FROM consultas ORDER BY consultado_em DESC;
```

Se POSTGRES_DSN estiver vazio, funciona somente com SQLite. Se o PostgreSQL estiver indisponível, a API mantém consultas no SQLite e tenta sincronizar novamente. Faça backup dos dois bancos. Se apagar/restaurar o destino PostgreSQL, remova as confirmações correspondentes de `postgres_enviados` no SQLite para reenviar o histórico; não apague a identidade em sync_metadata. A cópia do mesmo arquivo SQLite mantém a mesma origem intencionalmente.
