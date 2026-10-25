import Nav from "../components/Nav";
import Hero from "../components/Hero";
import Problem from "../components/Problem";
import HowItWorks from "../components/HowItWorks";
import GetStarted from "../components/GetStarted";
import Footer from "../components/Footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <Problem />
        <HowItWorks />
        <GetStarted />
      </main>
      <Footer />
    </>
  );
}
