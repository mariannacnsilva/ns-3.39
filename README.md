# Simulação de protocolos de roteamento MANET com ns-3

Este projeto compara AODV, OLSR e DSDV em uma rede móvel ad hoc (MANET).
O script de lote executa um cenário-base e varia um fator por vez: número
de nós, área, velocidade máxima e pausa da mobilidade. Cada simulação gera
tráfego UDP entre os nós 0 e 1, estatísticas FlowMonitor e uma trajetória
de mobilidade usada para calcular a vizinhança.

## Compilar

Na raiz do ns-3, onde está o executável `ns3`, configure e compile:

```shell
./ns3 configure --enable-examples
./ns3
```

## Executar um experimento individual

Para executar um único protocolo:

```shell
./ns3 run scratch/experimento-aodv-demo
./ns3 run scratch/experimento-olsr-demo
./ns3 run scratch/experimento-dsdv-demo
```

Os programas aceitam parâmetros como `--seed`, `--nodes`, `--areaWidth`,
`--areaHeight`, `--speed` e `--pause`. Exemplo:

```shell
./ns3 run "scratch/experimento-aodv-demo --seed=7 --nodes=40 --areaWidth=1000 --areaHeight=1000 --speed=5 --pause=10"
```

## Matriz de condições de rede

O script `scratch/run_condicoes_rede.py` executa o cenário-base e variações
de um fator por vez. Todos os cenários duram 180 s, seguidos de 10 s para
drenar pacotes em trânsito.

| Cenário | Nós | Área (m²) | Velocidade máx. (m/s) | Pausa (s) | Densidade (nós/km²) |
|---|---:|---:|---:|---:|---:|
| Base | 40 | 1000 × 1000 | 5 | 10 | 40,00 |
| Número de nós baixo | 20 | 1000 × 1000 | 5 | 10 | 20,00 |
| Número de nós alto | 60 | 1000 × 1000 | 5 | 10 | 60,00 |
| Área pequena | 40 | 500 × 500 | 5 | 10 | 160,00 |
| Área grande | 40 | 1500 × 1500 | 5 | 10 | 17,78 |
| Velocidade baixa | 40 | 1000 × 1000 | 1 | 10 | 40,00 |
| Velocidade alta | 40 | 1000 × 1000 | 10 | 10 | 40,00 |
| Velocidade muito alta | 40 | 1000 × 1000 | 20 | 10 | 40,00 |
| Sem pausa | 40 | 1000 × 1000 | 5 | 0 | 40,00 |
| Pausa longa | 40 | 1000 × 1000 | 5 | 30 | 40,00 |

A densidade é o número de nós dividido pela área em km². O grau médio de
vizinhança é calculado a partir das posições registradas a cada segundo;
dois nós contam como vizinhos quando estão a até 200 m. Para cada cenário
e seed, o mesmo arquivo de mobilidade é usado nos três protocolos. O script
compara hashes das trajetórias para confirmar que são idênticas. O canal
aplica um alcance máximo de 200 m e um modelo de perda LogDistance; o grau
é geométrico e não garante que cada enlace consiga decodificar pacotes.

### Parâmetros de rádio documentados

| Parâmetro | Configuração |
|---|---|
| Versão do ns-3 | 3.39 |
| Padrão Wi-Fi | IEEE 802.11b |
| Modo/taxa de dados e controle | DSSS 1 Mbps (`DsssRate1Mbps`) |
| Potência de transmissão | 20 dBm, fixa |
| Sensibilidade de recepção configurada | −101 dBm |
| Perda de propagação | `RangePropagationLossModel` (200 m), seguido de `LogDistancePropagationLossModel` (expoente 2; referência de 40,05 dB a 1 m para 2,4 GHz). O helper `YansWifiChannelHelper::Default()` usa LogDistance e ConstantSpeed; aqui os modelos são configurados explicitamente para colocar o limite de alcance antes da perda |
| Atraso de propagação | `ConstantSpeedPropagationDelayModel` |
| RTS/CTS | Desativado para os pacotes do experimento (`RtsCtsThreshold=65535`) |
| MAC | `AdhocWifiMac` |
| Seeds | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 |

### Executar as 300 simulações

Na raiz do ns-3, rode:

```shell
python3 scratch/run_condicoes_rede.py
```

O comando executa 10 cenários × 3 protocolos × 10 seeds = 300 simulações.
Os resultados ficam em `results/condicoes-rede/`:

- `resultados.csv`: fluxos de ida e volta, perdas, atraso e tráfego de controle;
- `manifesto.csv`: parâmetros, densidade, grau médio, versão e seeds;
- um CSV de mobilidade para cada combinação cenário/seed;
- um XML FlowMonitor para cada execução.

NetAnim fica desativado no lote para evitar 300 arquivos grandes. Em uma
execução individual, use `--animation=true` para gerar a animação.

Para validar três execuções antes do lote completo, use:

```shell
python3 scratch/run_condicoes_rede.py --seeds 1 --limit 3 --output results/teste
```

Para a lista padrão de seeds, o script usa os valores de 1 a 10. É possível
especificar outra lista, por exemplo `--seeds 11,12,13`. Consulte a
[documentação oficial do ns-3](https://www.nsnam.org/documentation/) para
detalhes dos modelos.