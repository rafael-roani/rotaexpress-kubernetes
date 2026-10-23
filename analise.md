# RotaExpress - Análise do teste de carga

## 1. Cenário

- Computador: notebook com Intel i5-11400H (6 núcleos / 12 threads), 32 GB de RAM, Windows 11 com Docker Desktop (WSL 2).
- Cluster: Minikube v1.34, Kubernetes v1.31, perfil `ops-lab`, criado com `--cpus=3 --memory=3072`.
- Recursos de cada Pod da aplicação: request e limit de 500m de CPU, 64Mi/128Mi de memória (QoS Burstable).
- Gerador: k6 rodando como Job dentro do cluster (250m de request, 500m de limit), batendo em `http://rotas:8000`.
- Teste: 10 s de aquecimento + 60 s medidos, 9 paradas por rota.
- Taxa escolhida: **6 pedidos/s**. No piloto com 1 Pod deu 72% de falhas, mas ainda com 100 rotas concluídas e nenhuma iteração descartada, então a taxa não estava nem baixa demais nem alta demais. Também bateu com a conta do guia: com meia CPU cada cálculo levou ~0,5 s, então 1 Pod aguenta no máximo uns 2 pedidos/s e 3 Pods uns 6. Com 6/s a gente fica no limite do que 3 Pods conseguiriam, o que deixa a diferença entre as configurações bem visível.

Duas coisas que aconteceram no ambiente e valem anotar:

- O `minikube image load rotas:1.0` deu erro no Windows 11 (`exec: "wmic": executable file not found`). O minikube 1.34 ainda chama o `wmic`, que não vem mais no Windows. Contornamos com `minikube image build -t rotas:1.0 .`, que constrói a imagem direto dentro do nó.
- Mesmo com `--cpus=3`, o nó aparece no Kubernetes com 12 CPUs (as da máquina). O contêiner do Minikube está limitado a 3 CPUs de verdade (`docker inspect` mostra `NanoCpus=3000000000`), mas o scheduler acha que tem 12. Por isso, no passo 8.1, pedir 6 réplicas não deixou nenhum Pod em Pending. Só com 25 réplicas (12,5 CPUs de request) apareceu o `FailedScheduling ... Insufficient cpu` (ver `resultados/limite-no.txt`). Para as medições isso não atrapalhou, porque 3 Pods + k6 somam 2 CPUs, abaixo das 3 reais.

## 2. Evidências

Tabela completa das 9 execuções em `resultados_modelo.csv`. Logs do k6 em `resultados/<nome>.txt` e contadores/`kubectl top` em `resultados/<nome>-pods.txt`.

Medianas das três repetições de cada configuração:

| Pods | Sucessos/s | Falhas | p95 (latencia_ok) | Iterações descartadas | CPU reservada |
|---|---|---|---|---|---|
| 1 | 1,72 | 71,46% | 561,58 ms | 0 | 0,5 CPU |
| 2 | 2,75 | 54,16% | 616,99 ms | 0 | 1,0 CPU |
| 3 | 3,37 | 44,04% | 605,69 ms | 0 | 1,5 CPU |

As três repetições ficaram bem parecidas entre si (ex.: 1 Pod teve 103, 104 e 102 rotas), então a mediana é confiável.

Distribuição entre os Pods (aceitos no teste, diferença dos contadores antes e depois, inclui o aquecimento):

- 2 Pods: 95/88, 99/95, 96/100
- 3 Pods: 79/83/67, 74/79/82, 77/80/80

A carga foi dividida de forma parecida, nenhum Pod ficou com quase tudo.

Uso de CPU no `kubectl top`: com 1 Pod ficou entre ~250m e ~375m, com 3 Pods entre ~180m e ~250m por Pod. Nenhum chegou nos 500m do limite. Essas leituras são atrasadas (o metrics-server faz média de alguns segundos), então servem só como indício.

Todos os Jobs terminaram como `Failed`, mas é porque o k6 sai com código 99 quando a meta de falhas não é atingida. O resumo está completo em todos os logs.

## 3. Explicação

O que foi observado:

- Mais Pods = mais rotas concluídas e menos falhas. De 1 para 3 Pods os sucessos quase dobraram (1,72 → 3,37/s) e as falhas caíram de 71% para 44%.
- O ganho vai diminuindo. De 1 para 2 Pods ganhamos ~1 rota/s, de 2 para 3 só ~0,6. Por CPU reservada: 3,4 rotas/s por CPU com 1 Pod, 2,75 com 2 e 2,25 com 3.
- O p95 dos sucessos ficou parecido em todos (~560 a 620 ms), sempre abaixo de 800 ms. Isso faz sentido porque a aplicação não tem fila: quem é atendido leva o tempo de um cálculo (~0,5 s com meia CPU, contra ~0,3 s no teste com Docker sem limite). Quem não é atendido recebe 503 na hora, e isso não entra no p95.
- Nenhuma configuração bateu a meta de falhas (< 1%).

Hipótese para as falhas continuarem altas mesmo com 3 Pods: cada Pod só faz um cálculo por vez e responde 503 se chegar outro pedido nesse meio tempo. O Service manda cada conexão para um Pod sorteado, sem saber se ele está ocupado. Então mesmo com 3 Pods, que em média dariam conta de ~6 pedidos/s, um pedido pode cair num Pod ocupado enquanto outro está livre. Por causa do sorteio, às vezes um Pod recebe dois pedidos seguidos e recusa o segundo, e às vezes fica um tempo sem receber nada. Isso também explica por que a CPU dos Pods ficou bem abaixo de 500m.

Fizemos uma conta simples para ver se a hipótese fecha: se cada Pod recebe pedidos aleatórios e não tem fila, a chance de recusa é mais ou menos `carga / (1 + carga)`, onde carga = pedidos por segundo no Pod × tempo do cálculo. Com 6/s e 0,5 s:

- 1 Pod: carga 3 → ~75% de recusa (medimos 71%)
- 2 Pods: carga 1,5 → ~60% (medimos 54%)
- 3 Pods: carga 1 → ~50% (medimos 44%)

Os números medidos ficaram um pouco abaixo, acho que porque o k6 manda os pedidos em intervalos certinhos e só a escolha do Pod é aleatória, então a conta é só uma aproximação. Mas o padrão é o mesmo. Isso é uma hipótese nossa, não foi testado separadamente.

## 4. Decisão

Das configurações testadas, ficaríamos com **3 Pods**: foi a que mais entregou rotas (3,37/s), teve menos falhas e o p95 continuou dentro da meta. O custo é **1,5 CPU reservada** (3 × 500m), três vezes o de 1 Pod.

Mas nenhuma configuração atingiu as metas. Pela conta acima, só adicionar Pods não resolve: para ficar abaixo de 1% de recusa, cada Pod teria que ficar parado quase o tempo todo, o que daria centenas de Pods para essa taxa. Não compensa.

Próxima investigação que faríamos:

1. Mudar a aplicação para ter uma fila pequena (esperar alguns ms em vez de responder 503 na hora) e medir de novo. A ideia é trocar falha por um pouco mais de latência, e ainda temos folga no p95.
2. Testar um balanceamento que sabe se o Pod está ocupado (tipo least-connections ou retry quando recebe 503), por exemplo com um Ingress ou service mesh.
3. Repetir com 4 e 5 Pods para confirmar se a curva continua caindo como a conta prevê.
4. Só depois disso pensar em HPA, já sabendo a capacidade real de cada Pod.

Limite da conclusão: todos os Pods estavam no mesmo nó, então isso mede atendimento sob carga e não protege contra a queda do nó. Em produção as réplicas teriam que estar em nós diferentes.
