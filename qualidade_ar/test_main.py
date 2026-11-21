from datetime import datetime, timezone
import httpx
import pytest
from fastapi.testclient import TestClient
import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('POSTGRES_DSN', '')
    monkeypatch.setattr(main, 'DB', tmp_path / 'test.db')
    monkeypatch.setattr(main, 'MOCK', True)
    with TestClient(main.app) as client:
        yield client


def test_mock_e_historico(client):
    response = client.get('/qualidade-ar', params={'cidade': 'Itajaí'})
    assert response.status_code == 200
    assert response.json()['fonte'] == 'mock'
    assert response.json()['estacao_id'] is None
    history = client.get('/historico', params={'cidade': 'itajai'}).json()
    assert history == [response.json()]


def test_cidade_e_limite(client):
    assert client.get('/qualidade-ar?cidade=desconhecida').status_code == 404
    assert client.get('/historico?cidade=itajai&limite=0').status_code == 422


def test_real_sem_estacao(client, monkeypatch):
    monkeypatch.setattr(main, 'MOCK', False)
    assert client.get('/qualidade-ar?cidade=itajai').status_code == 503
    assert client.get('/historico?cidade=itajai').json() == []


def test_conversao():
    station = {'sensors': [{'id': 7, 'parameter': {'name': 'pm25', 'units': 'µg/m³'}}]}
    readings = [{'sensorsId': 7, 'value': 9, 'datetime': {'utc': '2026-01-01T00:00:00Z'}}]
    result = main.converter(station, readings, datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result[0].desatualizado
    assert result[0].poluente == 'pm25'
    readings[0]['value'] = -1
    assert main.converter(station, readings, datetime.now(timezone.utc)) == []


def test_openaq_contrato_e_autenticacao(client, monkeypatch):
    original = httpx.AsyncClient
    def handler(request):
        assert request.headers['X-API-Key'] == 'teste'
        if request.url.path.endswith('/latest'):
            return httpx.Response(200, json={'results': [{'sensorsId': 7, 'value': 10,
                 'datetime': {'utc': '2026-01-01T00:00:00Z'}}]})
        return httpx.Response(200, json={'results': [{'name': 'Teste', 'sensors': [
            {'id': 7, 'parameter': {'name': 'pm25', 'units': 'µg/m³'}}]}]})
    monkeypatch.setenv('OPENAQ_API_KEY', 'teste')
    monkeypatch.setattr(main.httpx, 'AsyncClient', lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler)))
    import asyncio
    station, readings = asyncio.run(main.buscar_openaq(123))
    assert station['name'] == 'Teste'
    assert readings[0]['value'] == 10


def test_timeout(client, monkeypatch):
    original = httpx.AsyncClient
    def handler(request):
        raise httpx.ReadTimeout('teste', request=request)
    monkeypatch.setenv('OPENAQ_API_KEY', 'teste')
    monkeypatch.setattr(main.httpx, 'AsyncClient', lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler)))
    import asyncio
    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.buscar_openaq(123))
    assert error.value.status_code == 504
