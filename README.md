# Redes Móveis 2026/2 — comparação de AODV, OLSR e DSDV

## Objetivo

Comparar, sob condições reproduzíveis de mobilidade, como AODV, OLSR e DSDV se comportam em **PDR, throughput, atraso e jitter**. A Etapa 2 acrescenta uma única variável experimental — taxa de tráfego por fluxo — e avalia também o overhead de controle. Métricas são analisadas separadamente; não há nota única nem declaração de vencedor além do que os dados sustentam. Toda interpretação é **limitada às condições simuladas**.

## Versão do ns-3 e revisão

- ns-3: **3.39** (arquivo `VERSION`).
- Revisão exata: obtida por leitura de `git rev-parse HEAD` e `git describe --always --dirty` e gravada no manifesto raiz e nos manifestos de execução. O repositório ns-3 também é o repositório do projeto neste checkout; ambos os campos indicam a mesma revisão. Não fixe um hash neste README, pois os resultados devem registrar a revisão do checkout que os produziu.
Commit da versão do artigo: <preencher após o commit final>

## Sistema operacional, compilador e dependências

Suporte documentado para Ubuntu 22.04/24.04 (nativo ou WSL2 no Windows 10/11), Python 3.10+ e toolchain C++17: g++, CMake, Ninja/Make e ferramentas necessárias ao ns-3.39. No Windows, execute build/simulações no Ubuntu do WSL; PowerShell serve para testes Python se as dependências estiverem instaladas, mas a compilação nativa no Windows não está validada. Para abrir animações, instale Qt 5 e o visualizador NetAnim compatível com ns-3.39.

### Clonar e preparar ambiente

No terminal Ubuntu/WSL:

