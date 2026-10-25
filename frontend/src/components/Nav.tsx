import Logo from "./Logo";

export default function Nav() {
  return (
    <header className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-4 p-6">
      <a href="#top" className="text-base hover:text-neutral-300">
        <Logo />
      </a>
      <nav aria-label="Main" className="flex flex-wrap items-center gap-7 text-sm text-neutral-400">
        <a href="#problem" className="py-2.5 hover:text-neutral-300 max-sm:hidden">
          The problem
        </a>
        <a href="#how" className="py-2.5 hover:text-neutral-300 max-sm:hidden">
          How it works
        </a>
        <a href="#try" className="py-2.5 hover:text-neutral-300">
          Try it
        </a>
        <a
          href="#get"
          className="inline-flex min-h-11 items-center rounded-md bg-white px-[18px] font-medium text-black transition-colors hover:bg-neutral-300"
        >
          Get Parallax
        </a>
      </nav>
    </header>
  );
}
