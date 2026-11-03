#pragma once

#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <string>
#include <utility>
#include <vector>

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
    uint64_t timesForwarded{0};

    void Add(const ns3::FlowMonitor::FlowStats& stats)
    {
        txPackets += stats.txPackets;
        rxPackets += stats.rxPackets;
        lostPackets += stats.lostPackets;
        txBytes += stats.txBytes;
        rxBytes += stats.rxBytes;
        delaySum += stats.delaySum;
        timesForwarded += stats.timesForwarded;
    }
};

class ControlTrafficCounter
{
  public:
    explicit ControlTrafficCounter(uint16_t protocolPort) : m_port(protocolPort) {}

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
                     double width,
                     double height,
                     double stopTime,
                     double radioRange,
                     double sampleInterval,
                     std::string traceFile)
        : m_nodes(std::move(nodes)),
          m_width(width),
          m_height(height),
          m_stopTime(stopTime),
          m_radioRange(radioRange),
          m_sampleInterval(sampleInterval),
          m_traceFile(std::move(traceFile))
    {
        if (!m_traceFile.empty())
        {
            m_output.open(m_traceFile);
            m_output << std::setprecision(17) << "time_s,node_id,x_m,y_m\n";
        }
    }

    bool IsOpen() const { return m_traceFile.empty() || m_output.is_open(); }
    void Start() { ns3::Simulator::ScheduleNow(&MobilityRecorder::Sample, this); }
    double MeanDegree() const { return m_samples ? m_degreeSum / m_samples : 0.0; }
    double DensityPerKm2() const { return m_nodes.GetN() * 1e6 / (m_width * m_height); }

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
                if (dx * dx + dy * dy <= m_radioRange * m_radioRange)
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
        const double now = ns3::Simulator::Now().GetSeconds();
        if (now + m_sampleInterval <= m_stopTime)
        {
            ns3::Simulator::Schedule(ns3::Seconds(m_sampleInterval), &MobilityRecorder::Sample, this);
        }
    }

    ns3::NodeContainer m_nodes;
    double m_width;
    double m_height;
    double m_stopTime;
    double m_radioRange;
    double m_sampleInterval;
    std::string m_traceFile;
    std::ofstream m_output;
    double m_degreeSum{0.0};
    uint64_t m_samples{0};
};

} // namespace experiment
