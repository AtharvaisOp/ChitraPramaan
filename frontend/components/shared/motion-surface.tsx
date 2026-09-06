"use client";

import { useRef, type ReactNode } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(useGSAP, ScrollTrigger);

export function MotionSurface({ children, motionKey }: { children: ReactNode; motionKey: string }) {
  const scope = useRef<HTMLDivElement>(null);
  useGSAP(() => {
    const media = gsap.matchMedia();
    media.add("(prefers-reduced-motion: no-preference)", () => {
      gsap.fromTo(scope.current, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.55, ease: "power2.out", clearProps: "all" });
      gsap.fromTo("[data-intro]", { opacity: 0, y: 14 }, { opacity: 1, y: 0, stagger: 0.07, duration: 0.65, ease: "power2.out", clearProps: "all" });
      gsap.utils.toArray<HTMLElement>("[data-scroll-reveal]").forEach((element) => {
        gsap.fromTo(element, { opacity: 0.6, y: 12, scale: 0.98 }, {
          opacity: 1, y: 0, scale: 1, duration: 0.7, ease: "power2.out",
          scrollTrigger: { trigger: element, start: "top 94%", once: true }, clearProps: "all",
        });
      });
    });
    return () => media.revert();
  }, { scope, dependencies: [motionKey], revertOnUpdate: true });
  return <div ref={scope} className="motion-surface">{children}</div>;
}
