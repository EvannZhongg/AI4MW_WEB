export type WorkflowDefinition = {
  id: string;
  name: string;
  goal: string;
  promptId: string;
  status: "active" | "draft";
  steps: string[];
};

export const workflowCatalog: WorkflowDefinition[] = [
  {
    id: "wf-datasheet-to-kg",
    name: "Datasheet to Knowledge Graph",
    goal: "Parse, extract, normalize, and persist device knowledge.",
    promptId: "kg.pipeline.v1",
    status: "active",
    steps: ["parse", "chunk", "extract", "normalize", "store"]
  },
  {
    id: "wf-visual-annotation",
    name: "Figure Annotation",
    goal: "Classify figures and link them to models and parameters.",
    promptId: "vlm.figure.v2",
    status: "draft",
    steps: ["detect", "classify", "caption", "associate"]
  },
  {
    id: "wf-research-brief",
    name: "Research Brief",
    goal: "Combine retrieval and reasoning into a structured report.",
    promptId: "brief.compose.v1",
    status: "draft",
    steps: ["retrieve", "summarize", "verify", "report"]
  }
];
