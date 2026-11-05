#include "ns3/aodv-module.h"
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/dsdv-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/netanim-module.h"
#include "ns3/network-module.h"
#include "ns3/olsr-helper.h"
#include "ns3/wifi-module.h"

#include "experiment-metrics.h"

#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using namespace ns3;

namespace
{
// Parametros fixos do cenario, documentados no README.
const char* const WIFI_MODE = "ErpOfdmRate6Mbps";
const uint16_t APPLICATION_PORT = 9000;

struct Options
{
    std::string stage{"stage1"};
    std::string protocol{"aodv"};
    uint32_t seedMaster{12345};
    uint32_t run{1};
    double speed{1.0};
    uint32_t ratePps{10};
    uint32_t nodes{20};
    uint32_t flowCount{4};
    std::string flowPairs{"0:1;2:3;4:5;6:7"};
    std::string wifiStandard{"802.11g"};
    double areaWidthM{500.0};
    double areaHeightM{500.0};
    double pauseS{10.0};
    double minimumSpeedMps{1.0};
    double durationS{120.0};
    double trafficStartS{10.0};
    double trafficStopS{110.0};
    double txPowerDbm{16.0};
    double rxSensitivityDbm{-101.0};
    double preambleMinRssiDbm{-82.0};
    uint32_t rtsCtsThresholdBytes{65535};
    double referenceLossDb{40.05};
    double referenceDistanceM{1.0};
    double pathLossExponent{2.6};
    uint32_t packetSizeBytes{512};
    int64_t initialPositionStream{10};
    int64_t mobilityStream{1000};
    double mobilityTraceIntervalS{1.0};
    std::string flowsPath{"flows.csv"};
    std::string mobilityPath{"mobility.csv"};
    std::string flowMonitorPath{"flowmonitor.xml"};
    bool animation{false};
    std::string animationPath;
    double animationStartS{0.0};
    double animationStopS{120.0};
    uint64_t maxAnimationPackets{100000};
    double mobilityUpdateS{1.0};
    double routeUpdateS{5.0};
};

std::vector<std::pair<uint32_t, uint32_t>>
ParseFlowPairs(const std::string& value)
{
    std::vector<std::pair<uint32_t, uint32_t>> pairs;
    std::stringstream list(value);
    std::string item;
    while (std::getline(list, item, ';'))
    {
        const auto separator = item.find(':');
        if (separator == std::string::npos)
        {
            throw std::invalid_argument("pares de fluxo devem usar origem:destino;...");
        }
        pairs.emplace_back(static_cast<uint32_t>(std::stoul(item.substr(0, separator))),
                           static_cast<uint32_t>(std::stoul(item.substr(separator + 1))));
    }
    return pairs;
}

bool
Validate(const Options& o, const std::vector<std::pair<uint32_t, uint32_t>>& pairs)
{
    if (o.protocol != "aodv" && o.protocol != "dsdv" && o.protocol != "olsr")
    {
        std::cerr << "Erro: --protocol deve ser aodv, dsdv ou olsr.\n";
        return false;
    }
    if (o.stage != "stage1" && o.stage != "stage2")
    {
        std::cerr << "Erro: --stage deve ser stage1 ou stage2.\n";
        return false;
    }
    if (o.run == 0 || o.seedMaster == 0 || o.ratePps == 0 || o.flowCount == 0 ||
        o.flowCount != pairs.size() || o.nodes < 2 || o.packetSizeBytes == 0 ||
        o.initialPositionStream < 0 || o.mobilityStream < 0 ||
        o.initialPositionStream == o.mobilityStream)
    {
        std::cerr << "Erro: run, seed, taxa, fluxos, nós, payload ou streams inválidos.\n";
        return false;
    }
    if (!std::isfinite(o.speed) || !std::isfinite(o.minimumSpeedMps) ||
        o.minimumSpeedMps <= 0 || o.speed < o.minimumSpeedMps ||
        !std::isfinite(o.areaWidthM) || o.areaWidthM <= 0 ||
        !std::isfinite(o.areaHeightM) || o.areaHeightM <= 0 ||
        !std::isfinite(o.pauseS) || o.pauseS < 0 ||
        !std::isfinite(o.durationS) || !std::isfinite(o.trafficStartS) ||
        !std::isfinite(o.trafficStopS) || o.trafficStartS < 0 ||
        o.trafficStopS <= o.trafficStartS || o.durationS <= o.trafficStopS ||
        static_cast<double>(o.ratePps) * (o.trafficStopS - o.trafficStartS) + 1.0 >
            std::numeric_limits<uint32_t>::max())
    {
        std::cerr << "Erro: duração, tráfego, mobilidade ou área fora dos limites válidos.\n";
        return false;
    }
    if (o.wifiStandard != "802.11g")
    {
        std::cerr << "Erro: este experimento usa somente IEEE 802.11g.\n";
        return false;
    }
    if (!std::isfinite(o.txPowerDbm) || !std::isfinite(o.referenceLossDb) ||
        !std::isfinite(o.rxSensitivityDbm) || !std::isfinite(o.preambleMinRssiDbm) ||
        !std::isfinite(o.referenceDistanceM) || o.referenceDistanceM <= 0 ||
        !std::isfinite(o.pathLossExponent) || o.pathLossExponent <= 0 ||
        !std::isfinite(o.mobilityTraceIntervalS) || o.mobilityTraceIntervalS <= 0 ||
        o.flowsPath.empty() || o.mobilityPath.empty() || o.flowMonitorPath.empty())
    {
        std::cerr << "Erro: parâmetros de rádio, trace ou caminhos de saída inválidos.\n";
        return false;
    }
    if (pairs.empty())
    {
        std::cerr << "Erro: configure ao menos um par origem-destino.\n";
        return false;
    }
    for (size_t i = 0; i < pairs.size(); ++i)
    {
        if (pairs[i].first >= o.nodes || pairs[i].second >= o.nodes || pairs[i].first == pairs[i].second)
        {
            std::cerr << "Erro: par de fluxo aponta para nó inexistente ou origem igual ao destino.\n";
            return false;
        }
        for (size_t j = 0; j < i; ++j)
        {
            if (pairs[i] == pairs[j])
            {
                std::cerr << "Erro: pares de fluxo duplicados.\n";
                return false;
            }
        }
    }
    if (o.animation && (o.animationPath.empty() || !std::isfinite(o.animationStartS) ||
        !std::isfinite(o.animationStopS) || !std::isfinite(o.mobilityUpdateS) ||
        !std::isfinite(o.routeUpdateS) || o.animationStartS < 0 ||
        o.animationStopS <= o.animationStartS || o.animationStopS > o.durationS ||
        o.maxAnimationPackets == 0 || o.mobilityUpdateS <= 0 || o.routeUpdateS <= 0))
    {
        std::cerr << "Erro: janela ou parâmetros da animação inválidos.\n";
        return false;
    }
    return true;
}

uint16_t
ControlPort(const std::string& protocol)
{
    if (protocol == "aodv") return 654;
    if (protocol == "dsdv") return 269;
    return 698; // OLSR
}

void
InstallRouting(InternetStackHelper& stack, const std::string& protocol)
{
    if (protocol == "aodv")
    {
        AodvHelper routing;
        stack.SetRoutingHelper(routing);
    }
    else if (protocol == "dsdv")
    {
        DsdvHelper routing;
        stack.SetRoutingHelper(routing);
    }
    else
    {
        OlsrHelper routing;
        stack.SetRoutingHelper(routing);
    }
}

void
ConfigureAnimation(AnimationInterface& animation,
                   const NodeContainer& nodes,
                   const Options& o,
                   const std::string& routePath,
                   const std::vector<std::pair<uint32_t, uint32_t>>& pairs)
{
    animation.SetStartTime(Seconds(o.animationStartS));
    animation.SetStopTime(Seconds(o.animationStopS));
    animation.SetMobilityPollInterval(Seconds(o.mobilityUpdateS));
    animation.SetMaxPktsPerTraceFile(o.maxAnimationPackets);
    animation.EnablePacketMetadata();
    animation.EnableIpv4RouteTracking(routePath, Seconds(o.animationStartS),
                                      Seconds(o.animationStopS), nodes, Seconds(o.routeUpdateS));
    std::ostringstream title;
        title << o.stage << " | " << o.protocol << " | v=" << o.speed << " m/s | "
            << o.ratePps << " pps/fluxo | seed=" << o.seedMaster << " | run=" << o.run;
    for (uint32_t i = 0; i < nodes.GetN(); ++i)
    {
        bool isSource = false;
        bool isDestination = false;
        for (const auto& pair : pairs)
        {
            isSource = isSource || pair.first == i;
            isDestination = isDestination || pair.second == i;
        }
        const std::string role = isSource ? "Origem" : (isDestination ? "Destino" : "Relay");
        animation.UpdateNodeDescription(i, title.str() + " | " + std::to_string(i) + " - " + role);
        if (isSource) { animation.UpdateNodeColor(i, 220, 55, 55); animation.UpdateNodeSize(i, 8, 8); }
        else if (isDestination) { animation.UpdateNodeColor(i, 55, 100, 220); animation.UpdateNodeSize(i, 8, 8); }
        else { animation.UpdateNodeColor(i, 245, 180, 40); animation.UpdateNodeSize(i, 5, 5); }
    }
}

} // namespace

