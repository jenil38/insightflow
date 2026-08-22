/**
 * Public landing page.
 *
 * Composes the scroll-driven sections. Each section owns its own scroll
 * observers, so they animate independently as they enter the viewport and the
 * page has no central scroll controller to fight with.
 *
 * The fixed mesh + grain layer underneath is what makes the glass panels work:
 * `backdrop-filter` refracts whatever sits behind it, so without colour back
 * there the panels would just look grey. It is fixed rather than scrolling so
 * the hue behind a panel shifts as the page moves, which is what sells the
 * material as translucent.
 */
import { useEffect } from "react";

import { ScrollProgressBar } from "../components/scroll/index.jsx";
import LandingNav from "../features/landing/LandingNav.jsx";
import HeroSection from "../features/landing/HeroSection.jsx";
import PipelineSection from "../features/landing/PipelineSection.jsx";
import QualitySection from "../features/landing/QualitySection.jsx";
import ModelsSection from "../features/landing/ModelsSection.jsx";
import ExplainSection from "../features/landing/ExplainSection.jsx";
import CopilotSection from "../features/landing/CopilotSection.jsx";
import CtaSection from "../features/landing/CtaSection.jsx";

export default function Landing() {
  // The app shell locks scrolling on some routes; make sure the marketing page
  // can always scroll regardless of what a previous route left behind.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  return (
    <div className="relative min-h-screen bg-canvas">
      {/* Backdrop stack, pinned and inert. aria-hidden because it carries no
          information - it exists purely for the glass above it to refract. */}
      <div
        aria-hidden="true"
        className="mesh-bg grain pointer-events-none fixed inset-0 z-0"
      />

      <div className="relative z-10">
        <ScrollProgressBar />
        <LandingNav />
        <main id="main">
          <HeroSection />
          <PipelineSection />
          <QualitySection />
          <ModelsSection />
          <ExplainSection />
          <CopilotSection />
          <CtaSection />
        </main>
      </div>
    </div>
  );
}
