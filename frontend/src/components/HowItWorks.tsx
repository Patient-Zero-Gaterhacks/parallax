const STEPS = [
  {
    number: "01",
    title: "Find",
    text: "Parallax compares what a person would see with what the AI receives: text colored to match the background, hidden boxes, tiny fonts, text pushed off the page, invisible characters, and pages that show AI agents different content.",
  },
  {
    number: "02",
    title: "Judge",
    text: "Each hidden passage gets checked. Is it talking to an AI? Does it add an email address, link, phone number or amount you never saw? Pattern rules and our trained model check every passage, and Gemma can give a second opinion.",
  },
  {
    number: "03",
    title: "Stop",
    text: "Threats are flagged and held back. Your assistant can still read the email, but it can't pay, send or remember anything that came only from text you couldn't see.",
  },
];

export default function HowItWorks() {
  return (
    <section id="how" className="bg-black">
      <div className="mx-auto flex max-w-[1200px] flex-col gap-14 px-6 py-28">
        <div className="flex max-w-[760px] flex-col gap-5">
          <p className="font-mono text-xs tracking-[0.1em] text-neutral-500">02 / HOW IT WORKS</p>
          <h2 className="text-[clamp(32px,4.6vw,60px)] leading-[1.05] font-semibold tracking-[-0.03em] text-balance">
            Three steps, before your AI acts.
          </h2>
        </div>
        <div className="flex flex-wrap gap-x-8 gap-y-10">
          {STEPS.map((s) => (
            <div key={s.number} className="flex min-w-0 flex-[1_1_280px] flex-col gap-3.5 border-t border-white pt-6">
              <span className="font-mono text-[13px] text-neutral-500">{s.number}</span>
              <h3 className="text-2xl font-semibold tracking-[-0.02em]">{s.title}</h3>
              <p className="leading-relaxed text-neutral-400">{s.text}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
