# Comparação de roteamento MANET com ns-3.39

## Objetivo

Investigar a hipótese **H1**: aumentar a velocidade de mobilidade pode piorar atraso, jitter, vazão e/ou PDR em uma MANET. O estudo compara os resultados de AODV, DSDV e OLSR sem declarar um protocolo vencedor. As conclusões são limitadas ao cenário e aos parâmetros descritos aqui.

## Guia rápido: o que o experimento faz

Uma MANET é uma rede sem ponto de acesso central: os nós móveis enviam dados e podem encaminhar pacotes uns dos outros. O ns-3 simula os nós, o rádio, o movimento e o roteamento. O experimento envia quatro fluxos UDP entre pares fixos e mede os pacotes observados no destino.

- **AODV** descobre rotas sob demanda; **DSDV** e **OLSR** mantêm informações de rota proativamente.
- **PDR** é a porcentagem de pacotes transmitidos que chegaram ao destino.
- **Vazão** é o número de bits recebidos dividido pela janela útil da aplicação.
- **Atraso** é o tempo médio entre envio e recepção dos pacotes entregues.
- **Jitter** é a variação média do atraso entre recepções consecutivas.

## Cenário experimental

Os parâmetros executáveis ficam em `config/experiment.json`. Os manifestos preservam a configuração e a revisão usadas.

| Parâmetro | Etapa 1 — base | Etapa 2 — carga |
|---|---|---|
| Nós e área | 20 nós em 500 × 500 m | Igual à Etapa 1 |
| Rádio | IEEE 802.11g ad hoc, 2,4 GHz, canal 1, largura 20 MHz, taxa PHY fixa de 6 Mbps | Igual à Etapa 1 |
| Propagação | YANS com LogDistance; expoente 3, perda de referência 40,05 dB a 1 m | Igual à Etapa 1 |
| Mobilidade | RandomWaypoint; velocidade mínima 1 m/s, pausa 10 s; velocidade máxima 1, 5, 10 e 20 m/s | Igual à Etapa 1 |
| Aplicação | 4 fluxos UDP: 0→1, 2→3, 4→5 e 6→7; payload de 512 bytes | Mesmos fluxos e payload |
| Taxa | 10 pacotes/s por fluxo | 10 e 100 pacotes/s por fluxo |
| Duração | 120 s; tráfego entre 10 e 110 s; janela útil de 100 s e 10 s de escoamento | Igual à Etapa 1 |
| Runs | Runs 1–10 | Runs 1–30 |
| Execuções | 3 protocolos × 4 velocidades × 10 runs = **120** | 3 protocolos × 4 velocidades × 2 cargas × 30 runs = **720** |

A Etapa 2 altera apenas a carga oferecida. Em ambas, a posição inicial usa stream 10, a mobilidade usa streams atribuídos a partir de 1000, a seed mestre é 12345 e o run é passado a `RngSeedManager::SetRun`. Para uma mesma velocidade/run, os protocolos e cargas devem ter trajetórias iguais, conferidas pelo SHA-256 do trace. As runs 1–10 da Etapa 2 a 10 pacotes/s também são comparadas com a Etapa 1 para confirmar reprodução exata dos dados por fluxo.

### Métricas

As métricas são calculadas por fluxo e agregadas por execução, somando pacotes e bytes:

- **Vazão (Mbps)** = `8 × rxBytes / (100 × 10⁶)`. `rxBytes` do FlowMonitor inclui cabeçalhos IP e UDP.
- **PDR (%)** = `100 × rxPackets / txPackets`.
- **Atraso médio (ms)** = `delaySum / rxPackets`; ausente se não houver recepção.
- **Jitter médio (ms)** = `jitterSum / (rxPackets − 1)`; ausente se houver menos de duas recepções.

Na agregação de uma execução, atraso é ponderado pelo total de pacotes recebidos; jitter, pelo total de pares consecutivos recebidos em cada fluxo. A vazão usa a janela fixa de 100 s, não o tempo entre o primeiro e o último pacote recebido. O analisador informa média, desvio-padrão, IC t de 95% e quantidade válida por célula.

### Decisão de H1

Para cada protocolo, métrica e carga, compara-se o IC de 95% a 1 m/s com o IC a 20 m/s:

- **Sustentada:** os ICs não se sobrepõem no sentido de piora — atraso/jitter aumentam, ou vazão/PDR diminuem.
- **Melhora:** os ICs não se sobrepõem na direção oposta.
- **Inconclusiva:** os ICs se sobrepõem ou não há amostra válida para calcular os intervalos.

Não são feitos testes estatísticos entre protocolos. As quatro figuras de cada etapa apresentam uma série por protocolo (e, na Etapa 2, por carga), com barras de IC de 95%.

### Checagem de carga a 100 pacotes/s

