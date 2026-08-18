"use client";

import { BaseEdge, EdgeProps, getBezierPath } from "reactflow";

import { cn } from "@/lib/utils";

export function SmartBezierEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
  style,
  markerEnd,
}: EdgeProps) {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: selected ? "#a78bfa" : "#52525b",
          strokeWidth: selected ? 2.5 : 2,
          ...style,
        }}
      />
      {selected ? (
        <path
          d={edgePath}
          fill="none"
          stroke="#c4b5fd"
          strokeWidth={2}
          strokeLinecap="round"
          strokeDasharray="6 14"
          className={cn("flow-edge-pulse pointer-events-none")}
        />
      ) : null}
    </>
  );
}
