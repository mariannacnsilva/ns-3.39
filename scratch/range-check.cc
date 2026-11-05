// Teste de alcance: dois nos parados, com o mesmo canal do experimento, a uma distancia dada.
#include "ns3/applications-module.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/network-module.h"
#include "ns3/wifi-module.h"

#include <iostream>

using namespace ns3;

int
main(int argc, char* argv[])
{
    double distance = 100.0;
    double txPower = 16.0;
    double rxSensitivity = -101.0;
    double preambleMinRssi = -82.0;
    double referenceLoss = 40.05;
    double referenceDistance = 1.0;
    double exponent = 2.6;
    uint32_t packets = 100;
    uint32_t packetSize = 512;
    CommandLine cmd(__FILE__);
    cmd.AddValue("distance", "Distancia entre os nos (m)", distance);
    cmd.AddValue("tx-power", "Potencia de transmissao (dBm)", txPower);
    cmd.AddValue("rx-sensitivity", "Sensibilidade de recepcao (dBm)", rxSensitivity);
    cmd.AddValue("preamble-min-rssi", "RSSI minimo do preambulo (dBm)", preambleMinRssi);
    cmd.AddValue("reference-loss", "Perda de referencia (dB)", referenceLoss);
    cmd.AddValue("reference-distance", "Distancia de referencia (m)", referenceDistance);
    cmd.AddValue("path-loss-exponent", "Expoente LogDistance", exponent);
    cmd.AddValue("packets", "Pacotes enviados", packets);
    cmd.AddValue("packet-size", "Tamanho do pacote (bytes)", packetSize);
    cmd.Parse(argc, argv);

    NodeContainer nodes;
    nodes.Create(2);
    WifiHelper wifi;
    wifi.SetStandard(WIFI_STANDARD_80211g);
    wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
                                 "DataMode", StringValue("ErpOfdmRate6Mbps"),
                                 "ControlMode", StringValue("ErpOfdmRate6Mbps"),
                                 "NonUnicastMode", StringValue("ErpOfdmRate6Mbps"));
    YansWifiPhyHelper phy;
    phy.Set("ChannelSettings", StringValue("{1, 20, BAND_2_4GHZ, 0}"));
    phy.Set("TxPowerStart", DoubleValue(txPower));
    phy.Set("TxPowerEnd", DoubleValue(txPower));
    phy.Set("RxSensitivity", DoubleValue(rxSensitivity));
    phy.SetPreambleDetectionModel("ns3::ThresholdPreambleDetectionModel",
                                  "MinimumRssi", DoubleValue(preambleMinRssi));
    YansWifiChannelHelper channel;
    channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
                               "Exponent", DoubleValue(exponent),
                               "ReferenceDistance", DoubleValue(referenceDistance),
                               "ReferenceLoss", DoubleValue(referenceLoss));
    phy.SetChannel(channel.Create());
    WifiMacHelper mac;
    mac.SetType("ns3::AdhocWifiMac");
    NetDeviceContainer devices = wifi.Install(phy, mac, nodes);

    Ptr<ListPositionAllocator> positions = CreateObject<ListPositionAllocator>();
    positions->Add(Vector(0.0, 0.0, 0.0));
    positions->Add(Vector(distance, 0.0, 0.0));
    MobilityHelper mobility;
    mobility.SetPositionAllocator(positions);
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(nodes);

    InternetStackHelper stack;
    stack.Install(nodes);
    Ipv4AddressHelper address;
    address.SetBase("10.0.0.0", "255.0.0.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);

    const uint16_t port = 9000;
    PacketSinkHelper sink("ns3::UdpSocketFactory", InetSocketAddress(Ipv4Address::GetAny(), port));
    ApplicationContainer receiver = sink.Install(nodes.Get(1));
    UdpClientHelper client(interfaces.GetAddress(1), port);
    client.SetAttribute("PacketSize", UintegerValue(packetSize));
    client.SetAttribute("Interval", TimeValue(Seconds(0.1)));
    client.SetAttribute("MaxPackets", UintegerValue(packets));
    ApplicationContainer sender = client.Install(nodes.Get(0));
    receiver.Start(Seconds(0.0));
    sender.Start(Seconds(1.0));
    Simulator::Stop(Seconds(1.0 + 0.1 * packets + 2.0));
    Simulator::Run();
    const uint64_t received = DynamicCast<PacketSink>(receiver.Get(0))->GetTotalRx() / packetSize;
    Simulator::Destroy();
    std::cout << distance << ',' << packets << ',' << received << std::endl;
    return 0;
}
