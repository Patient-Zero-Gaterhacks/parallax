import Logo from "./Logo";

export default function Footer() {
  return (
    <footer className="bg-black">
      <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-x-8 gap-y-4 px-6 pt-10 pb-14 font-mono text-xs text-neutral-500">
        <span className="text-white">
          <Logo size={22} />
        </span>
        <span>Built at Gator Hack V, University of Florida</span>
        <a href="https://github.com/Patient-Zero-Gaterhacks/parallax" className="hover:text-neutral-300">
          GitHub
        </a>
        <span>Globe and feed are simulated, not real data.</span>
      </div>
    </footer>
  );
}
