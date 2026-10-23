"""RotaExpress: protótipo didático, só biblioteca padrão do Python.

Resolve um pequeno problema real de roteirização por busca exata.
Pontos e distâncias são fictícios; não é um roteirizador viário de produção.
"""
import itertools
import json
import math
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PONTOS = [(10, 10), (80, 20), (25, 70), (70, 85), (45, 25),
          (15, 45), (90, 55), (50, 95), (65, 45), (35, 55)]
POD = os.getenv('HOSTNAME', socket.gethostname())
VAGA = threading.BoundedSemaphore(1)

# Contadores acumulados desde que o contêiner iniciou. Aparecem em cada linha
# de log, para que `kubectl logs --tail=1` mostre quanto cada Pod já atendeu.
CONTAGEM = {'aceitos': 0, 'recusados': 0}
TRAVA_CONTAGEM = threading.Lock()


def registrar(evento, detalhe=''):
    with TRAVA_CONTAGEM:
        CONTAGEM[evento] += 1
        aceitos, recusados = CONTAGEM['aceitos'], CONTAGEM['recusados']
    print(f'{evento[:-1]} {detalhe}total_aceitos={aceitos} total_recusados={recusados}', flush=True)


def calcular_rota(paradas):
    """Menor circuito euclidiano: depósito 0 -> entregas -> depósito 0."""
    pontos = PONTOS[:paradas + 1]
    dist = [[math.dist(a, b) for b in pontos] for a in pontos]
    melhor = float('inf')
    ordem = None
    for rota in itertools.permutations(range(1, len(pontos))):
        total = dist[0][rota[0]] + dist[rota[-1]][0]
        for a, b in zip(rota, rota[1:]):
            total += dist[a][b]
        if total < melhor:
            melhor, ordem = total, rota
    return {'pontos': pontos, 'ordem': [0, *ordem, 0],
            'distancia': round(melhor, 2), 'paradas': paradas}


PAGINA = '''<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>RotaExpress • Operações</title><style>
body{font:18px system-ui;max-width:850px;margin:40px auto;padding:20px;color:#18382a;background:#f5f8f6}
h1{color:#004823}button,select{font:inherit;padding:10px;border-radius:8px;border:1px solid #99b5a5}
button{background:#004823;color:white;cursor:pointer}section{background:white;border-radius:14px;padding:25px}
svg{width:100%;max-height:360px}small{display:block;color:#526158}#info{min-height:55px}</style>
<h1>RotaExpress</h1><p>Uma pequena transportadora precisa visitar pontos de entrega e voltar ao depósito, percorrendo a menor distância possível.</p>
<section><label>Entregas: <select id="n"><option>7</option><option>8</option><option selected>9</option></select></label>
<button id="go">Calcular rota</button><p id="info">O ponto 0 é o depósito. Clique para enviar uma solicitação à aplicação.</p>
<svg id="mapa" viewBox="0 0 110 110" aria-label="Rota calculada"></svg></section>
<p><small>Protótipo didático: pontos fictícios, distâncias em linha reta, sem trânsito ou ruas. Cada pedido refaz o cálculo, sem cache.</small></p>
<script>
document.querySelector('#go').onclick=async()=>{
 const el=document.querySelector('#info'); el.textContent='Calculando…';
 try {const r=await fetch('/api/rota?paradas='+document.querySelector('#n').value);
 const d=await r.json(); if(!r.ok)throw Error(d.erro);
 el.textContent=`Distância: ${d.distancia} unidades | Cálculo: ${d.calculo_ms} ms | Atendido por: ${d.pod}`;
 let s='<polyline fill="none" stroke="#326ce5" stroke-width="0.8" points="'+d.ordem.map(i=>d.pontos[i].join(',')).join(' ')+'"/>';
 d.pontos.forEach((p,i)=>{s+=`<circle cx="${p[0]}" cy="${p[1]}" r="2" fill="${i===0?'#e31e24':'#004823'}"/><text x="${p[0]+3}" y="${p[1]}" font-size="4">${i}</text>`});
 document.querySelector('#mapa').innerHTML=s;
 }catch(e){el.textContent='Não foi possível atender: '+e.message;}
};</script></html>'''


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass  # Desliga o log padrão de acesso; health checks poluiriam a saída.

    def responder(self, status, dados, tipo='application/json; charset=utf-8'):
        corpo = dados.encode('utf-8') if isinstance(dados, str) else json.dumps(dados).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(len(corpo)))
        self.send_header('X-Pod', POD)
        self.send_header('Connection', 'close')
        self.end_headers()
        try:
            self.wfile.write(corpo)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ('/healthz', '/readyz'):
            return self.responder(200, {'status': 'ok', 'pod': POD})
        if url.path == '/':
            return self.responder(200, PAGINA, 'text/html; charset=utf-8')
        if url.path != '/api/rota':
            return self.responder(404, {'erro': 'Caminho não encontrado'})
        try:
            n = int(parse_qs(url.query).get('paradas', ['9'])[0])
            if not 3 <= n <= 9:
                raise ValueError
        except ValueError:
            return self.responder(400, {'erro': 'Use de 3 a 9 paradas'})
        if not VAGA.acquire(blocking=False):
            registrar('recusados')
            return self.responder(503, {'erro': 'Calculador ocupado. Tente novamente.', 'pod': POD})
        try:
            inicio = time.perf_counter()
            resultado = calcular_rota(n)
            resultado.update(pod=POD, calculo_ms=round((time.perf_counter()-inicio)*1000, 1))
            self.responder(200, resultado)
            registrar('aceitos', f"calculo_ms={resultado['calculo_ms']} ")
        finally:
            VAGA.release()


if __name__ == '__main__':
    porta = int(os.getenv('PORT', '8000'))
    print(f'RotaExpress em http://localhost:{porta}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', porta), Handler).serve_forever()
