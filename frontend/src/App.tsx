import { useEffect, useState } from "react";
import Home from "./pages/Home";
import ComingSoon from "./pages/ComingSoon";

// Simple page switching with the part of the URL after "#".
// "#extension" and "#plugin" open their own pages; anything else shows the home page
// (and "#problem", "#how", "#get" scroll to that section).
type Page = "home" | "extension" | "plugin";

function pageFromUrl(): Page {
  const hash = window.location.hash.slice(1);
  return hash === "extension" || hash === "plugin" ? hash : "home";
}

export default function App() {
  const [page, setPage] = useState<Page>(pageFromUrl);

  useEffect(() => {
    const onChange = () => setPage(pageFromUrl());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  // When the page changes, start at the top (or at the section the link pointed to).
  useEffect(() => {
    const section = document.getElementById(window.location.hash.slice(1));
    if (page === "home" && section) section.scrollIntoView();
    else window.scrollTo(0, 0);
  }, [page]);

  if (page === "extension") {
    return <ComingSoon label="Browser extension" title="Get the extension" />;
  }
  if (page === "plugin") {
    return <ComingSoon label="MCP plugin" title="Get the plugin" />;
  }
  return <Home />;
}
