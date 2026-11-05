#pragma once

#include <fstream>
#include <iomanip>
#include <string>
#include <utility>

#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"

namespace experiment
{

// Conta, na saida IP de todos os nos, os datagramas UDP da porta do protocolo de roteamento.
// Inclui retransmissoes de controle por outros nos; nao mede tempo de canal nem energia.
class ControlTrafficCounter
{
  public:
    explicit ControlTrafficCounter(uint16_t protocolPort) : m_port(protocolPort) {}

    void OnIpv4Tx(ns3::Ptr<const ns3::Packet> packet, ns3::Ptr<ns3::Ipv4>, uint32_t)
    {
        ns3::Ptr<ns3::Packet> copy = packet->Copy();
        ns3::Ipv4Header ipHeader;
        if (copy->RemoveHeader(ipHeader) == 0 || ipHeader.GetProtocol() != 17)
        {
            return;
        }
        ns3::UdpHeader udpHeader;
        if (copy->RemoveHeader(udpHeader) == 0 ||
            (udpHeader.GetSourcePort() != m_port && udpHeader.GetDestinationPort() != m_port))
        {
            return;
        }
        ++m_packets;
        m_bytes += packet->GetSize();
    }

    uint64_t Packets() const { return m_packets; }
    uint64_t Bytes() const { return m_bytes; }

  private:
    uint16_t m_port;
    uint64_t m_packets{0};
    uint64_t m_bytes{0};
};

class MobilityRecorder
{
  public:
    MobilityRecorder(ns3::NodeContainer nodes,
                     double stopTime,
                     double sampleInterval,
                     std::string traceFile)
        : m_nodes(std::move(nodes)),
          m_stopTime(stopTime),
          m_sampleInterval(sampleInterval),
          m_traceFile(std::move(traceFile))
    {
        if (!m_traceFile.empty())
        {
            m_output.open(m_traceFile);
            // Precisão de micrômetro: ruído de ponto flutuante de consultas de posição não altera o hash.
            m_output << std::fixed << std::setprecision(6) << "time_s,node_id,x_m,y_m\n";
        }
    }

    bool IsOpen() const { return m_traceFile.empty() || m_output.is_open(); }
    void Start() { ns3::Simulator::ScheduleNow(&MobilityRecorder::Sample, this); }

  private:
    void Sample()
    {
        const uint32_t count = m_nodes.GetN();
        if (m_output.is_open())
        {
            const double time = ns3::Simulator::Now().GetSeconds();
            for (uint32_t i = 0; i < count; ++i)
            {
                const ns3::Vector position = m_nodes.Get(i)->GetObject<ns3::MobilityModel>()->GetPosition();
                m_output << time << ',' << i << ',' << position.x << ',' << position.y << '\n';
            }
        }
        const double now = ns3::Simulator::Now().GetSeconds();
        if (now + m_sampleInterval <= m_stopTime)
        {
            ns3::Simulator::Schedule(ns3::Seconds(m_sampleInterval), &MobilityRecorder::Sample, this);
        }
    }

    ns3::NodeContainer m_nodes;
    double m_stopTime;
    double m_sampleInterval;
    std::string m_traceFile;
    std::ofstream m_output;
};

} // namespace experiment
