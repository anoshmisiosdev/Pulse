function Block({ className }: { className: string }) {
  return (
    <div
      className={`animate-pulse rounded-xl ${className}`}
      style={{ background: "var(--surface-3)" }}
    />
  );
}

/** Dashboard-shaped placeholder shown while tenant data loads. */
export default function PageSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Loading">
      <div className="space-y-2">
        <Block className="h-9 w-64" />
        <Block className="h-4 w-96 max-w-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Block className="h-24" />
        <Block className="h-24" />
        <Block className="h-24" />
        <Block className="h-24" />
      </div>
      <Block className="h-72" />
      <div className="grid gap-4 md:grid-cols-2">
        <Block className="h-48" />
        <Block className="h-48" />
      </div>
    </div>
  );
}
