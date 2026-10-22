#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/mobility-module.h"
#include "ns3/wifi-module.h"
#include "ns3/internet-module.h"
#include "ns3/dsdv-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/netanim-module.h"
#include "experiment-metrics.h"

#include <memory>
#include <string>

using namespace ns3;

int
main (int argc, char *argv[])
{
  uint32_t nNodes = 40;
  double simTime = 180.0;
  double drainTime = 10.0;
  double areaWidth = 1000.0;
  double areaHeight = 1000.0;
  double maxSpeed = 5.0;
  double pause = 10.0;
  uint32_t seed = 12345;
  std::string scenario = "base";
  std::string summaryFile = "resumo-trafego-dsdv.csv";
  std::string mobilityFile;
  std::string flowMonitorFile = "resultado-flowmonitor-dsdv.xml";
  bool animation = true;

  CommandLine cmd (__FILE__);
  cmd.AddValue ("seed", "Semente aleatória", seed);
  cmd.AddValue ("nodes", "Número de nós", nNodes);
  cmd.AddValue ("areaWidth", "Largura da área em metros", areaWidth);
  cmd.AddValue ("areaHeight", "Altura da área em metros", areaHeight);
  cmd.AddValue ("speed", "Velocidade máxima em m/s", maxSpeed);
  cmd.AddValue ("pause", "Pausa do RandomWaypoint em segundos", pause);
  cmd.AddValue ("scenario", "Identificador do cenário", scenario);
  cmd.AddValue ("summary", "Arquivo CSV de resumo", summaryFile);
  cmd.AddValue ("mobilityTrace", "Arquivo CSV da trajetória (opcional)", mobilityFile);
  cmd.AddValue ("flowMonitorFile", "Arquivo XML do FlowMonitor", flowMonitorFile);
  cmd.AddValue ("animation", "Gerar arquivo para NetAnim", animation);
  cmd.Parse (argc, argv);

  SeedManager::SetSeed (seed);

  NodeContainer nodes;
  nodes.Create (nNodes);

  WifiHelper wifi;
  wifi.SetStandard (WIFI_STANDARD_80211b);
  wifi.SetRemoteStationManager ("ns3::ConstantRateWifiManager",
                                "DataMode",
                                StringValue ("DsssRate1Mbps"),
                                "ControlMode",
                                StringValue ("DsssRate1Mbps"),
                                "RtsCtsThreshold",
                                UintegerValue (65535));

  constexpr double txPowerDbm = 20.0;
  constexpr double rxSensitivityDbm = -101.0;
  constexpr double radioRange = 200.0;
  YansWifiPhyHelper wifiPhy;
  wifiPhy.Set ("TxPowerStart", DoubleValue (txPowerDbm));
  wifiPhy.Set ("TxPowerEnd", DoubleValue (txPowerDbm));
  wifiPhy.Set ("RxSensitivity", DoubleValue (rxSensitivityDbm));

  YansWifiChannelHelper wifiChannel;
  wifiChannel.SetPropagationDelay ("ns3::ConstantSpeedPropagationDelayModel");
  wifiChannel.AddPropagationLoss ("ns3::RangePropagationLossModel",
                                 "MaxRange",
                                 DoubleValue (radioRange));
  wifiChannel.AddPropagationLoss ("ns3::LogDistancePropagationLossModel",
                                 "Exponent",
                                 DoubleValue (2.0),
                                 "ReferenceDistance",
                                 DoubleValue (1.0),
                                 "ReferenceLoss",
                                 DoubleValue (40.05));
  wifiPhy.SetChannel (wifiChannel.Create ());

  WifiMacHelper wifiMac;
  wifiMac.SetType ("ns3::AdhocWifiMac");
  NetDeviceContainer devices = wifi.Install (wifiPhy, wifiMac, nodes);

  MobilityHelper mobility;
  ObjectFactory positionFactory;
  positionFactory.SetTypeId ("ns3::RandomRectanglePositionAllocator");
  positionFactory.Set ("X", StringValue ("ns3::UniformRandomVariable[Min=0.0|Max=" +
                                           std::to_string (areaWidth) + "]"));
  positionFactory.Set ("Y", StringValue ("ns3::UniformRandomVariable[Min=0.0|Max=" +
                                           std::to_string (areaHeight) + "]"));
  Ptr<PositionAllocator> positionAlloc =
      positionFactory.Create ()->GetObject<PositionAllocator> ();
  positionAlloc->AssignStreams (100);

  std::ostringstream speed;
  speed << "ns3::UniformRandomVariable[Min=1.0|Max=" << maxSpeed << "]";
  mobility.SetMobilityModel ("ns3::RandomWaypointMobilityModel",
                             "Speed",
                             StringValue (speed.str ()),
                             "Pause",
                             StringValue ("ns3::ConstantRandomVariable[Constant=" +
                                          std::to_string (pause) + "]"),
                             "PositionAllocator",
                             PointerValue (positionAlloc));
  mobility.SetPositionAllocator (positionAlloc);
  mobility.Install (nodes);
  mobility.AssignStreams (nodes, 1000);

  DsdvHelper dsdv;
  InternetStackHelper stack;
  stack.SetRoutingHelper (dsdv);
  stack.Install (nodes);

  Ipv4AddressHelper address;
  address.SetBase ("10.0.0.0", "255.0.0.0");
  Ipv4InterfaceContainer interfaces = address.Assign (devices);

  constexpr uint16_t appPort = 9;
  constexpr uint16_t dsdvControlPort = 269;
  experiment::ControlTrafficCounter controlTraffic (dsdvControlPort);
  Config::ConnectWithoutContext ("/NodeList/*/$ns3::Ipv4L3Protocol/Tx",
                                 MakeCallback (&experiment::ControlTrafficCounter::OnIpv4Tx,
                                               &controlTraffic));

  UdpEchoServerHelper echoServer (appPort);
  ApplicationContainer serverApp = echoServer.Install (nodes.Get (1));
  serverApp.Start (Seconds (1.0));
  serverApp.Stop (Seconds (simTime + drainTime));

  UdpEchoClientHelper echoClient (interfaces.GetAddress (1), appPort);
  echoClient.SetAttribute ("MaxPackets", UintegerValue (1000));
  echoClient.SetAttribute ("Interval", TimeValue (Seconds (1.0)));
  echoClient.SetAttribute ("PacketSize", UintegerValue (512));
  ApplicationContainer clientApp = echoClient.Install (nodes.Get (0));
  clientApp.Start (Seconds (10.0));
  clientApp.Stop (Seconds (simTime));

  FlowMonitorHelper flowmonHelper;
  Ptr<FlowMonitor> monitor = flowmonHelper.InstallAll ();

  experiment::MobilityRecorder mobilityRecorder (nodes,
                                                  areaWidth,
                                                  areaHeight,
                                                  simTime,
                                                  radioRange,
                                                  mobilityFile);
  mobilityRecorder.Start ();

  std::unique_ptr<AnimationInterface> anim;
  if (animation)
    {
      anim = std::make_unique<AnimationInterface> ("experimento-dsdv-demo.xml");
    }

  Simulator::Stop (Seconds (simTime + drainTime));
  Simulator::Run ();

  monitor->CheckForLostPackets ();
  monitor->SerializeToXmlFile (flowMonitorFile, true, true);
  Ptr<Ipv4FlowClassifier> classifier =
      DynamicCast<Ipv4FlowClassifier> (flowmonHelper.GetClassifier ());
  experiment::WriteSummary ("DSDV",
                            seed,
                            appPort,
                            interfaces.GetAddress (0),
                            interfaces.GetAddress (1),
                            monitor,
                            classifier,
                            controlTraffic,
                            scenario,
                            nNodes,
                            areaWidth,
                            areaHeight,
                            maxSpeed,
                            pause,
                            mobilityRecorder,
                            summaryFile);

  Simulator::Destroy ();
  return 0;
}
