#pragma once

#include <fstream>
#include <iomanip>
#include <cmath>
#include <string>
#include <utility>

#include "ns3/flow-monitor-module.h"
#include "ns3/ipv4-flow-classifier.h"
#include "ns3/ipv4-header.h"
#include "ns3/mobility-module.h"
#include "ns3/udp-header.h"

namespace experiment
{

struct FlowTotals
{
    uint64_t txPackets{0};
    uint64_t rxPackets{0};
    uint64_t lostPackets{0};
    uint64_t txBytes{0};
    uint64_t rxBytes{0};
    ns3::Time delaySum{ns3::Seconds(0)};

    void Add(const ns3::FlowMonitor::FlowStats& stats)
    {
        txPackets += stats.txPackets;
        rxPackets += stats.rxPackets;
        lostPackets += stats.lostPackets;
        txBytes += stats.txBytes;
        rxBytes += stats.rxBytes;
        delaySum += stats.delaySum;
    }

    double MeanDelayMs() const
    {
        return rxPackets == 0 ? 0.0 : delaySum.GetSeconds() * 1000.0 / rxPackets;
    }
};

class ControlTrafficCounter
{
  public:
    explicit ControlTrafficCounter(uint16_t port)
        : m_port(port)
    {
    }

    void OnIpv4Tx(ns3::Ptr<const ns3::Packet> packet,
                  ns3::Ptr<ns3::Ipv4> ipv4,
                  uint32_t interface)
    {
        (void)ipv4;
        (void)interface;

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

        // Count each IP-layer transmission, including broadcasts and forwarded control packets.
        ++m_packets;
        m_bytes += packet->GetSize();
    }

    uint64_t GetPackets() const
    {
        return m_packets;
    }

    uint64_t GetBytes() const
    {
        return m_bytes;
    }

  private:
    uint16_t m_port;
    uint64_t m_packets{0};
    uint64_t m_bytes{0};
};

class MobilityRecorder
{
  public:
    MobilityRecorder(ns3::NodeContainer nodes,
                     double width,
                     double height,
                     double stopTime,
                     double radioRange,
                     std::string traceFile)
        : m_nodes(std::move(nodes)),
          m_width(width),
          m_height(height),
          m_stopTime(stopTime),
          m_radioRange(radioRange),
          m_traceFile(std::move(traceFile))
    {
        if (!m_traceFile.empty())
        {
            m_output.open(m_traceFile);
            m_output << "time_s,node_id,x_m,y_m\n";
        }
    }

    void Start()
    {
        ns3::Simulator::Schedule(ns3::Seconds(0), &MobilityRecorder::Sample, this);
    }

    double GetDensityNodesPerKm2() const
    {
        return m_nodes.GetN() * 1e6 / (m_width * m_height);
    }

    double GetMeanDegree() const
    {
        return m_samples == 0 ? 0.0 : m_degreeSum / m_samples;
    }

    double GetRadioRangeMeters() const
    {
        return m_radioRange;
    }

  private:
    void Sample()
    {
        const uint32_t count = m_nodes.GetN();
        std::vector<ns3::Vector> positions;
        positions.reserve(count);

        for (uint32_t i = 0; i < count; ++i)
        {
            positions.push_back(m_nodes.Get(i)->GetObject<ns3::MobilityModel>()->GetPosition());
        }

        uint64_t degreeSum = 0;
        for (uint32_t i = 0; i < count; ++i)
        {
            for (uint32_t j = i + 1; j < count; ++j)
            {
                const double dx = positions[i].x - positions[j].x;
                const double dy = positions[i].y - positions[j].y;
                const double dz = positions[i].z - positions[j].z;
                if (dx * dx + dy * dy + dz * dz <= m_radioRange * m_radioRange)
                {
                    degreeSum += 2;
                }
            }
        }

        m_degreeSum += static_cast<double>(degreeSum) / count;
        ++m_samples;

        if (m_output.is_open())
        {
            const double time = ns3::Simulator::Now().GetSeconds();
            for (uint32_t i = 0; i < count; ++i)
            {
                m_output << time << ',' << i << ',' << positions[i].x << ',' << positions[i].y << '\n';
            }
        }

        if (ns3::Simulator::Now().GetSeconds() + 1.0 <= m_stopTime)
        {
            ns3::Simulator::Schedule(ns3::Seconds(1), &MobilityRecorder::Sample, this);
        }
    }

    ns3::NodeContainer m_nodes;
    double m_width;
    double m_height;
    double m_stopTime;
    double m_radioRange;
    std::string m_traceFile;
    std::ofstream m_output;
    double m_degreeSum{0.0};
    uint64_t m_samples{0};
};

inline void
WriteSummary(const std::string& protocol,
             uint32_t seed,
             uint16_t applicationPort,
             ns3::Ipv4Address source,
             ns3::Ipv4Address destination,
             ns3::Ptr<ns3::FlowMonitor> monitor,
             ns3::Ptr<ns3::Ipv4FlowClassifier> classifier,
             const ControlTrafficCounter& control,
             const std::string& scenario,
             uint32_t nodes,
             double width,
             double height,
             double maxSpeed,
             double pause,
             const MobilityRecorder& mobility,
             const std::string& outputFile)
{
    FlowTotals forward;
    FlowTotals reverse;

    for (const auto& [flowId, stats] : monitor->GetFlowStats())
    {
        const auto tuple = classifier->FindFlow(flowId);
        if (tuple.protocol != 17)
        {
            continue;
        }

        if (tuple.sourceAddress == source && tuple.destinationAddress == destination &&
            tuple.destinationPort == applicationPort && tuple.sourcePort != applicationPort)
        {
            forward.Add(stats);
        }
        else if (tuple.sourceAddress == destination && tuple.destinationAddress == source &&
                 tuple.sourcePort == applicationPort && tuple.destinationPort != applicationPort)
        {
            reverse.Add(stats);
        }
    }

    std::ofstream output(outputFile);
    output << "scenario,protocol,seed,nodes,width_m,height_m,max_speed_mps,pause_s,density_nodes_km2,"
              "radio_range_m,mean_neighbor_degree,direction,tx_packets,rx_packets,lost_packets,tx_bytes,"
              "rx_bytes,mean_delay_ms,control_tx_packets,control_tx_ip_bytes\n";
    output << std::fixed << std::setprecision(3);
    const auto writeRow = [&](const char* direction, const FlowTotals& flow, bool includeControl) {
        output << scenario << ',' << protocol << ',' << seed << ',' << nodes << ',' << width << ',' << height
               << ',' << maxSpeed << ',' << pause << ',' << mobility.GetDensityNodesPerKm2() << ','
               << mobility.GetRadioRangeMeters() << ',' << mobility.GetMeanDegree() << ',' << direction << ','
               << flow.txPackets << ',' << flow.rxPackets << ',' << flow.lostPackets << ',' << flow.txBytes << ','
               << flow.rxBytes << ',' << flow.MeanDelayMs() << ',';
        if (includeControl)
        {
            output << control.GetPackets() << ',' << control.GetBytes();
        }
        else
        {
            output << ',';
        }
        output << '\n';
    };
    writeRow("outbound", forward, true);
    writeRow("return", reverse, false);
}

} // namespace experiment
