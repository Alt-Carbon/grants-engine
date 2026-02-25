"use client";

import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

const DIMENSION_LABELS: Record<string, string> = {
  theme_alignment:        "Theme",
  eligibility_confidence: "Eligibility",
  funding_amount:         "Funding",
  deadline_urgency:       "Deadline",
  geography_fit:          "Geography",
  competition_level:      "Competition",
};

interface ScoreRadarProps {
  scores: Record<string, number>;
  height?: number;
}

export function ScoreRadar({ scores, height = 220 }: ScoreRadarProps) {
  const data = Object.entries(scores)
    .filter(([, v]) => typeof v === "number")
    .map(([key, value]) => ({
      dimension: DIMENSION_LABELS[key] || key,
      value: Math.min(10, Math.max(0, value)),
    }));

  if (data.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-gray-400">
        No score data
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} margin={{ top: 10, right: 20, bottom: 10, left: 20 }}>
        <PolarGrid stroke="#e5e7eb" />
        <PolarAngleAxis
          dataKey="dimension"
          tick={{ fontSize: 11, fill: "#6b7280" }}
        />
        <PolarRadiusAxis domain={[0, 10]} tick={false} axisLine={false} />
        <Tooltip
          contentStyle={{ fontSize: 12, borderRadius: 8 }}
          formatter={(v: number) => [v.toFixed(1), "Score"]}
        />
        <Radar
          name="Score"
          dataKey="value"
          stroke="#3b82f6"
          fill="#3b82f6"
          fillOpacity={0.25}
          dot={{ r: 3, fill: "#3b82f6" }}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}
