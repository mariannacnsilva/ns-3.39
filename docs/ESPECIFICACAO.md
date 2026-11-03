# Metodologia do experimento

## Cenário

O cenário simula uma MANET com:

- 30 nós em uma área de 100 m por 50 m;
- Wi-Fi 802.11b com canal Yans;
- protocolo MAC ad hoc;
- mobilidade com Random Waypoint;
- velocidade uniforme entre 1 m/s e 2 m/s;
- pausa constante de 1 segundo;
- 100 segundos de simulação;
- um cliente em `10.0.0.1` e um servidor em `10.0.0.2`;
- tráfego UDP com 512 bytes, intervalo de 1 segundo e até 1.000 pacotes;
- início das transmissões em 10 segundos;
- roteamento por AODV, DSDV ou OLSR.

## Mecanismo de aleatoriedade

A mobilidade é gerada por `RandomWaypointMobilityModel`. A seed usada no experimento é `12345`.

> A seed deve ser registrada em cada execução e reproduzida em toda a simulação. Uma única execução não deve ser usada para concluir que um protocolo é superior.

## Métricas

Os valores de taxa de entrega, taxa de perda, atraso médio e taxa de recebimento são calculados com base no XML gerado pelo FlowMonitor.

### Taxa de entrega

$$
\text{Taxa de entrega} = \frac{\text{rxPackets}}{\text{txPackets}}
$$

### Taxa de perda

$$
\text{Taxa de perda} = \frac{\text{lostPackets}}{\text{txPackets}}
$$

### Atraso médio

$$
\text{Atraso médio} = \frac{\text{delaySum}}{\text{rxPackets}}
$$

### Taxa de recebimento em bit/s

$$
\text{Taxa de recebimento} = \frac{\text{rxBytes} \times 8}{\text{duração de recepção}}
$$

### Salto estimado

$$
\text{Média de saltos} = \frac{\text{timesForwarded}}{\text{rxPackets}} + 1
$$

## Interpretação do resultado

- "rxPackets" e "txPackets" referem-se ao fluxo de aplicação.
- "lostPackets" corresponde a pacotes transmitidos porém não recebidos dentro do intervalo de perda do FlowMonitor.
- "delaySum" representa a soma dos atrasos end-to-end dos pacotes recebidos.
- "jitter" mede a variação do atraso entre pacotes consecutivos.
- "timesForwarded" representa o número total de encaminhamentos de um pacote até o destino.
- O XML inclui histogramas de atraso, jitter, tamanho e interrupções; estes dados não devem ser reduzidos apenas à média.

## Fraquezas conhecidas

- A cena atual não inclui variações de seed nem múltiplas topologias.
- O valor de `lostPackets` depende da definição de perda usada no FlowMonitor.
- O resultado pode depender da versão e configuração do compilador.
- Os protocolos podem ter parâmetros internos diferentes dos valores padrão; eles devem ser registrados se forem alterados.

## Procedimento para uma nova execução

1. Ajustar os parâmetros no `config/experiment.json`.
2. Executar `run-experiment.py` para o protocolo desejado ou para todos.
3. Confirmar o manifesto `run-metadata.json` dentro de cada pasta por protocolo.
4. Executar `summarize-results.py`.
5. Comparar o CSV processado com o XML bruto correspondente.
6. Registrar a seed e as diferenças de configuração antes de tirar conclusões.
