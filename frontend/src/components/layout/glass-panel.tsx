import { cn } from "@/lib/utils";

interface GlassPanelProps {
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export function GlassPanel({ title, children, className }: GlassPanelProps) {
  return (
    <div className={cn("glass-hover p-6", className)}>
      {title && <h3 className="text-lg font-semibold mb-4">{title}</h3>}
      {children}
    </div>
  );
}
