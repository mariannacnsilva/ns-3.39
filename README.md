# Comparação de roteamento MANET com ns-3.39

## Objetivo

O objetivo é comparar AODV, DSDV e OLSR quanto à rapidez e à eficiência de entrega em uma MANET móvel, considerando confiabilidade e tráfego de controle. O estudo busca comprovar a hipótese (**H1**) de que aumentar a velocidade altera negativamente o atraso e/ou a taxa de entrega, sem declarar um protocolo vencedor. As conclusões são limitadas ao cenário e aos parâmetros descritos aqui.

## O que o experimento faz

MANET é uma rede sem ponto de acesso central: os nós móveis enviam dados e podem encaminhar pacotes uns dos outros. O ns-3 simula os nós, o rádio, o movimento e o roteamento. O experimento envia quatro fluxos UDP entre pares fixos e mede os pacotes observados no destino.

- **AODV** descobre rotas sob demanda; **DSDV** e **OLSR** mantêm informações de rota proativamente.
- **PDR** é a porcentagem de pacotes transmitidos que chegaram ao destino.
- **Vazão** é o número de bits recebidos dividido pela janela útil da aplicação.
- **Atraso** é o tempo médio entre envio e recepção dos pacotes entregues.
- **Jitter** é a variação média do atraso entre recepções consecutivas.
- **Tráfego de controle** é o que o protocolo transmite para descobrir ou manter rotas.

## Cenário experimental

Os parâmetros do cenário ficam em `config/experiment.json`; os fixos de rádio e rede (canal 1, 20 MHz, 6 Mbps, porta 9000, rede 10.0.0.0/8) são constantes em `scratch/manet-routing-compare.cc`. Os manifestos preservam a configuração e a revisão usadas.

| Parâmetro | Etapa 1 — base | Etapa 2 — carga |
|---|---|---|
| Nós e área | 20 nós em 500 × 500 m | Igual à Etapa 1 |
| Rádio | IEEE 802.11g ad hoc, 2,4 GHz, canal 1, largura 20 MHz, taxa PHY fixa de 6 Mbps | Igual à Etapa 1 |
| Propagação | YANS com LogDistance; expoente 2,6, perda de referência 40,05 dB a 1 m; 16 dBm e detecção de preâmbulo a partir de −82 dBm, o que dá alcance de cerca de 169 m | Igual à Etapa 1 |
| Mobilidade | RandomWaypoint; velocidade mínima 1 m/s, pausa 10 s; velocidade máxima 1, 5, 10 e 20 m/s | Igual à Etapa 1 |
| Aplicação | 4 fluxos UDP: 0→1, 2→3, 4→5 e 6→7; payload de 512 bytes; início defasado em ¼ do intervalo entre pacotes por fluxo (25 ms a 10 pacotes/s), porque transmissões perfeitamente sincronizadas colidem de forma repetida | Mesmos fluxos e payload |
| Taxa | 10 pacotes/s por fluxo | 10 e 100 pacotes/s por fluxo |
| Duração | 120 s; tráfego entre 10 e 110 s; janela útil de 100 s e 10 s de escoamento | Igual à Etapa 1 |
| Runs | Runs 1–10 | Runs 1–30 |
| Execuções | 3 protocolos × 4 velocidades × 10 runs = **120** | 3 protocolos × 4 velocidades × 2 cargas × 30 runs = **720** |

A Etapa 2 altera apenas a carga oferecida. Em ambas, a posição inicial usa stream 10, a mobilidade usa streams atribuídos a partir de 1000, a seed mestre é 12345 e o run é passado a `RngSeedManager::SetRun`. Para uma mesma velocidade/run, os protocolos e cargas devem ter trajetórias iguais, conferidas pela comparação numérica dos traces com tolerância de 1 mm. O ns-3 integra a posição a cada consulta, e o tráfego muda quantas consultas ocorrem, então um resíduo de cerca de 10⁻⁶ m pode alterar o texto do trace mesmo com a mesma trajetória. O SHA-256 fica como verificação de integridade de cada arquivo. As runs 1–10 da Etapa 2 a 10 pacotes/s também são comparadas com a Etapa 1 para confirmar reprodução exata dos dados por fluxo.

