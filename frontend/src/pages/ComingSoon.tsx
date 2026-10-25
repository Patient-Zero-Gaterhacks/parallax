import Nav from "../components/Nav";
import Footer from "../components/Footer";

// Placeholder for the "Get the extension" and "Get the plugin" pages.
// Install instructions go here once we've tested both.
export default function ComingSoon({ label, title }: { label: string; title: string }) {
  return (
    <>
      <Nav />
      <main className="mx-auto flex min-h-[60vh] max-w-[1200px] flex-col items-start gap-5 px-6 pt-12 pb-28">
        <p className="font-mono text-xs tracking-[0.1em] text-neutral-500 uppercase">{label}</p>
        <h1 className="text-[clamp(36px,5vw,60px)] leading-[1.05] font-semibold tracking-[-0.03em]">{title}</h1>
        <p className="max-w-[520px] text-lg text-neutral-400">Install instructions are coming soon.</p>
        <a
          href="#top"
          className="mt-3 inline-flex min-h-12 items-center rounded-md border border-white px-6 text-[15px] font-medium transition-colors hover:bg-white hover:text-black"
        >
          Back to home
        </a>
      </main>
      <Footer />
    </>
  );
}
