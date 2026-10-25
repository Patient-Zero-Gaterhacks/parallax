import Nav from "../components/Nav";
import Footer from "../components/Footer";

const STEPS = [
  {
    number: "01",
    title: "Download Parallax",
    description:
      "Download the Parallax Chrome extension and extract the ZIP file. Keep the extracted folder somewhere easy to find.",
  },
  {
    number: "02",
    title: "Open Chrome Extensions",
    description:
      "Open a new Chrome tab and visit chrome://extensions. Enable Developer mode in the top-right corner.",
  },
  {
    number: "03",
    title: "Load the extension",
    description:
      'Click "Load unpacked" and select the extension/ folder containing manifest.json, not the repository or ZIP folder.',
  },
  {
    number: "04",
    title: "Pin Parallax",
    description:
      "Click the puzzle-piece icon in your Chrome toolbar and pin Parallax for quick access.",
  },
  {
    number: "05",
    title: "Start scanning",
    description:
      "Refresh tabs that were already open, then open Parallax from your toolbar. Basic page scanning works offline; the hosted server enables the additional features.",
  },
];

export default function ComingSoon({
  label,
  title,
}: {
  label: string;
  title: string;
}) {
  const isExtension = label.toLowerCase().includes("extension");

  // Keep the MCP plugin placeholder unchanged.
  if (!isExtension) {
    return (
      <>
        <Nav />
        <main className="mx-auto flex min-h-[60vh] max-w-[1200px] flex-col items-start gap-5 px-6 pt-12 pb-28">
          <p className="font-mono text-xs tracking-[0.1em] text-neutral-500 uppercase">
            {label}
          </p>

          <h1 className="text-[clamp(36px,5vw,60px)] leading-[1.05] font-semibold tracking-[-0.03em]">
            {title}
          </h1>

          <p className="max-w-[520px] text-lg text-neutral-400">
            Install instructions are coming soon.
          </p>

          <a
            href="#get"
            className="mt-3 inline-flex min-h-12 items-center rounded-md border border-white px-6 text-[15px] font-medium transition-colors hover:bg-white hover:text-black"
          >
            Back to home
          </a>
        </main>
        <Footer />
      </>
    );
  }

  // Browser extension installation guide.
  return (
    <>
      <Nav />

      <main className="bg-white text-black">
        <section className="mx-auto max-w-[1200px] px-6 pt-20 pb-28">

          {/* Header */}
          <div className="mb-20 max-w-[760px]">
            <p className="mb-6 font-mono text-xs tracking-[0.1em] text-neutral-500">
              PARALLAX / BROWSER EXTENSION
            </p>

            <h1 className="mb-6 text-[clamp(38px,5vw,68px)] leading-[1.05] font-semibold tracking-[-0.04em]">
              Protection starts
              <br />
              with one install.
            </h1>

            <p className="max-w-[570px] text-lg leading-relaxed text-neutral-600">
              Add Parallax to Chrome and see what suspicious content
              might be hiding in the pages, emails, and files you open.
            </p>
          </div>

          {/* Installation */}
          <div className="grid gap-16 border-t border-neutral-200 pt-14 lg:grid-cols-[1fr_1.5fr]">

            <div>
              <p className="mb-5 font-mono text-xs tracking-[0.1em] text-neutral-500">
                01 / INSTALLATION
              </p>

              <h2 className="mb-5 text-3xl font-semibold tracking-[-0.03em]">
                Get up and running.
              </h2>

              <p className="mb-8 max-w-[340px] leading-relaxed text-neutral-600">
                Follow these steps to add the Parallax extension
                to your Chrome browser.
              </p>

              <div className="rounded-lg border border-neutral-200 p-5">
                <p className="mb-2 font-mono text-xs tracking-[0.1em] text-neutral-500">
                  BEFORE YOU BEGIN
                </p>

                <p className="text-sm leading-relaxed text-neutral-600">
                  You'll need Google Chrome and the extracted
                  Parallax extension folder.
                </p>
              </div>
            </div>

            {/* Steps */}
            <div className="flex flex-col">
              {STEPS.map((step) => (
                <div
                  key={step.number}
                  className="flex gap-7 border-b border-neutral-200 py-7 first:pt-0"
                >
                  <span className="shrink-0 font-mono text-sm text-neutral-400">
                    {step.number}
                  </span>

                  <div>
                    <h3 className="mb-3 text-xl font-semibold tracking-[-0.02em]">
                      {step.title}
                    </h3>

                    <p className="max-w-[540px] leading-relaxed text-neutral-600">
                      {step.description}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Connection information */}
          <div className="mt-20 border-t border-neutral-200 pt-12">
            <p className="mb-3 font-mono text-xs tracking-[0.1em] text-neutral-500">
              02 / CONNECTION
            </p>

            <h2 className="mb-4 text-2xl font-semibold tracking-[-0.02em]">
              Hosted scanning, ready to try.
            </h2>

            <p className="max-w-[640px] leading-relaxed text-neutral-600">
              The extension uses the hosted scanning server by default. You do not need
              to start Python to try it. Basic page scanning also works offline;
              file scanning, AI-bot comparisons, and Gemma assessment need a reachable
              server, with Gemma configured for assessment.
            </p>

            <p className="mt-4 max-w-[640px] leading-relaxed text-neutral-600">
              With no saved address, Parallax checks the hosted server for up to three
              seconds and selects localhost if that health check fails. A saved server
              address overrides this selection. Failed scan requests do not automatically
              switch servers.
            </p>
            <p className="mt-4 max-w-[640px] leading-relaxed text-neutral-600">
              Local setup is optional: follow the repository README to run the backend,
              then open the extension popup → Server settings, enter
              http://localhost:8787, and choose Save server. You can use the same field
              for another hosted backend.
            </p>
          </div>

          {/* Back to home */}
          <div className="mt-20 border-t border-neutral-200 pt-10">
            <a
              href="#get"
              className="inline-flex min-h-12 items-center rounded-md border border-black px-6 text-[15px] font-medium transition-colors hover:bg-black hover:text-white"
            >
              Back to home
            </a>
          </div>

        </section>
      </main>

      <Footer />
    </>
  );
}