### Métricas

As métricas são calculadas por fluxo e agregadas por execução, somando pacotes e bytes:

- **Vazão (Mbps)** = `8 × rxBytes / (100 × 10⁶)`. `rxBytes` do FlowMonitor inclui cabeçalhos IP e UDP.
- **PDR (%)** = `100 × rxPackets / txPackets`.
- **Atraso médio (ms)** = `delaySum / rxPackets`; ausente se não houver recepção.
- **Jitter médio (ms)** = `jitterSum / (rxPackets − 1)`; ausente se houver menos de duas recepções.

- **Tráfego de controle** = pacotes e bytes IP enviados por todos os nós na porta UDP do protocolo (AODV 654, OLSR 698, DSDV 269), durante toda a simulação. Inclui as retransmissões de controle, é um valor por execução e não mede tempo de canal nem energia. É comparado entre protocolos e não entra na decisão da H1.

Em `flows.csv`, `lostPackets` é o valor do FlowMonitor, que só enxerga pacotes que entraram na camada IP, e `undeliveredPackets` é `txPackets − rxPackets`. `routingProtocol` registra o protocolo instalado.

Na agregação de uma execução, atraso é ponderado pelo total de pacotes recebidos; jitter, pelo total de pares consecutivos recebidos em cada fluxo. A vazão usa a janela fixa de 100 s, não o tempo entre o primeiro e o último pacote recebido. O analisador informa média, desvio-padrão, IC t de 95% e quantidade válida por célula.

### Decisão de H1

Para cada protocolo, métrica e carga, compara-se o IC de 95% a 1 m/s com o IC a 20 m/s:

- **Sustentada:** os ICs não se sobrepõem no sentido de piora — atraso/jitter aumentam, ou vazão/PDR diminuem.
- **Melhora:** os ICs não se sobrepõem na direção oposta.
- **Inconclusiva:** os ICs se sobrepõem ou não há amostra válida para calcular os intervalos.

Não são feitos testes estatísticos entre protocolos. As quatro figuras de cada etapa apresentam uma série por protocolo (e, na Etapa 2, por carga), com barras de IC de 95%.

O efeito da carga é descritivo: a Etapa 2 compara o desfecho da H1 e a diferença entre 20 e 1 m/s em cada carga (`load-effect.md`), sem hipótese própria.

## Preparação do ambiente

O build e as simulações devem ser executados em Ubuntu 22.04/24.04, nativo ou em máquina virtual. Requisitos: g++, CMake, Ninja ou Make, Python 3 e dependências do `requirements.txt`. Qt 5 é necessário apenas para compilar/abrir o visualizador NetAnim.

### Hardware e software do ambiente inventariado

Inventário da máquina disponível para este projeto em 4 de novembro de 2026. Os lotes oficiais foram executados neste ambiente, na revisão `588d738`, com o build no perfil `release`, que evita o `-march=native` do perfil `optimized`. Atualize esta seção caso os experimentos sejam executados em outra máquina ou com versões diferentes.

| Componente | Especificação |
|---|---|
| Computador | Acer Nitro ANV15-51 |
| Processador | 13th Gen Intel Core i7-13620H; 10 núcleos, 16 processadores lógicos |
| Memória | 15,7 GB RAM (aprox. 16 GB) |
| Sistema host | Windows 11 Home, build 26200 |
| Ambiente de build | VM VirtualBox, Ubuntu 22.04.5 LTS, 4 vCPUs e cerca de 3 GB de RAM |
| ns-3 | 3.39 (versão do código-fonte em `VERSION`; perfil `release`) |
| Python | 3.10.12; ambiente virtual `.venv` |
| Compilador C++ | g++ 11.4.0 |
| CMake | 3.22.1 |
| Ninja | 1.10.1 |
| Dependências Python observadas | NumPy 2.2.6, pandas 2.3.3, SciPy 1.15.3 e Matplotlib 3.10.9 |

Qt 5 e NetAnim são opcionais e não foram considerados necessários para executar as métricas; servem somente para compilar/visualizar as animações.