int
main(int argc, char* argv[])
{
    Options o;
    CommandLine cmd(__FILE__);
#define ADD(name, help, field) cmd.AddValue(name, help, o.field)
    ADD("stage", "Etapa do experimento", stage);
    ADD("protocol", "Protocolo aodv, dsdv ou olsr", protocol);
    ADD("seed-master", "Seed mestre do RngSeedManager", seedMaster);
    ADD("run", "Repetição/run a partir de 1", run);
    ADD("speed", "Velocidade máxima (m/s)", speed);
    ADD("rate", "Pacotes/s por fluxo UDP", ratePps);
    ADD("nodes", "Quantidade de nós", nodes);
    ADD("flow-count", "Quantidade de fluxos UDP", flowCount);
    ADD("flow-pairs", "Pares como 0:1;2:3", flowPairs);
    ADD("wifi-standard", "Padrão Wi-Fi", wifiStandard);
    ADD("area-width", "Largura da área (m)", areaWidthM);
    ADD("area-height", "Altura da área (m)", areaHeightM);
    ADD("pause", "Pausa de RandomWaypoint (s)", pauseS);
    ADD("minimum-speed", "Velocidade mínima (m/s)", minimumSpeedMps);
    ADD("duration", "Duração total (s)", durationS);
    ADD("traffic-start", "Início do tráfego (s)", trafficStartS);
    ADD("traffic-stop", "Fim do tráfego (s)", trafficStopS);
    ADD("tx-power", "Potência de transmissão (dBm)", txPowerDbm);
    ADD("rx-sensitivity", "Sensibilidade de recepção (dBm)", rxSensitivityDbm);
    ADD("preamble-min-rssi", "RSSI mínimo para detectar o preâmbulo (dBm)", preambleMinRssiDbm);
    ADD("rts-cts-threshold", "Limiar RTS/CTS (bytes)", rtsCtsThresholdBytes);
    ADD("reference-loss", "Perda de referência (dB)", referenceLossDb);
    ADD("reference-distance", "Distância de referência (m)", referenceDistanceM);
    ADD("path-loss-exponent", "Expoente LogDistance", pathLossExponent);
    ADD("packet-size", "Payload UDP (bytes)", packetSizeBytes);
    ADD("initial-position-stream", "Stream explícito para posições iniciais", initialPositionStream);
    ADD("mobility-stream", "Stream explícito para RandomWaypoint", mobilityStream);
    ADD("mobility-trace-interval", "Intervalo do trace (s)", mobilityTraceIntervalS);
    ADD("flows", "Caminho CSV de métricas por fluxo", flowsPath);
    ADD("mobility-trace", "Caminho CSV de mobilidade", mobilityPath);
    ADD("flow-monitor", "Caminho XML bruto do FlowMonitor", flowMonitorPath);
    ADD("animation", "Gerar XML do NetAnim", animation);
    ADD("animation-file", "Caminho do XML NetAnim", animationPath);
    ADD("anim-start", "Início da janela NetAnim (s)", animationStartS);
    ADD("anim-stop", "Fim da janela NetAnim (s)", animationStopS);
    ADD("max-animation-packets", "Máximo de pacotes por trace NetAnim", maxAnimationPackets);
    ADD("mobility-update-interval", "Atualização de mobilidade NetAnim (s)", mobilityUpdateS);
    ADD("route-update-interval", "Atualização de rotas NetAnim (s)", routeUpdateS);
#undef ADD
    cmd.Parse(argc, argv);

    std::vector<std::pair<uint32_t, uint32_t>> pairs;
    try { pairs = ParseFlowPairs(o.flowPairs); }
    catch (const std::exception& error)
    {
        std::cerr << "Erro: pares de fluxo inválidos: " << error.what() << "\n";
        return 2;
    }
    if (!Validate(o, pairs)) return 2;

    RngSeedManager::SetSeed(o.seedMaster);
    RngSeedManager::SetRun(o.run);
    NodeContainer nodes;
    nodes.Create(o.nodes);

    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager", "DataMode", StringValue(WIFI_MODE),
                                 "ControlMode", StringValue(WIFI_MODE),
                                 "NonUnicastMode", StringValue(WIFI_MODE),
                                 "RtsCtsThreshold", UintegerValue(o.rtsCtsThresholdBytes));
    YansWifiPhyHelper phy;
    phy.Set("ChannelSettings", StringValue("{1, 20, BAND_2_4GHZ, 0}"));
    phy.Set("TxPowerStart", DoubleValue(o.txPowerDbm));
    phy.Set("TxPowerEnd", DoubleValue(o.txPowerDbm));
    phy.Set("RxSensitivity", DoubleValue(o.rxSensitivityDbm));
    // Este limite define o alcance efetivo: quadros abaixo dele são descartados na detecção do preâmbulo.
    phy.SetPreambleDetectionModel("ns3::ThresholdPreambleDetectionModel",
                                  "MinimumRssi", DoubleValue(o.preambleMinRssiDbm));
    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel", "Exponent", DoubleValue(o.pathLossExponent),
                               "ReferenceDistance", DoubleValue(o.referenceDistanceM),
                               "ReferenceLoss", DoubleValue(o.referenceLossDb));
    phy.SetChannel(channel.Create());
    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");
    NetDeviceContainer devices = wifi.Install(phy, mac, nodes);

    ObjectFactory initialFactory;
    initialFactory.SetTypeId("ns3::RandomRectanglePositionAllocator");
    initialFactory.Set("X", StringValue("ns3::UniformRandomVariable[Min=0|Max=" + std::to_string(o.areaWidthM) + "]"));
    initialFactory.Set("Y", StringValue("ns3::UniformRandomVariable[Min=0|Max=" + std::to_string(o.areaHeightM) + "]"));
    Ptr<PositionAllocator> initial = initialFactory.Create()->GetObject<PositionAllocator>();
    initial->AssignStreams(o.initialPositionStream);

    ObjectFactory destinationFactory;
    destinationFactory.SetTypeId("ns3::RandomRectanglePositionAllocator");
    destinationFactory.Set("X", StringValue("ns3::UniformRandomVariable[Min=0|Max=" + std::to_string(o.areaWidthM) + "]"));
    destinationFactory.Set("Y", StringValue("ns3::UniformRandomVariable[Min=0|Max=" + std::to_string(o.areaHeightM) + "]"));
    Ptr<PositionAllocator> destinations = destinationFactory.Create()->GetObject<PositionAllocator>();
    MobilityHelper mobility;
    mobility.SetPositionAllocator(initial);
    std::ostringstream speed;
    speed << "ns3::UniformRandomVariable[Min=" << o.minimumSpeedMps << "|Max=" << o.speed << "]";
    mobility.SetMobilityModel("ns3::RandomWaypointMobilityModel", "Speed", StringValue(speed.str()),
                              "Pause", StringValue("ns3::ConstantRandomVariable[Constant=" + std::to_string(o.pauseS) + "]"),
                              "PositionAllocator", PointerValue(destinations));
    mobility.Install(nodes);
    mobility.AssignStreams(nodes, o.mobilityStream);

    InternetStackHelper stack;
    InstallRouting(stack, o.protocol);
    stack.Install(nodes);
    const std::string routingProtocol =
        nodes.Get(0)->GetObject<Ipv4>()->GetRoutingProtocol()->GetInstanceTypeId().GetName();
    Ipv4AddressHelper address;
    address.SetBase("10.0.0.0", "255.0.0.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);

    std::vector<std::shared_ptr<uint64_t>> sentPackets;
    size_t startIndex = 0;
    for (const auto& pair : pairs)
    {
        PacketSinkHelper sink("ns3::UdpSocketFactory",
            InetSocketAddress(Ipv4Address::GetAny(), APPLICATION_PORT));
        ApplicationContainer receiver = sink.Install(nodes.Get(pair.second));
        receiver.Start(Seconds(0));
        receiver.Stop(Seconds(o.durationS));
        UdpClientHelper client(interfaces.GetAddress(pair.second), APPLICATION_PORT);
        client.SetAttribute("PacketSize", UintegerValue(o.packetSizeBytes));
        client.SetAttribute("Interval", TimeValue(Seconds(1.0 / o.ratePps)));
        client.SetAttribute("MaxPackets", UintegerValue(static_cast<uint32_t>(
            std::ceil(o.ratePps * (o.trafficStopS - o.trafficStartS)) + 1.0)));
        ApplicationContainer sender = client.Install(nodes.Get(pair.first));
        // Defasagem determinística: fluxos sincronizados colidem de forma repetida, um artefato do simulador.
        sender.Start(Seconds(o.trafficStartS + startIndex * (1.0 / o.ratePps) / pairs.size()));
        ++startIndex;
        sender.Stop(Seconds(o.trafficStopS));
        // Tx vem da aplicação: o FlowMonitor não registra o fluxo se o roteamento descarta antes do IP.
        auto counter = std::make_shared<uint64_t>(0);
        sentPackets.push_back(counter);
        sender.Get(0)->TraceConnectWithoutContext(
            "Tx",
            Callback<void, Ptr<const Packet>>([counter](Ptr<const Packet>) { ++*counter; }));
    }

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();
    experiment::ControlTrafficCounter control(ControlPort(o.protocol));
    Config::ConnectWithoutContext("/NodeList/*/$ns3::Ipv4L3Protocol/Tx",
                                  MakeCallback(&experiment::ControlTrafficCounter::OnIpv4Tx, &control));
    experiment::MobilityRecorder recorder(nodes, o.durationS, o.mobilityTraceIntervalS, o.mobilityPath);
    if (!recorder.IsOpen())
    {
        std::cerr << "Erro: não foi possível criar o trace de mobilidade: " << o.mobilityPath << "\n";
        return 2;
    }
    recorder.Start();
    std::unique_ptr<AnimationInterface> animation;
    if (o.animation)
    {
        animation = std::make_unique<AnimationInterface>(o.animationPath);
        ConfigureAnimation(*animation, nodes, o, o.animationPath + ".routes.xml", pairs);
    }

    Simulator::Stop(Seconds(o.durationS));
    Simulator::Run();
    monitor->CheckForLostPackets();
    monitor->SerializeToXmlFile(o.flowMonitorPath, false, false);

    Ptr<Ipv4FlowClassifier> classifier = DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());
    const auto& flowStats = monitor->GetFlowStats();
    std::ofstream output(o.flowsPath);
    if (!output)
    {
        std::cerr << "Erro: não foi possível criar o CSV: " << o.flowsPath << "\n";
        Simulator::Destroy();
        return 2;
    }
    output << "stage,protocol,speed,rate,run,seed,flowId,txPackets,rxPackets,lostPackets,rxBytes,throughputMbps,pdrPct,delayMs,jitterMs,delaySumMs,jitterSumMs,maxPackets,flowIndex,sourceNode,destinationNode,packetSizeBytes,undeliveredPackets,routingProtocol,controlPackets,controlBytes\n";
    output << std::setprecision(17);
    for (size_t index = 0; index < pairs.size(); ++index)
    {
        const auto pair = pairs[index];
        const Ipv4Address source = interfaces.GetAddress(pair.first);
        const Ipv4Address destination = interfaces.GetAddress(pair.second);
        // Fluxo ausente no FlowMonitor significa nenhum pacote recebido (flowId 0 = ausente).
        uint32_t flowId = 0;
        uint64_t rxPackets = 0;
        uint64_t rxBytes = 0;
        double delaySumMs = 0;
        double jitterSumMs = 0;
        uint64_t lostPackets = 0;
        for (const auto& entry : flowStats)
        {
            const auto tuple = classifier->FindFlow(entry.first);
            if (tuple.protocol != 17 || tuple.sourceAddress != source || tuple.destinationAddress != destination ||
                tuple.destinationPort != APPLICATION_PORT) continue;
            flowId = entry.first;
            rxPackets = entry.second.rxPackets;
            rxBytes = entry.second.rxBytes;
            delaySumMs = entry.second.delaySum.GetSeconds() * 1000.0;
            jitterSumMs = entry.second.jitterSum.GetSeconds() * 1000.0;
            lostPackets = entry.second.lostPackets;
            break;
        }
        const uint64_t txPackets = *sentPackets[index];
        const uint64_t undeliveredPackets = txPackets > rxPackets ? txPackets - rxPackets : 0;
        const double nan = std::numeric_limits<double>::quiet_NaN();
        const double delayMs = rxPackets ? delaySumMs / rxPackets : nan;
        const double jitterMs = rxPackets > 1 ? jitterSumMs / (rxPackets - 1) : nan;
        const uint32_t maxPackets = static_cast<uint32_t>(std::ceil(o.ratePps * (o.trafficStopS - o.trafficStartS)) + 1.0);
        const double throughputMbps = rxBytes * 8.0 / ((o.trafficStopS - o.trafficStartS) * 1e6);
        const double pdrPct = txPackets ? 100.0 * rxPackets / txPackets : nan;
        output << o.stage << ',' << o.protocol << ',' << o.speed << ',' << o.ratePps << ',' << o.run << ','
               << o.seedMaster << ',' << flowId << ',' << txPackets << ',' << rxPackets << ','
               << lostPackets << ',' << rxBytes << ',' << throughputMbps << ',' << pdrPct << ','
               << delayMs << ',' << jitterMs << ',' << delaySumMs << ',' << jitterSumMs << ','
               << maxPackets << ',' << index << ',' << pair.first << ',' << pair.second << ','
               << o.packetSizeBytes << ',' << undeliveredPackets << ',' << routingProtocol << ','
               << control.Packets() << ',' << control.Bytes() << '\n';
    }
    output.close();
    Simulator::Destroy();
    return 0;
}
