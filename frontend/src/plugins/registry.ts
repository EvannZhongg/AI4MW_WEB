import DatasheetKgModule from "@/plugins/modules/datasheet-kg";
import PromptOrchestratorModule from "@/plugins/modules/prompt-orchestrator";
import SimulationAdapterModule from "@/plugins/modules/sim-adapter";
import VlmInsightModule from "@/plugins/modules/vlm-insight";
import type { PluginDefinition } from "@/plugins/types";

export const pluginRegistry: PluginDefinition[] = [
  {
    id: "datasheet-kg",
    title: "Datasheet Knowledge Graph",
    description: "Extract entities and relations from datasheets into PostgreSQL + pgvector.",
    category: "knowledge",
    status: "ready",
    tags: ["parser", "kg", "pgvector"],
    entry: DatasheetKgModule
  },
  {
    id: "prompt-orchestrator",
    title: "Prompt Orchestrator",
    description: "Route tasks through prompts, tools, and traceable steps.",
    category: "orchestration",
    status: "beta",
    tags: ["workflow", "prompts"],
    entry: PromptOrchestratorModule
  },
  {
    id: "vlm-insight",
    title: "VLM Image Insight",
    description: "Classify figures and link them to datasheet context.",
    category: "analysis",
    status: "beta",
    tags: ["vlm", "vision"],
    entry: VlmInsightModule
  },
  {
    id: "simulation-adapter",
    title: "Simulation Adapter",
    description: "Abstract access layer for EM solvers and sweep configs.",
    category: "simulation",
    status: "planned",
    tags: ["hfss", "cst", "comsol"],
    entry: SimulationAdapterModule
  }
];
