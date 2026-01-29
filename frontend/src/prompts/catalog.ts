export type PromptDefinition = {
  id: string;
  name: string;
  version: string;
  scope: "core" | "domain" | "task";
  owner: string;
};

export const promptCatalog: PromptDefinition[] = [
  {
    id: "kg.pipeline.v1",
    name: "KG pipeline base",
    version: "1.0.0",
    scope: "core",
    owner: "system"
  },
  {
    id: "vlm.figure.v2",
    name: "Figure classification",
    version: "2.1.0",
    scope: "task",
    owner: "vision"
  },
  {
    id: "brief.compose.v1",
    name: "Research brief",
    version: "1.0.0",
    scope: "domain",
    owner: "research"
  }
];
