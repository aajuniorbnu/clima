const $ = (id) => document.getElementById(id);
const formatDate = (date) => new Intl.DateTimeFormat('pt-BR', {dateStyle:'short',timeStyle:'short'}).format(new Date(date));
let currentCity = 'Itajaí';
let airLocation = null;
function element(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; }
async function request(path) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
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
  $('air-index').replaceChildren();
  const index = data.indice_validado;
  if(index) {
    $('air-index').append(element('h3',`Índice de partículas: ${index.valor} · escala US AQI`),element('p',index.observacao,'muted'));
    for (const sub of index.subindices) $('air-index').append(element('p',`${sub.poluente.toUpperCase()}: ${sub.valor} · ${sub.horas_validas}/12 horas válidas · até ${formatDate(sub.fim)}`));
  } else $('air-index').append(element('p','Índice indisponível: histórico horário insuficiente.'));
  for(const reason of data.pendencias_indice || []) $('air-index').append(element('p',reason,'muted'));
  if (!mock) $('notice').textContent = `Estação a ${data.distancia_km ?? 'N/D'} km do centro pesquisado. Provedor: ${data.provedor || 'OpenAQ'}. A estação pode estar em outro município. Confira a data de cada leitura.`;
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
async function search(event, place = null) {
  if (event) event.preventDefault();
  const city = $('city').value.trim();
  if (!city) { $('city').setCustomValidity('Informe uma cidade.'); $('city').reportValidity(); return; }
  if (!place) {
    $('dashboard').hidden = true;
    $('air-locations').replaceChildren();
    $('feedback').textContent = 'Buscando cidades…';
    $('search-button').disabled = true;
    try {
      const places = await request(`/api/locais?nome=${encodeURIComponent(city)}`);
      $('feedback').textContent = places.length ? 'Selecione a cidade e o estado para consultar a OpenAQ.' : 'Cidade não encontrada.';
      for (const item of places) {
        const button = element('button',[item.nome,item.estado,item.pais].filter(Boolean).join(', '),'secondary');
        button.type = 'button';
        button.addEventListener('click', () => { $('weather-city').value=item.nome; loadForecast(item, null); });
        $('air-locations').append(button);
      }
    } catch(error) { $('feedback').textContent = error.message; }
    finally { $('search-button').disabled = false; }
    return;
  }
  for (const button of $('air-locations').children) button.disabled = true;
  airLocation = place.id;
  currentCity = city;
  $('search-button').disabled = true;
  $('search-button').textContent = 'Consultando…';
  $('feedback').className = 'feedback';
  $('feedback').textContent = `Consultando ${city}…`;
  $('dashboard').hidden = true;
  try {
    const data = await request(`/qualidade-ar?local_id=${place.id}`);
    render(data);
    $('feedback').textContent = 'Consulta concluída.';
  } catch (error) {
    $('feedback').textContent = error.message;
    $('feedback').className = 'feedback error';
  } finally {
    $('search-button').disabled = false;
    $('search-button').textContent = 'Consultar qualidade do ar';
    for (const button of $('air-locations').children) button.disabled = false;
  }
}
$('city').addEventListener('input', () => $('city').setCustomValidity(''));
$('search-form').addEventListener('submit', search);

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
  $('dashboard').hidden = true;
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
  $('dashboard').hidden = true;
  $('forecast-panel').hidden = true;
  $('report-status').textContent = '';
  $('weather-message').textContent = 'Consultando a previsão real…';
  for (const node of $('location-results').children) node.setAttribute('aria-pressed',String(node === button));
  try {
    const data = await request(`/api/previsao?local_id=${place.id}`);
    if (version !== weatherVersion) return;
    selectedLocation = place.id;
    $('run-result').replaceChildren();
    $('forecast-place').textContent = [data.local.nome,data.local.estado,data.local.pais].filter(Boolean).join(', ');
    $('forecast-timezone').textContent = `Fuso: ${data.fuso} · Consulta: ${formatDate(data.consultado_em)}`;
    const current = data.atual || {};
    $('current-temp').textContent = number(current.temperatura_c,' °C');
    $('current-condition').textContent = current.condicao || 'Condições indisponíveis';
    $('current-icon').textContent = weatherIcon(current.condicao);
    $('current-feels').textContent = number(current.sensacao_c,' °C');
    $('current-humidity').textContent = number(current.umidade,'%');
    $('current-wind').textContent = number(current.vento_kmh,' km/h');
    $('today-rain').textContent = number(data.dias[0].chuva_probabilidade,'%');
    $('current-range').textContent = `Máx. ${number(data.dias[0].max_c,' °C')} · Mín. ${number(data.dias[0].min_c,' °C')}`;
    $('current-time').textContent = current.horario ? `Atualização: ${current.horario.replace('T',' às ')} · ${data.fuso}` : 'Horário atual indisponível';
    $('forecast-days').replaceChildren();
    data.dias.forEach(day => {
      const card = element('article','','forecast-day');
      const date = new Date(day.data+'T12:00:00');
      card.append(element('h4',new Intl.DateTimeFormat('pt-BR',{weekday:'short'}).format(date)),
        element('span',new Intl.DateTimeFormat('pt-BR',{day:'2-digit',month:'2-digit'}).format(date),'day-date'),
        element('span',weatherIcon(day.condicao),'day-icon'), element('p',day.condicao,'forecast-condition'),element('div',number(day.max_c,' °C'),'forecast-temp'),
        element('div',`Mín. ${number(day.min_c,' °C')}`,'forecast-low'),
        element('p',`Chuva: ${number(day.chuva_probabilidade,'%')}`,'forecast-detail'),
        element('p',`Volume: ${number(day.chuva_mm,' mm')}`,'forecast-detail'),
        element('p',`Vento: ${number(day.vento_kmh,' km/h')}`,'forecast-detail'));
      $('forecast-days').append(card);
    });
    $('forecast-panel').hidden = false;
    $('weather-message').textContent = 'Previsão atualizada com dados reais.';
    loadAlerts();
  } catch (error) { if (version === weatherVersion) $('weather-message').textContent = error.message; }
}
async function report(save) {
  if (!selectedLocation) return;
  const location = selectedLocation;
  const version = weatherVersion;
  $('download-pdf').disabled = $('save-s3').disabled = true;
  $('report-status').textContent = save ? 'Salvando PDF…' : 'Preparando seu PDF…';
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
      if (version === weatherVersion) $('report-status').textContent = 'PDF salvo com sucesso.';
    } else {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `previsao-${location}-7-dias.pdf`; link.click();
      setTimeout(() => URL.revokeObjectURL(url),30000);
      if (version === weatherVersion) $('report-status').textContent = 'PDF gerado. O download foi iniciado.';
    }
  } catch (error) {
    if (version === weatherVersion) $('report-status').textContent = error.name === 'AbortError' ? 'O prazo de espera terminou. Não foi possível confirmar se o PDF foi salvo.' : error.message;
  } finally { clearTimeout(timeout); $('download-pdf').disabled = $('save-s3').disabled = false; }
}
$('weather-form').addEventListener('submit',searchWeather);
$('download-pdf').addEventListener('click',() => report(false));
$('save-s3').addEventListener('click',() => report(true));