```bash
sudo apt update
sudo apt install -y git g++ cmake ninja-build python3 python3-venv python3-pip pkg-config
sudo apt install -y qtbase5-dev qt5-qmake  # opcional: NetAnim

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
./ns3 configure -d release
./ns3 build scratch/manet-routing-compare
python -m unittest tests.test_experiment -v
```

## Execução

Todos os comandos abaixo partem da raiz do repositório. `--dry-run` apenas lista a matriz: não executa nem compila o ns-3.

### Conferir matrizes

```bash
python scripts/run_experiment.py --stage stage1 --dry-run  # 120 execuções
python scripts/run_experiment.py --stage stage2 --dry-run  # 720 execuções
python scripts/run_experiment.py --stage stage1 --animation --dry-run  # 12 animações
```

### Pilotos

```bash
# Um run por célula: 12 execuções na Etapa 1 e 24 na Etapa 2.
python scripts/run_experiment.py --stage stage1 --pilot
python scripts/run_experiment.py --stage stage2 --pilot

# Três runs para exercitar ICs e gráficos (36 execuções da Etapa 1).
python scripts/run_experiment.py --stage stage1 --pilot-runs 3
python scripts/analyze.py --stage stage1 --input results/pilot-stage1-3
```

Para a reprodução cruzada de piloto da Etapa 2, deve existir o piloto da Etapa 1 com o mesmo número de runs. O analisador exige pelo menos dois runs por célula; o piloto de um run serve apenas para validar execução, fluxos, traces e manifestos.

### Lotes oficiais

O mínimo oficial é cinco runs por célula; a configuração padrão usa os intervalos 1–10 e 1–30. O lote da Etapa 2 requer uma Etapa 1 oficial completa para conferir a reprodução das runs 1–10 a 10 pacotes/s.

```bash
python scripts/run_experiment.py --stage stage1 --jobs 3
python scripts/analyze.py --stage stage1
python scripts/run_experiment.py --stage stage2 --jobs 3
python scripts/analyze.py --stage stage2
```

`--jobs N` controla o paralelismo. O lote oficial só inicia com o código commitado e recusa retomar uma saída iniciada em outra revisão. A execução é retomável quando a saída e a configuração correspondem; saídas incompatíveis são recusadas para evitar sobrescrita acidental. Estime a duração pelo piloto antes de iniciar: neste ambiente, com `--jobs 3`, a Etapa 1 levou cerca de 8 minutos e a Etapa 2, cerca de 42 minutos.

### Animações

```bash
python scripts/run_experiment.py --stage stage1 --animation
```

O conjunto tem 12 XMLs: uma run, quatro velocidades e três protocolos. O simulador usa `AnimationInterface` e `SetMaxPktsPerTraceFile` para segmentar traces grandes. Para compilar o aplicativo NetAnim separado, use Qt 5 e siga a receita compatível com ns-3.39. Animações são apenas visuais e ficam sob `results/`.

## Saídas e versionamento

- Dados brutos oficiais: `experiments/manet-routing/data/raw/stage1/` e `stage2/` — manifestos, CSVs por fluxo, traces de mobilidade e XMLs FlowMonitor comprimidos e log de progresso (`progress.log`).
- Dados processados: `experiments/manet-routing/data/processed/<etapa>/` — `results.csv`, `summary.csv`, `h1-results.csv`, `h1-summary.md`, `connectivity.csv` e, na Etapa 2, `load-trend.csv` e `load-effect.md`.
- Figuras: `experiments/manet-routing/figures/<etapa>/` — seis PNGs por etapa (quatro métricas e tráfego de controle), com unidades e ICs, e o painel 2 × 2 para o artigo (`panel.pdf` e `panel.png`).
- Pilotos e animações: `results/`, fora do Git. `python scripts/range_check.py` regenera a tabela do teste de alcance em `results/range-check/`.

Antes de publicar os dados, confira o tamanho e os manifestos. Eles registram versão do ns-3, revisão, perfil de build, data e hora, seed, run, comando, configuração e hash da trajetória, calculado sobre o conteúdo descomprimido.
