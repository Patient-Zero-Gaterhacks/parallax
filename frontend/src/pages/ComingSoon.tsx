import type { ReactNode } from "react";
import Nav from "../components/Nav";
import Footer from "../components/Footer";

const REPO = "https://github.com/Patient-Zero-Gaterhacks/parallax";
const ZIP = `${REPO}/archive/refs/heads/main.zip`;

const code = "rounded bg-neutral-900 px-1.5 py-0.5 font-mono text-[0.9em] text-neutral-200";
const link = "text-white underline decoration-neutral-600 underline-offset-4 transition-colors hover:decoration-white";

function Header({ label, title, intro }: { label: string; title: string; intro: string }) {
  return (
    <>
      <p className="font-mono text-xs tracking-[0.1em] text-neutral-500 uppercase">{label}</p>
      <h1 className="mt-4 text-[clamp(36px,5vw,60px)] leading-[1.05] font-semibold tracking-[-0.03em]">{title}</h1>
      <p className="mt-4 max-w-[560px] text-lg text-neutral-400">{intro}</p>
    </>
  );
}

function BackHome() {
  return (
    <a
      href="#get"
      className="mt-12 inline-flex min-h-12 items-center rounded-md border border-white px-6 text-[15px] font-medium transition-colors hover:bg-white hover:text-black"
    >
      Back to home
    </a>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-5 border-t border-neutral-800 py-7">
      <span className="shrink-0 pt-1 font-mono text-sm text-neutral-500">{String(n).padStart(2, "0")}</span>
      <div className="min-w-0">
        <h2 className="text-xl font-semibold tracking-[-0.02em]">{title}</h2>
        <div className="mt-2 leading-relaxed text-neutral-400">{children}</div>
      </div>
    </li>
  );
}

function ExtensionPage({ label, title }: { label: string; title: string }) {
  return (
    <>
      <Header label={label} title={title} intro="Takes about two minutes. No account needed." />

      <ol className="mt-12 max-w-[640px]">
        <Step n={1} title="Download it">
          <a
            href={ZIP}
            className="mb-3 inline-flex min-h-12 items-center rounded-md bg-white px-6 text-[15px] font-medium text-black transition-colors hover:bg-neutral-200"
          >
            Download Parallax (.zip)
          </a>
          <p>Unzip it once it's downloaded.</p>
        </Step>
        <Step n={2} title="Add it to Chrome">
          Go to <span className={code}>chrome://extensions</span>, turn on Developer mode (top right), click Load
          unpacked, and choose the parallax-main → extension folder.
        </Step>
        <Step n={3} title="Check that it works">
          Open <a href="#try" className={link}>Am I protected?</a> It should say you're protected.
        </Step>
      </ol>

      <p className="max-w-[640px] border-t border-neutral-800 pt-7 text-neutral-400">
        Tip: click the puzzle piece in Chrome's toolbar and pin Parallax.
      </p>

      <p className="mt-8 text-sm text-neutral-500">
        Want to run your own server or change settings?{" "}
        <a href={`${REPO}#2-chrome-extension`} className="text-neutral-300 transition-colors hover:text-white">
          Full guide on GitHub →
        </a>
      </p>
    </>
  );
}

function PluginPage({ label, title }: { label: string; title: string }) {
  return (
    <>
      <Header
        label={label}
        title={title}
        intro="Parallax also protects AI assistants that use tools, like reading your email."
      />

      <ul className="mt-10 flex max-w-[640px] flex-col gap-3 text-neutral-300">
        {[
          "Removes hidden instructions from what tools return (like an email the AI reads)",
          "Catches tools with poisoned descriptions",
          "Pauses risky actions, like sending an email, until you approve them",
        ].map((item) => (
          <li key={item} className="flex gap-3 leading-relaxed">
            <span className="mt-[0.6em] h-1.5 w-1.5 shrink-0 rounded-full bg-neutral-500" aria-hidden="true" />
            {item}
          </li>
        ))}
      </ul>

      <p className="mt-8 max-w-[640px] leading-relaxed text-neutral-400">
        Works with Claude Desktop, Cursor and Claude Code. It comes with a demo inbox so you can try it safely.
      </p>

      <a
        href={`${REPO}#4-mcp-gateway-claude-desktop-cursor-claude-code`}
        className="mt-8 inline-flex min-h-12 items-center rounded-md bg-white px-6 text-[15px] font-medium text-black transition-colors hover:bg-neutral-200"
      >
        Setup guide on GitHub →
      </a>
    </>
  );
}

// The two install pages: #extension and #plugin.
export default function ComingSoon({ label, title }: { label: string; title: string }) {
  const isExtension = label.toLowerCase().includes("extension");
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-[1200px] px-6 pt-12 pb-28">
        {isExtension ? <ExtensionPage label={label} title={title} /> : <PluginPage label={label} title={title} />}
        <div>
          <BackHome />
        </div>
      </main>
      <Footer />
    </>
  );
}
