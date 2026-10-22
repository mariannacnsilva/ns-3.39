# Experimento comparativo de roteamento MANET

## Objetivo

Comparar o comportamento de AODV, DSDV e OLSR em um cenário Wi-Fi ad hoc com mobilidade e tráfego UDP Echo.

## Estrutura

- `config/experiment.json`: parâmetros comuns e protocolos disponíveis.
- `scripts/run-experiment.py`: compila e executa um cenário, preservando a configuração e os resultados.
- `scripts/summarize-results.py`: converte os XMLs do FlowMonitor em um resumo tabular.
- `results/raw/`: resultados XML gerados diretamente pela simulação.
- `results/processed/`: métricas e relatórios derivados.
- `results/animations/`: animações selecionadas do NetAnim.

## Requisitos

- Linux com compilador C++ e ferramentas de compilação do ns-3.
- ns-3.39 em uma das árvores suportadas pelo projeto.
- Python 3.10 ou superior.
- Qt e bibliotecas de NetAnim apenas para abrir animações.

## Execução rápida

A partir da raiz do ns-3.39:

```bash
./ns3 configure --enable-examples
./experiments/manet-routing/scripts/run-experiment.py --protocol all
./experiments/manet-routing/scripts/summarize-results.py \
  --input experiments/manet-routing/results/raw
```

O script de execução usa a seed configurada em `config/experiment.json` e produz uma pasta por protocolo.

## Entendendo os resultados

Os arquivos `results/raw/` contêm os XMLs gerados pelo FlowMonitor. Cada XML registra:

- fluxo de origem e destino;
- pacotes transmitidos, recebidos e perdidos;
- atraso, jitter e tamanho de pacote;
- histogramas de atraso, jitter, fluxos interrompidos e tamanho;
- estatísticas por sonda e por fluxo.

O resumo processado organiza as métricas principais por protocolo:

- taxa de entrega;
- taxa de perda;
- atraso médio;
- jitter médio;
- bytes recebidos;
- taxa de encaminhamento;
- número de saltos estimado.

## Comparação e interpretação

A comparação deve usar a mesma topologia, a mesma carga UDP, a mesma direção da comunicação e a mesma quantidade de seeds para cada protocolo. O resultado de uma única execução não deve ser considerado conclusivo.

Para cada valor do CSV processado, deve ser possível localizar:

1. o protocolo e a seed;
2. a versão do ns-3;
3. os parâmetros do cenário;
4. o arquivo XML bruto;
5. a fórmula usada para obter a métrica.

## Limitações conhecidas

- A mobilidade usa um gerador aleatório e não possui uma seed explícita no código dos cenários originais.
- Os resultados atuais foram produzidos por execuções anteriores e devem ser registrados como artefatos históricos, não como referência permanente.
- Os resultados do AODV possuem um arquivo geral `resultado-flowmonitor.xml`; a organização nova deverá atribuir a ele um prefixo explícito de protocolo e seed.
- O parser do FlowMonitor do exemplo ns-3 não é uma API oficial para todos os cenários e deve ser validado com cada novo XML.