```bash
sudo apt update
sudo apt install -y git g++ cmake ninja-build python3 python3-venv python3-pip pkg-config
# Qt é opcional para simular e necessário para abrir as animações com NetAnim.
sudo apt install -y qtbase5-dev qt5-qmake

git clone https://github.com/mariannacnsilva/ns-3.39.git
cd ns-3.39
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### Configurar e compilar

Na raiz do repositório, com o ambiente virtual ativado:

```bash
./ns3 configure --enable-examples
./ns3 build scratch_manet-routing-compare
```

A animação no simulador usa `AnimationInterface`, incluída no ns-3. Para compilar o aplicativo NetAnim separado, configure CMake com `-DNS3_NETANIM=ON` e compile conforme a versão Qt disponível:

```bash
cmake -S . -B cmake-cache -DNS3_NETANIM=ON
cmake --build cmake-cache
```

## Etapas e parâmetros

Todos os parâmetros variáveis ficam em `config/experiment.json`. Os manifestos salvam uma cópia e seu hash. A Etapa 2 herda o cenário-base e altera **somente a taxa UDP por fluxo**; o overhead é uma métrica adicional, não uma variável do cenário.

| Etapa | Nós e área | Wi-Fi fixo | Mobilidade | Fluxos UDP | Velocidade máxima | Taxas/run | Duração total / útil | Runs | Execuções completas |
|---|---|---|---|---|---|---|---|---:|---:|
| 1 — Base | 20; 500 × 500 m | 802.11g, canal 1/2,4 GHz, 20 MHz, modo fixo 6 Mbps | RandomWaypoint; posição uniforme; pausa 10 s; mínima 1 m/s | 4 pares fixos: 0→1, 2→3, 4→5, 6→7; UDP 512 B | 1, 5, 10, 20 m/s | 10 pps/fluxo | 120 s / 100 s; tráfego 10–110 s e 10 s de drenagem | 10 | 3 × 4 × 10 = **120** |
| 2 — Extensão de carga | Herda Etapa 1 | Idêntico à Etapa 1 | Idêntico à Etapa 1 | Os mesmos 4 fluxos | 1, 5, 10, 20 m/s | 10 e 100 pps/fluxo | Idêntico à Etapa 1 | 10 | 3 × 4 × 2 × 10 = **240** |
| 3 — Complementar | 10; 100 × 50 m | 802.11p, canal 172/5,86 GHz, 10 MHz, 3 Mbps fixos | RandomWaypoint; uniforme; pausa 10 s; mínima 1 m/s | 1 fluxo 0→1; UDP 512 B | 1, 2, 10, 20 m/s | 10 e 100 pps | 180 s / 160 s; tráfego 10–170 s | 30 | 3 × 4 × 2 × 30 = **720** |

A Etapa 1 usa 802.11g em 2,4 GHz com 6 Mbps fixos, em vez de 802.11p: é um padrão comum de WLAN ad hoc, com canal de 20 MHz, apropriado para comparar protocolos de roteamento em uma MANET genérica. A Etapa 2 mantém exatamente esse padrão e modo para isolar a carga como variável adicional. Os parâmetros de roteamento AODV/OLSR/DSDV permanecem padrão. Modelos de propagação e valores fixos adicionais estão descritos no JSON.

| Parâmetro | Significado e unidade | Padrão / valor |
|---|---|---:|
| `seed_master` | Seed mestre do gerador aleatório | 12345 |
| `run` | Repetição independente (`RngSeedManager::SetRun`) | 1–10 (Etapas 1/2); 1–30 (Etapa 3) |
| `nodes` | Número de nós | 20 (Etapas 1/2); 10 (Etapa 3) |
| `area_width_m`, `area_height_m` | Largura e altura do campo | 500 × 500 m; 100 × 50 m na Etapa 3 |
| `minimum_speed_mps` | Velocidade mínima do RandomWaypoint | 1 m/s |
| `pause_s` | Pausa do RandomWaypoint | 10 s |
| `maximum_speeds_mps` | Velocidades máximas do estudo | Etapas 1/2: 1, 5, 10, 20 m/s; Etapa 3: 1, 2, 10, 20 m/s |
| `flow_pairs` | Pares de nós, origem → destino | 0→1, 2→3, 4→5, 6→7; Etapa 3 0→1 |
| `rate_pps` | Taxa por fluxo UDP | Etapa 1: 10; Etapa 2: 10 e 100; Etapa 3: 10 e 100 pacotes/s |
| `packet_size_bytes` | Payload UDP | 512 B |
| `duration_s` | Duração da simulação incluindo drenagem | 120 s; Etapa 3: 180 s |
| `traffic_start_s`, `traffic_stop_s` | Intervalo de geração | 10–110 s; Etapa 3: 10–170 s |
| `useful_duration_s` | Janela usada no throughput | 100 s; Etapa 3: 160 s |
| `wifi_mode` | Taxa PHY constante (dados e controle) | 802.11g: 6 Mbps; 802.11p: 3 Mbps |
| `channel_number` / largura | Canal de rádio / MHz | Etapa 1/2: 1 / 20 MHz; Etapa 3: 172 / 10 MHz |
| `tx_power_dbm` | Potência de transmissão | 16 dBm (Etapas 1/2); 20 dBm (Etapa 3) |
| Ganho TX/RX | Ganho de antena em dB | 0 / 0 dB |
| `rx_sensitivity_dbm` | Sensibilidade de recepção | −101 dBm |
| `rts_cts_threshold_bytes` | Limiar de ativação RTS/CTS | 65535 B |
| `propagation_delay` | Modelo de atraso de propagação | ConstantSpeedPropagationDelayModel |
| `range_m` | Limite de alcance, se diferente de zero | Desativado (Etapas 1/2); 50 m (Etapa 3) |
| LogDistance | Expoente e perda de referência a 1 m | Etapas 1/2: 3 e 40,05 dB; Etapa 3: 2 e 47,86 dB |
| Streams | Posição inicial / mobilidade | 10 / 1000 |
| `repetitions` | Runs independentes por célula | 10; mínimo 5 validado; 30 na Etapa 3 |

### Aleatoriedade e repetição

O programa chama `RngSeedManager::SetSeed(seed_master)` e `RngSeedManager::SetRun(run)`. O stream 10 é reservado às posições iniciais uniformes e os streams de mobilidade são atribuídos explicitamente a partir de 1000; não dependem da taxa nem do protocolo. Assim, para cada par velocidade/run, os três protocolos e todas as taxas compartilham a mesma trajetória. O executor calcula SHA-256 do trace, confere os hashes entre execuções e grava-os nos manifestos/CSV. `seed` nas tabelas é a seed mestre; `run` identifica a repetição. Runs oficiais são 1..N. O programa recusa menos de cinco repetições em perfis oficiais; pilotos temporários podem usar 1 ou 3 para validação.

## Um cenário, pilotos e lotes

A partir da raiz do ns-3:

**Uma execução isolada** (não é conjunto para análise estatística):

```bash
python scripts/run_experiment.py --stage stage1 --protocol aodv --speed 5 --rate 10 --run 1
```

**Piloto curto da Etapa 1**, uma repetição por célula (12 execuções), em `results/pilot-stage1-1/`:

```bash
python scripts/run_experiment.py --stage stage1 --pilot --dry-run
python scripts/run_experiment.py --stage stage1 --pilot
```

**Piloto de três runs**, para exercitar IC/testes/gráficos (36 execuções da Etapa 1):

```bash
python scripts/run_experiment.py --stage stage1 --pilot-runs 3
python scripts/analyze.py --stage stage1 --input results/pilot-stage1-3
```

O piloto de apenas um run é intencionalmente rejeitado pelo analisador. O piloto de três runs é analisável, mas não é lote oficial e não deve ser misturado a dados oficiais.

**Etapa 1 oficial — 120 execuções:**

```bash
python scripts/run_experiment.py --stage stage1 --dry-run
python scripts/run_experiment.py --stage stage1
python scripts/analyze.py --stage stage1
```

**Etapa 2 oficial — 240 execuções:**

```bash
python scripts/run_experiment.py --stage stage2 --dry-run
python scripts/run_experiment.py --stage stage2
python scripts/analyze.py --stage stage2
```

**Etapa 3 complementar — 720 execuções** (não executar sem decisão do grupo):

```bash
python scripts/run_experiment.py --stage stage3 --dry-run
python scripts/run_experiment.py --stage stage3
python scripts/analyze.py --stage stage3
```

O runner mostra progresso e pode retomar apenas outputs completos do mesmo perfil. Uma pasta preexistente incompatível é recusada; escolha outro `--output`. Paralelismo opcional: `--jobs 4`. Lote completo não foi nem deve ser executado durante validações rápidas.

## Métricas e estatística

`flows.csv` contém uma linha por run/fluxo, com `stage, protocol, speed, rate, run, seed, flowId, txPackets, rxPackets, lostPackets, rxBytes, throughputMbps, pdrPct, delayMs, jitterMs`, além dos campos auxiliares de soma, p95, controle e hash. O `results.csv` tem uma linha por execução: soma tx/rx/perdas/bytes dos fluxos, PDR agregada, throughput, atraso e jitter ponderados, p95, overhead e hash.

- **Throughput (Mbps)** = $rxBytes \times 8 / duração\ útil / 10^6$. `rxBytes` do FlowMonitor inclui cabeçalhos IP/UDP; o throughput dos gráficos é esta métrica, conforme o enunciado.
- **PDR (%)** = $rxPackets / txPackets \times 100$. `lostPackets` é reportado separadamente.
- **Atraso (ms)** = `delaySum / rxPackets`. Sem pacote recebido, é ausente (CSV vazio/NaN), nunca zero.
- **Jitter (ms)** = `jitterSum / (rxPackets − 1)` por fluxo. Com zero ou um pacote recebido, é ausente. Na execução, atraso é ponderado por pacotes recebidos; jitter combinado usa o total de amostras de pares consecutivos por fluxo.
- **P95** por fluxo é estimado pelo centro do bin do histograma FlowMonitor. No `results.csv` por execução, o p95 reportado é uma aproximação ponderada pelos pacotes recebidos dos p95 dos fluxos, não o percentil exato da união das amostras; fica explicitamente separado da média exata.
- **Overhead** (Etapa 2 e adicionalmente nas demais saídas) conta datagramas UDP da porta de controle de AODV/DSDV/OLSR na camada Tx IPv4. Inclui pacotes/bytes de controle, bytes de controle por byte útil (payload recebido) e pacotes por pacote entregue; não mede airtime ou energia.

O analisador valida duração útil, completude de fluxo/run/célula, XML, seed, configuração e hashes. Rejeita rx > tx, perdas > tx, divisão por zero, PDR fora de 0–100%, atraso/jitter negativos, duplicatas e faltantes. Fluxos sem recepção são válidos como resultado de rede: PDR 0 e atraso/jitter ausentes, com aviso claro. Médias excluem valores ausentes e informam `n_valid`.

As médias, desvios padrão e IC 95% usam t de Student. Comparações são pareadas pelo run. Com menos de 10 pares, o analisador apresenta IC e não declara significância por teste; com 10 ou mais usa t pareado e correção de Holm nas comparações múltiplas. Isso evita interpretar p-valores pouco informativos em amostras pequenas. Os resultados também imprimem tendências por velocidade, ponto de maior degradação e contagem de ICs sobrepostos entre protocolos. Texto neutro, sem eleger “melhor” protocolo. Uma afirmação de entrega confiável deve respeitar `minimum_reliable_pdr_pct` definido previamente no JSON.

## Dados, figuras, logs e animações

Dados oficiais ficam separados por etapa e são destinados ao versionamento:

- `experiments/manet-routing/data/raw/<stage>/`: `manifest.json`, cópia de `config.json`, `flows.csv`, XML FlowMonitor, traces de mobilidade e manifesto/CSV por run.
- `experiments/manet-routing/data/processed/<stage>/`: `flows.csv`, `results.csv`, `summary.csv` e `paired-tests.csv`.
- `experiments/manet-routing/figures/<stage>/`: PNGs com barras de IC 95% e unidades. Etapa 2 gera arquivos por taxa.
- `results/`: pilotos, execução isolada e animações; ignorados pelo Git. `--animation` gera 1 run × 4 velocidades × 3 protocolos = **12 XMLs** do perfil-base; não escreve em `data/` nem é analisado.

Para gerar as animações:

```bash
python scripts/run_experiment.py --stage stage1 --animation --dry-run
python scripts/run_experiment.py --stage stage1 --animation
```

Os XMLs ficam em `results/animation-stage1/animation/<velocidade>/<protocolo>/run-1.xml`. Abra no NetAnim por **File > Open XML**. Nó 0/origem é vermelho; nó 1/destino azul; os outros são amarelos. Descrições identificam protocolo, velocidade, taxa/run. `AnimationInterface` habilita metadados e captura de tabela de rotas IPv4 quando suportado. O runner compara o hash da trajetória visual com uma execução sem animação. Se não existir baseline oficial completa, cria uma execução baseline temporária separada sob `results/animation-stage1/baseline/`.

Reduza a janela de animação ou o limite de pacotes no perfil para controlar XML grande; reproduza em velocidade menor para observar mobilidade. Se a tela estiver vazia, confirme que abriu XML da pasta `animation`, que o playback está entre 10 e 110 s e que não abriu o XML FlowMonitor. Sem pacotes visíveis, confira filtros e janela do playback. Falha de abertura costuma indicar versão NetAnim/Qt incompatível.

Após cada piloto, o runner mede o volume observado e projeta o tamanho oficial pela razão entre runs esperados e realizados, registrando ambos no manifesto e imprimindo a estimativa. Se a projeção passar de 50 MiB, o lote oficial grava os XMLs FlowMonitor em gzip; se não houver piloto prévio, mede ao terminar e compacta caso o limite seja ultrapassado. O analisador lê XML normal ou gzip. CSVs, manifestos, traces/hash e figuras permanecem preservados. Não se estima tamanho de dados ainda não gerados como se fosse medição.

## Como interpretar os resultados

- **PDR** mostra a porcentagem de pacotes entregues. Um PDR baixo significa que muitos pacotes não chegaram.
- **Throughput** mede quantos bits recebidos por segundo o FlowMonitor observou durante a janela útil. Inclui cabeçalhos IP/UDP; por isso não é exatamente payload útil.
- **Atraso** mede quanto tempo os pacotes recebidos levaram, em média, da origem ao destino. **Jitter** resume a variação do atraso entre chegadas consecutivas.
- Barras de erro largas indicam maior incerteza entre runs. ICs sobrepostos não provam igualdade; ICs não sobrepostos, sozinhos, também não substituem o teste pareado.
- A Etapa 2 permite observar se a carga altera métricas e overhead mantendo o restante do cenário. Resultado nenhum deve ser generalizado para redes maiores ou outros parâmetros.
- H1: avaliar se a mobilidade crescente acompanha atraso maior e/ou PDR menor. H2: avaliar diferenças entre protocolos sob as mesmas seeds/trajetórias. H3: comparar os custos de controle. Se os intervalos não derem evidência suficiente, escrever “inconclusivo”.

### Glossário

- **MANET:** rede móvel ad hoc, sem infraestrutura central fixa.
- **AODV:** roteamento sob demanda; busca rotas quando necessário.
- **OLSR:** roteamento proativo com retransmissores multiponto.
- **DSDV:** roteamento proativo por vetor de distâncias sequenciado.
- **PDR:** taxa de entrega de pacotes, expressa em porcentagem.
- **Throughput:** bits recebidos por segundo, conforme a definição do experimento.
- **Goodput:** bits de payload útil recebidos por segundo; diferente de throughput que inclui cabeçalhos.
- **Overhead:** tráfego de controle medido no ponto instrumentado.
- **Seed/run:** seed mestre e repetição determinística do gerador aleatório.
- **NetAnim:** visualizador Qt de XMLs de animação do ns-3.

## Correspondência com o enunciado

| Estrutura indicada | Arquivo deste projeto |
|---|---|
| `src/manet-routing.cc` | `scratch/manet-routing-compare.cc` |
| `run_batch.sh` | `scripts/run_experiment.py` |
| `analyze.py` | `scripts/analyze.py` |
| `data/raw/` | `experiments/manet-routing/data/raw/` |
| `data/processed/` | `experiments/manet-routing/data/processed/` |
| `figures/` | `experiments/manet-routing/figures/` |
| `article/` | Será criado pelo grupo; não faz parte deste repositório por enquanto. |

## Checklist de reprodução

- [ ] Registrar nomes do grupo e revisar a pergunta/hipóteses dos slides.
- [ ] Clonar checkout do ns-3.39, instalar compilador/Python/Qt necessários e guardar revisão reportada pelo manifesto.
- [ ] Conferir `config/experiment.json`; não reduzir abaixo de cinco runs oficiais.
- [ ] Configurar/compilar `scratch_manet-routing-compare`.
- [ ] Rodar piloto da Etapa 1 e testar hashes, 4 fluxos, jitter e CSVs.
- [ ] Rodar piloto de três runs e analisar para exercitar ICs e gráficos.
- [ ] Executar lote oficial das Etapas 1 e 2 somente quando autorizado; Etapa 3 é complementar e opcional.
- [ ] Executar `scripts/analyze.py` separadamente para cada etapa e revisar métricas/síntese sem misturar pilotos.
- [ ] Verificar tamanho dos dados, figuras e manifestos; versionar CSVs, XMLs brutos dentro do limite acordado e PNGs.
- [ ] Preencher “Commit da versão do artigo” somente após o commit final realizado pelo grupo.

A especificação anterior do repositório permanece em `docs/ESPECIFICACAO.md` sem alteração; ela descreve um cenário antigo e não é a fonte de parâmetros deste estudo.