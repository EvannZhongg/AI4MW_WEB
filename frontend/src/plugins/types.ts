import type { ComponentType } from "react";

export type PluginStatus = "ready" | "beta" | "planned";
export type PluginCategory =
  | "ingestion"
  | "analysis"
  | "knowledge"
  | "simulation"
  | "orchestration";

export type PluginDefinition = {
  id: string;
  title: string;
  description: string;
  category: PluginCategory;
  status: PluginStatus;
  tags: string[];
  entry: ComponentType;
};
