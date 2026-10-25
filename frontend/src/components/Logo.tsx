// Two overlapping rings: the page as you see it, and the page as the AI reads it.
export default function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5 font-mono font-medium tracking-[-0.01em]">
      <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
        <rect width="28" height="28" rx="6" fill="#0a0a0a" />
        <circle cx="10.5" cy="14" r="8.5" fill="none" stroke="#fff" strokeWidth="1.6" />
        <circle cx="17.5" cy="14" r="8.5" fill="none" stroke="#3d7eff" strokeWidth="1.6" />
      </svg>
      parallax
    </span>
  );
}