function weatherIcon(condition = '') {
  if (/Trovoada/.test(condition)) return '⛈';
  if (/chuva|Chuva|Garoa/.test(condition)) return '☂';
  if (/Neve/.test(condition)) return '❄';
  if (/nublado|Nublado|Nevoeiro/.test(condition)) return '☁';
  return condition === 'Céu limpo' ? '☀' : '◌';
}
// Blumenau é apenas o local inicial; o usuário pode escolher qualquer resultado.
(async () => {
  await searchWeather({preventDefault(){}});
  const initial = Array.from($('location-results').children).find(node => /Blumenau.*Santa Catarina/.test(node.textContent));
  if (initial && $('weather-city').value === 'Blumenau') initial.click();
})();

let alertVersion = 0;
async function loadAlerts() {
  const version = ++alertVersion;
  if (!selectedLocation) return;
  const id=selectedLocation;
  $('evaluate-run').disabled=true;
  $('run-result').textContent='Consultando clima e qualidade do ar…';
  try {
    const params=new URLSearchParams({local_id:id,sensivel:$('sensitive').checked});
    const result=await request(`/api/alerta?${params}`);
    if (selectedLocation!==id || version!==alertVersion) return;
    $('run-result').replaceChildren(element('h4',result.mensagem));
    if(result.dados_ar) {
      render(result.dados_ar);
      $('city').value = result.dados_ar.cidade;
      $('feedback').textContent='Qualidade do ar da mesma cidade e consulta dos alertas.';
    } else {
      $('dashboard').hidden=true;
      $('feedback').textContent='Qualidade do ar indisponível para a cidade selecionada.';
    }
    if(result.dados_clima) $('run-result').append(element('p',`Clima: ${result.dados_clima.local.nome} · ${result.dados_clima.atual.horario} (${result.dados_clima.fuso})`,'muted'));
    for (const [title,items] of [['Riscos',result.riscos],['Dados pendentes',result.pendencias],['Cuidados',result.cuidados]]) {
      if (!items?.length) continue;
      $('run-result').append(element('strong',title));
      const list=document.createElement('ul');
      items.forEach(item=>list.append(element('li',item)));
      $('run-result').append(list);
    }
    $('run-result').append(element('p',result.escopo,'muted'), element('p', `Consulta concluída em ${new Date().toLocaleTimeString('pt-BR')}`, 'muted'));
  } catch(error) { if(selectedLocation===id && version===alertVersion) $('run-result').textContent=error.message; }
  finally { if(version===alertVersion) $('evaluate-run').disabled=false; }
}
$('evaluate-run').addEventListener('click',loadAlerts);
$('sensitive').addEventListener('change',loadAlerts);
