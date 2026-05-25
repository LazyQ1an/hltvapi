"use client";

interface StatCardsProps {
  items: { label: string; value: string | number }[];
}

export function StatCards({ items }: StatCardsProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {items.map((item) => (
        <div key={item.label} className="glass-hover p-5">
          <div className="stat-label">{item.label}</div>
          <div className="stat-value text-primary mt-1">{item.value}</div>
        </div>
      ))}
    </div>
  );
}
