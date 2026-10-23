// Teste de carga do RotaExpress com Grafana k6.
// Taxa, tamanho da rota e duração chegam por variáveis de ambiente,
// definidas no manifesto do Job (k8s/job-carga.yaml).
import http from 'k6/http';
import { Counter, Rate, Trend } from 'k6/metrics';

const URL = __ENV.URL || 'http://rotas:8000';
const TAXA = Number(__ENV.TAXA || 6);           // pedidos iniciados por segundo
const PARADAS = __ENV.PARADAS || '9';           // entregas por rota
const DURACAO = Number(__ENV.DURACAO || 60);    // segundos medidos

const rotasOk = new Counter('rotas_ok');        // rotas válidas na medição
const falhas = new Rate('falhas');              // fração de tentativas sem rota válida
const latenciaOk = new Trend('latencia_ok', true); // tempo HTTP só dos sucessos

const cenario = {
  executor: 'constant-arrival-rate',
  rate: TAXA,
  timeUnit: '1s',
  preAllocatedVUs: 40,
  maxVUs: 40,
  gracefulStop: '10s',
};

export const options = {
  noConnectionReuse: true,  // cada pedido abre conexão nova; o Service escolhe o Pod a cada vez
  summaryTrendStats: ['avg', 'med', 'p(95)', 'max'],
  scenarios: {
    // 10 s para aquecer; não entra nas métricas próprias.
    aquecimento: { ...cenario, exec: 'aquecer', duration: '10s' },
    // Começa aos 20 s: 10 s de aquecimento + 10 s para pedidos pendentes terminarem.
    medicao: { ...cenario, exec: 'medir', startTime: '20s', duration: DURACAO + 's' },
  },
  thresholds: {
    falhas: ['rate<0.01'],
    latencia_ok: ['p(95)<800'],
    'dropped_iterations{scenario:medicao}': ['count==0'],
  },
};

function pedirRota() {
  return http.get(`${URL}/api/rota?paradas=${PARADAS}`, { timeout: '5s' });
}

export function aquecer() {
  pedirRota();
}

export function medir() {
  const r = pedirRota();
  let corpo = null;
  try { corpo = r.json(); } catch (_) { /* resposta sem JSON conta como falha */ }
  const ok = r.status === 200 && corpo !== null && Array.isArray(corpo.ordem);
  falhas.add(!ok);
  if (ok) {
    rotasOk.add(1);
    latenciaOk.add(r.timings.duration); // 503 rápido não pode "melhorar" o p95
  }
}
