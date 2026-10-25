// Two overlapping rings: the page as you see it, and the page as the AI reads it.
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5 font-mono font-medium tracking-[-0.01em]">
      <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
        <circle cx="10.5" cy="14" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="17.5" cy="14" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      parallax
    </span>
  );
}
