type TagProps = {
  label: string;
  tone?: "default" | "accent" | "success" | "warning";
};

export default function Tag({ label, tone = "default" }: TagProps) {
  const className = tone === "default" ? "tag" : `tag ${tone}`;
  return <span className={className}>{label}</span>;
}
