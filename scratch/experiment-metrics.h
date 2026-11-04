#pragma once

#include <fstream>
#include <iomanip>
#include <string>
#include <utility>

#include "ns3/mobility-module.h"

namespace experiment
{

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
            m_output << std::setprecision(17) << "time_s,node_id,x_m,y_m\n";
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
