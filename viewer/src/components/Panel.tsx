import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  children: ReactNode;
  accent?: "green" | "amber" | "red";
  className?: string;
}

export function Panel({ title, children, accent = "green", className }: PanelProps) {
  const accentClass = accent === "green" ? "" : `panel-accent-${accent}`;
  return (
    <section className={`panel ${accentClass} ${className ?? ""}`.trim()}>
      <header className="panel-title">{title}</header>
      <div className="panel-body">{children}</div>
    </section>
  );
}