A carga oferecida por quatro fluxos é 1,6384 Mbps de payload. Considerando cabeçalhos IPv4/UDP, são aproximadamente 1,728 Mbps na camada IP, frente à taxa PHY configurada de 6 Mbps. Essa razão não mede airtime: preâmbulos, contenção, retransmissões e tráfego de roteamento também consomem o canal. O relatório da Etapa 2 registra a comparação descritiva de PDR e atraso entre 10 e 100 pacotes/s como checagem de indícios de contenção, sem afirmar saturação só com base na taxa nominal.

## Preparação do ambiente

O build e as simulações devem ser executados em Ubuntu 22.04/24.04, nativo ou via WSL2 no Windows. Requisitos: g++, CMake, Ninja ou Make, Python 3 e dependências do `requirements.txt`. Qt 5 é necessário apenas para compilar/abrir o visualizador NetAnim.

### Hardware e software do ambiente inventariado

Inventário da máquina disponível para este projeto em 4 de novembro de 2026. **O build do ns-3 e os pilotos ainda não foram concluídos com sucesso**, portanto estes dados descrevem o ambiente configurado, não uma execução experimental validada. Atualize esta seção caso os experimentos sejam executados em outra máquina ou com versões diferentes.

| Componente | Especificação |
|---|---|
| Computador | Acer Nitro ANV15-51 |
| Processador | 13th Gen Intel Core i7-13620H; 10 núcleos, 16 processadores lógicos |
| Memória | 15,7 GB RAM (aprox. 16 GB) |
| Sistema host | Windows 10 Home 25H2, build 26200 |
| Ambiente de build | WSL 2, Ubuntu 24.04.1 LTS (Noble Numbat) |
| ns-3 | 3.39 (versão do código-fonte em `VERSION`; build ainda pendente) |
| Python | 3.12.3 no WSL; ambiente virtual `.venv` |
| Compilador C++ | g++ 13.3.0 |
| CMake | 3.28.3 |
| Ninja | 1.11.1 |
| Dependências Python observadas | NumPy 2.5.4, pandas 3.1.0, SciPy 1.18.1 e Matplotlib 3.11.2 |

Qt 5 e NetAnim são opcionais e não foram considerados necessários para executar as métricas; servem somente para compilar/visualizar as animações.

```bash
sudo apt update
sudo apt install -y git g++ cmake ninja-build python3 python3-venv python3-pip pkg-config
sudo apt install -y qtbase5-dev qt5-qmake  # opcional: NetAnim

git clone https://github.com/mariannacnsilva/ns-3.39.git
cd ns-3.39
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
./ns3 configure --enable-examples
./ns3 build scratch_manet-routing-compare
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

### Lotes oficiais — executar somente após autorização

O mínimo oficial é cinco runs por célula; a configuração padrão usa os intervalos 1–10 e 1–30. O lote da Etapa 2 requer uma Etapa 1 oficial completa para conferir a reprodução das runs 1–10 a 10 pacotes/s.

```bash
python scripts/run_experiment.py --stage stage1 --jobs 4
python scripts/analyze.py --stage stage1
python scripts/run_experiment.py --stage stage2 --jobs 4
python scripts/analyze.py --stage stage2
```

`--jobs N` controla o paralelismo. A execução é retomável quando a saída e a configuração correspondem; saídas incompatíveis são recusadas para evitar sobrescrita acidental. Não execute lotes oficiais até estimar duração e obter autorização.

### Animações

```bash
python scripts/run_experiment.py --stage stage1 --animation
```

O conjunto tem 12 XMLs: uma run, quatro velocidades e três protocolos. O simulador usa `AnimationInterface` e `SetMaxPktsPerTraceFile` para segmentar traces grandes. Para compilar o aplicativo NetAnim separado, use Qt 5 e siga a receita compatível com ns-3.39. Animações são apenas visuais e ficam sob `results/`.

## Saídas e versionamento

- Dados brutos oficiais: `experiments/manet-routing/data/raw/stage1/` e `stage2/` — manifestos, CSVs por fluxo, traces de mobilidade e XMLs FlowMonitor.
- Dados processados: `experiments/manet-routing/data/processed/<etapa>/` — `flows.csv`, `results.csv`, `summary.csv`, `h1-results.csv`, `h1-summary.md` e, na Etapa 2, `saturation-check.md`.
- Figuras: `experiments/manet-routing/figures/<etapa>/` — quatro PNGs por etapa, com unidades e ICs.
- Pilotos e animações: `results/`, ignorado pelo Git.

O runner estima o tamanho a partir de dados realmente observados nos pilotos e pode compactar XMLs FlowMonitor se o lote oficial projetado ultrapassar 50 MiB. Antes de publicar os dados, confira o tamanho e os manifestos. Eles registram versão do ns-3, revisão, seed, run, comando, configuração e hash da trajetória.
