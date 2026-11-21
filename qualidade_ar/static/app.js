const $ = (id) => document.getElementById(id);
const formatDate = (date) => new Intl.DateTimeFormat('pt-BR', {dateStyle:'short',timeStyle:'short'}).format(new Date(date));
let currentCity = 'Itajaí';
let historySequence = 0;
function element(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
async function request(path) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(path, {signal:controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Não foi possível concluir a consulta. Verifique a cidade informada.');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('A consulta demorou demais. Tente novamente.');
    if (error instanceof TypeError) throw new Error('Sem conexão com o serviço. Tente novamente.');
    throw error;
  } finally { clearTimeout(timeout); }
}
function render(data) {
  $('city-title').textContent = data.cidade;
  const mock = data.fonte === 'mock';
  $('source-badge').textContent = mock ? 'Demonstração · Mock' : 'Fonte · OpenAQ';
  $('notice').textContent = mock ? 'Modo demonstração: os valores abaixo são fictícios e servem para testar a integração.' : 'Medições da OpenAQ. Confira o horário de cada sensor; dados antigos não descrevem necessariamente as condições atuais.';
  $('station-name').textContent = data.estacao_nome;
  $('updated').textContent = formatDate(data.consultado_em);
  const count = data.medicoes.length;
  $('measurement-count').textContent = `${count} ${count === 1 ? 'medição disponível' : 'medições disponíveis'}`;
  const stale = data.medicoes.filter(m => m.desatualizado).length;
  $('freshness').textContent = !count ? 'Nenhuma medição disponível.' : stale ? `${stale} leitura(s) com horário fora do intervalo esperado.` : mock ? 'Leituras simuladas geradas nesta consulta.' : 'Leituras dentro do intervalo de atualização do serviço.';
  $('measurements').replaceChildren();
  data.medicoes.forEach(m => {
    const card = element('article', '', 'measurement');
    const top = element('div', '', 'measure-top');
    const names = {pm25:'PM2.5',pm10:'PM10',o3:'O₃',no2:'NO₂',so2:'SO₂',co:'CO'};
    top.append(element('h3', names[m.poluente] || m.poluente), element('span', mock ? 'Simulado' : `Sensor ${m.sensor_id}`, 'sensor'));
    const value = element('p', new Intl.NumberFormat('pt-BR',{maximumFractionDigits:3}).format(m.valor),'value');
    value.append(element('span',m.unidade,'unit'));
    card.append(top, value, element('span', m.desatualizado ? 'Horário fora do intervalo esperado' : mock ? 'Dado de demonstração' : 'Leitura recente', m.desatualizado ? 'fresh stale' : 'fresh'), element('p', `Medição: ${formatDate(m.medido_em)}`, 'measure-time'));
    $('measurements').append(card);
  });
  $('dashboard').hidden = false;
}
async function loadHistory() {
  const sequence = ++historySequence;
  $('history-status').textContent = 'Carregando histórico…';
  $('history-body').replaceChildren();
  try {
    const rows = await request(`/historico?cidade=${encodeURIComponent(currentCity)}&limite=10`);
    if (sequence !== historySequence) return;
    $('history-status').textContent = rows.length ? '' : 'Nenhuma consulta salva para esta cidade.';
    rows.forEach(row => {
      const tr = document.createElement('tr');
      const summary = row.medicoes.map(m => `${m.poluente.toUpperCase()}: ${new Intl.NumberFormat('pt-BR').format(m.valor)} ${m.unidade}`).join(' · ') || 'Sem medições';
      [formatDate(row.consultado_em), row.cidade, summary, row.fonte === 'mock' ? 'Mock · Simulado' : 'OpenAQ'].forEach(text => tr.append(element('td',text)));
      $('history-body').append(tr);
    });
  } catch (error) { if (sequence === historySequence) $('history-status').textContent = `Histórico indisponível: ${error.message}`; }
}
async function search(event) {
  if (event) event.preventDefault();
  const city = $('city').value.trim();
  if (!city) { $('city').setCustomValidity('Informe uma cidade.'); $('city').reportValidity(); return; }
  currentCity = city;
  ++historySequence;
  $('history-body').replaceChildren();
  $('history-status').textContent = '';
  $('search-button').disabled = true;
  $('refresh-history').disabled = true;
  $('search-button').textContent = 'Consultando…';
  $('feedback').className = 'feedback';
  $('feedback').textContent = `Consultando ${city}…`;
  $('dashboard').hidden = true;
  try {
    const data = await request(`/qualidade-ar?cidade=${encodeURIComponent(city)}`);
    render(data);
    $('feedback').textContent = 'Consulta concluída e salva no histórico.';
  } catch (error) {
    $('feedback').textContent = error.message;
    $('feedback').className = 'feedback error';
  } finally {
    $('search-button').disabled = false;
    $('search-button').textContent = 'Consultar qualidade do ar';
    $('refresh-history').disabled = false;
    await loadHistory();
  }
}
$('city').addEventListener('input', () => $('city').setCustomValidity(''));
$('search-form').addEventListener('submit', search);
$('refresh-history').addEventListener('click', loadHistory);
search();

// Previsão real: seleção explícita do local antes de consultar e exportar.
let selectedLocation = null;
let weatherVersion = 0;
const number = (value, unit = '') => value === null || value === undefined ? 'N/D' : `${new Intl.NumberFormat('pt-BR').format(value)}${unit}`;
async function searchWeather(event) {
  event.preventDefault();
  const query = $('weather-city').value.trim();
  if (query.length < 2) return;
  const version = ++weatherVersion;
  selectedLocation = null;
  $('forecast-panel').hidden = true;
  $('location-results').replaceChildren();
  $('report-status').textContent = '';
  $('weather-message').textContent = 'Buscando locais…';
  $('weather-search-button').disabled = true;
  try {
    const places = await request(`/api/locais?nome=${encodeURIComponent(query)}`);
    if (version !== weatherVersion) return;
    $('weather-message').textContent = places.length ? 'Selecione o local desejado para consultar a previsão.' : 'Nenhum local encontrado. Tente o nome da cidade sem o estado.';
    for (const place of places) {
      const button = element('button',[place.nome,place.estado,place.pais].filter(Boolean).join(', '));
      button.type = 'button';
      button.setAttribute('aria-pressed','false');
      button.addEventListener('click',() => loadForecast(place, button));
      $('location-results').append(button);
    }
  } catch (error) { if (version === weatherVersion) $('weather-message').textContent = error.message; }
  finally { $('weather-search-button').disabled = false; }
}
async function loadForecast(place, button) {
  const version = ++weatherVersion;
  selectedLocation = null;
  $('forecast-panel').hidden = true;
  $('report-status').textContent = '';
  $('weather-message').textContent = 'Consultando a previsão real…';
  for (const node of $('location-results').children) node.setAttribute('aria-pressed',String(node === button));
  try {
    const data = await request(`/api/previsao?local_id=${place.id}`);
    if (version !== weatherVersion) return;
    selectedLocation = place.id;
    $('forecast-place').textContent = [data.local.nome,data.local.estado,data.local.pais].filter(Boolean).join(', ');
    $('forecast-timezone').textContent = `Fuso: ${data.fuso} · Consulta: ${formatDate(data.consultado_em)}`;
    $('forecast-days').replaceChildren();
    data.dias.forEach(day => {
      const card = element('article','','forecast-day');
      const date = new Date(day.data+'T12:00:00');
      card.append(element('h4',new Intl.DateTimeFormat('pt-BR',{weekday:'short'}).format(date)),
        element('span',new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'2-digit'}).format(date),'day-date'),
        element('p',day.condicao,'forecast-condition'),element('div',number(day.max_c,'°'),'forecast-temp'),
        element('div',`Mín. ${number(day.min_c,' °C')}`,'forecast-low'),
        element('p',`Chuva: ${number(day.chuva_probabilidade,'%')}`,'forecast-detail'),
        element('p',`Volume: ${number(day.chuva_mm,' mm')}`,'forecast-detail'),
        element('p',`Vento: ${number(day.vento_kmh,' km/h')}`,'forecast-detail'));
      $('forecast-days').append(card);
    });
    $('forecast-panel').hidden = false;
    $('weather-message').textContent = 'Previsão atualizada com dados reais.';
  } catch (error) { if (version === weatherVersion) $('weather-message').textContent = error.message; }
}
async function report(save) {
  if (!selectedLocation) return;
  const location = selectedLocation;
  const version = weatherVersion;
  $('download-pdf').disabled = $('save-s3').disabled = true;
  $('report-status').textContent = save ? 'Gerando PDF e enviando ao S3…' : 'Preparando seu PDF…';
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(),120000);
  try {
    const response = await fetch(save ? '/api/relatorios' : `/api/previsao/pdf?local_id=${location}`,save ? {
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({local_id:location}),signal:controller.signal
    } : {signal:controller.signal});
    if (!response.ok) {
      const error = await response.json();
      throw new Error(typeof error.detail === 'string' ? error.detail : 'Não foi possível gerar o relatório.');
    }
    if (save) {
      const result = await response.json();
      if (version === weatherVersion) $('report-status').textContent = `PDF salvo no S3: ${result.uri}`;
    } else {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `previsao-${location}-7-dias.pdf`; link.click();
      setTimeout(() => URL.revokeObjectURL(url),30000);
      if (version === weatherVersion) $('report-status').textContent = 'PDF gerado. O download foi iniciado.';
    }
  } catch (error) {
    if (version === weatherVersion) $('report-status').textContent = error.name === 'AbortError' ? 'O prazo de espera terminou. Se estava enviando ao S3, confira o bucket antes de tentar novamente.' : error.message;
  } finally { clearTimeout(timeout); $('download-pdf').disabled = $('save-s3').disabled = false; }
}
$('weather-form').addEventListener('submit',searchWeather);
$('download-pdf').addEventListener('click',() => report(false));
$('save-s3').addEventListener('click',() => report(true));
