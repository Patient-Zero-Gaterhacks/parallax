import ThreatMap from "./ThreatMap";

export default function Hero() {
  return (
    <section
      id="top"
      className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-14 px-6 pt-12 pb-24"
    >
      <div className="flex min-w-0 flex-[1_1_440px] flex-col items-start gap-7">
        <p className="inline-flex items-center gap-2.5 rounded-full border border-neutral-800 px-3.5 py-[7px] font-mono text-xs text-neutral-400">
          <span className="size-1.5 rounded-full bg-white" />
          Hidden-text scanner for AI assistants
        </p>
        <h1 className="text-[clamp(42px,6.4vw,80px)] leading-[1.02] font-semibold tracking-[-0.035em] text-balance">
          Your AI reads what you can't see.
        </h1>
        <p className="max-w-[520px] text-lg leading-[1.55] text-neutral-400">
          Attackers hide instructions for AI in emails, PDFs, Word files and web
          pages, using white text, tiny fonts and invisible characters. Parallax
          finds that hidden text and stops your assistant from acting on it.
        </p>
        <div className="flex flex-wrap gap-3">
          <a
            href="#extension"
            className="inline-flex min-h-12 items-center rounded-md bg-white px-6 text-[15px] font-medium text-black transition-colors hover:bg-neutral-300"
          >
            Get the extension
          </a>
          <a
            href="#plugin"
            className="inline-flex min-h-12 items-center rounded-md border border-white px-6 text-[15px] font-medium transition-colors hover:bg-white hover:text-black"
          >
            Get the plugin
          </a>
          <a
            href="#try"
            className="inline-flex min-h-12 items-center rounded-md border border-safe px-6 text-[15px] font-medium text-safe transition-colors hover:bg-safe hover:text-black"
          >
            Try it live
          </a>
        </div>
      </div>

      <ThreatMap />
    </section>
  );
}
