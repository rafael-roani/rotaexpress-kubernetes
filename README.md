# RotaExpress

Projeto de operações: publicar uma aplicação no Kubernetes, gerar carga controlada e comparar 1, 2 e 3 Pods.

Comece pelo **Guia_Atividade.pdf**, na pasta acima. Ele explica cada comando, o motivo da ordem e o que observar. Este arquivo serve só para retomar algo já compreendido.

## O que vem pronto e o que você escreve

| Arquivo | Situação |
|---|---|
| `app.py` | Aplicação (Python, só biblioteca padrão). |
| `Dockerfile`, `.dockerignore` | Receita da imagem. |
| `carga.js` | Script do k6. Parâmetros por variável de ambiente: `TAXA`, `PARADAS`, `DURACAO`, `URL`. |
| `resultados_modelo.csv` | Tabela para registrar as medições. |
| `k8s/namespace.yaml` | Você escreve (Grupo 1). |
| `k8s/deployment.yaml` | Você escreve (Grupo 3). |
| `k8s/service.yaml` | Você escreve (Grupo 4). |
| `k8s/job-carga.yaml` | Você escreve (Grupo 6). |

## Ambiente

Windows 10/11 (PowerShell) ou Ubuntu 22.04+. Docker em execução, `kubectl` e `minikube` no PATH. O cluster usa 3 CPUs e 3 GiB.

Os comandos abaixo são iguais nos dois sistemas. Diferenças: no PowerShell use `curl.exe` em vez de `curl`; `watch` só existe no Ubuntu.

## Sequência de comandos

```
# 1. Cluster e contexto
minikube start -p ops-lab --driver=docker --cpus=3 --memory=3072
minikube profile ops-lab
kubectl config current-context
mkdir k8s
kubectl apply -f k8s/namespace.yaml
kubectl config set-context --current --namespace=ops-lab
minikube addons enable metrics-server

# 2. Imagem
docker build -t rotas:1.0 .
docker run -d --rm -p 8000:8000 --name rotas-teste rotas:1.0
curl http://localhost:8000/healthz
docker stop rotas-teste
minikube image load rotas:1.0

# 3. Deployment
kubectl apply -f k8s/deployment.yaml
kubectl rollout status deployment/rotas
kubectl get deployment,replicaset,pods

# 4. Service
kubectl apply -f k8s/service.yaml
kubectl get endpointslices -l kubernetes.io/service-name=rotas
kubectl run teste --rm -it --restart=Never --image=busybox:1.36 -- wget -qO- http://rotas:8000/healthz
kubectl port-forward service/rotas 8080:8000

# 5. Falha e rollback
kubectl set image deployment/rotas rotas=rotas:1.1
kubectl rollout status deployment/rotas --timeout=60s
kubectl rollout undo deployment/rotas

# 6. Teste de carga (ciclo de medição)
kubectl create configmap carga-script --from-file=carga.js
mkdir resultados
kubectl apply -f k8s/job-carga.yaml
kubectl wait --for=condition=Ready pod -l job-name=carga --timeout=180s
kubectl logs -f job/carga
kubectl logs job/carga > resultados/NOME.txt
kubectl delete job carga

# 7. Escala e medição
kubectl scale deployment/rotas --replicas=3
kubectl rollout status deployment/rotas
kubectl logs -l app=rotas --prefix --tail=1
kubectl top pods

# 8. Encerramento
kubectl delete namespace ops-lab
minikube stop
```

## O que a aplicação faz

Busca o menor circuito euclidiano para até nove entregas fictícias (9! ordens, trabalho real de CPU). Cada Pod aceita um cálculo por vez; um pedido simultâneo recebe 503. Não há fila nem cache. Cada cálculo escreve uma linha de log com os totais acumulados do Pod (`total_aceitos`, `total_recusados`), o que permite ver a distribuição com `kubectl logs -l app=rotas --prefix --tail=1`.

Rotas: `/` (interface), `/api/rota?paradas=9` (cálculo), `/healthz` e `/readyz` (saúde).

É um protótipo didático: servidor HTTP da biblioteca padrão, sem autenticação, sem ruas nem trânsito.

## Como ler o resumo do k6

- `rotas_ok`: rotas válidas na janela medida. Sucessos por segundo = `rotas_ok / 60`. O valor `/s` impresso pelo k6 divide pelo tempo total, incluindo aquecimento.
- `falhas`: fração de tentativas sem rota válida (inclui 503).
- `latencia_ok p(95)`: tempo HTTP das respostas com sucesso.
- `dropped_iterations{scenario:medicao}`: pedidos que o k6 não conseguiu iniciar. Precisa ser 0.

Metas: p95 < 800 ms, falhas < 1%, nenhuma iteração descartada. Meta não atingida faz o k6 sair com código 99 e o Job aparecer como `Failed`; o resumo continua nos logs.

## Documentação

- https://kubernetes.io/docs/reference/kubectl/quick-reference/
- https://kubernetes.io/docs/concepts/workloads/controllers/deployment/
- https://kubernetes.io/docs/concepts/services-networking/service/
- https://kubernetes.io/docs/concepts/workloads/controllers/job/
- https://minikube.sigs.k8s.io/docs/start/
- https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate/

Consulta: 15/10/2026.
