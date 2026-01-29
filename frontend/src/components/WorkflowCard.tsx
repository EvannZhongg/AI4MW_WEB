import Tag from "@/components/Tag";

type WorkflowCardProps = {
  name: string;
  goal: string;
  promptId: string;
  status: "active" | "draft";
  steps: string[];
};

export default function WorkflowCard({
  name,
  goal,
  promptId,
  status,
  steps
}: WorkflowCardProps) {
  return (
    <div className="workflow-card">
      <div>
        <h4>{name}</h4>
        <p>{goal}</p>
      </div>
      <div className="workflow-steps">
        {steps.map((step) => (
          <span key={step} className="workflow-step">
            {step}
          </span>
        ))}
      </div>
      <div className="card-footer">
        <Tag label={status} tone={status === "active" ? "success" : "warning"} />
        <Tag label={`prompt: ${promptId}`} />
      </div>
    </div>
  );
}
