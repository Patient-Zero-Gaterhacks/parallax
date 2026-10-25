const OPTIONS = [
  {
    label: "BROWSER EXTENSION",
    title: "Scans what you open.",
    text: "Checks the page you're on and every Gmail message you open, then shows what's hidden in a side panel. Right-click a PDF or Word link to scan the file. Our model runs inside the extension.",
    button: "Get the extension",
    href: "/extension",
  },
  {
    label: "MCP PLUGIN",
    title: "Guards your assistant's tools.",
    text: "Sits between Claude Desktop or Cursor and your MCP servers. It strips hidden text from tool results, hides poisoned tools, and pauses risky actions until you approve them.",
    button: "Get the plugin",
    href: "/plugin",
  },
];

export default function GetStarted() {
  return (
    <section id="get" className="bg-white text-black">
      <div className="mx-auto flex max-w-[1200px] flex-col gap-14 px-6 py-28">
        <div className="flex max-w-[760px] flex-col gap-5">
          <p className="font-mono text-xs tracking-[0.1em] text-neutral-600">03 / GET STARTED</p>
          <h2 className="text-[clamp(32px,4.6vw,60px)] leading-[1.05] font-semibold tracking-[-0.03em] text-balance">
            Two ways to run it.
          </h2>
        </div>
        <div className="flex flex-wrap gap-6">
          {OPTIONS.map((o) => (
            <div
              key={o.label}
              className="flex min-w-0 flex-[1_1_360px] flex-col items-start gap-[18px] rounded-lg border border-black p-8"
            >
              <span className="font-mono text-xs tracking-[0.1em] text-neutral-600">{o.label}</span>
              <h3 className="text-[28px] font-semibold tracking-[-0.02em]">{o.title}</h3>
              <p className="flex-1 leading-relaxed text-neutral-600">{o.text}</p>
              <a
                href={o.href}
                className="inline-flex min-h-12 items-center rounded-md bg-black px-6 text-[15px] font-medium text-white transition-colors hover:bg-neutral-800"
              >
                {o.button}
              </a>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
