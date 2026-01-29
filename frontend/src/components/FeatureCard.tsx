import type { ReactNode } from "react";
import Tag from "@/components/Tag";

type FeatureCardProps = {
  title: string;
  description: string;
  category: string;
  status: "ready" | "beta" | "planned";
  tags?: string[];
  children?: ReactNode;
};

const statusTone: Record<FeatureCardProps["status"], "accent" | "success" | "warning"> = {
  ready: "success",
  beta: "accent",
  planned: "warning"
};

export default function FeatureCard({
  title,
  description,
  category,
  status,
  tags = [],
  children
}: FeatureCardProps) {
  return (
    <div className="card">
      <div>
        <Tag label={category} />
      </div>
      <h3>{title}</h3>
      <p>{description}</p>
      {children ? <div>{children}</div> : null}
      <div className="card-footer">
        <Tag label={status} tone={statusTone[status]} />
        {tags.map((tag) => (
          <Tag key={tag} label={tag} tone="accent" />
        ))}
      </div>
    </div>
  );
}
