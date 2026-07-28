import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import Brand from "./Brand";
import Inbox from "./Inbox";
import Social from "./Social";

/** Order matters: campaigns first, then the inbox, then the brand setup. */
const SECTIONS = [
  { id: "campaigns", label: "Campaigns", blurb: "Plan and review posts", Component: Social },
  { id: "inbox", label: "Inbox", blurb: "Reply to comments", Component: Inbox },
  { id: "brand", label: "Brand", blurb: "Voice and knowledge", Component: Brand },
] as const;

const GAP = 16; // breathing room between the sticky bars and a section heading

/**
 * All three social screens on one page.
 *
 * The offsets are measured at runtime rather than hardcoded: the app header
 * grows a second row on mobile, so a fixed pixel value would park headings
 * underneath it on one breakpoint or leave a gap on the other.
 */
export default function SocialHub() {
  const { hash } = useLocation();
  const barRef = useRef<HTMLDivElement>(null);
  const [headerHeight, setHeaderHeight] = useState(0);
  const [barHeight, setBarHeight] = useState(0);
  const [active, setActive] = useState<string>(SECTIONS[0].id);

  useLayoutEffect(() => {
    const header = document.querySelector("header");
    if (!header) return;
    const measure = () => {
      setHeaderHeight(header.getBoundingClientRect().height);
      setBarHeight(barRef.current?.getBoundingClientRect().height ?? 0);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(header);
    if (barRef.current) observer.observe(barRef.current);
    return () => observer.disconnect();
  }, []);

  const offset = headerHeight + barHeight + GAP;

  const scrollToSection = useCallback(
    (id: string, behavior: ScrollBehavior = "smooth") => {
      const el = document.getElementById(id);
      if (!el) return;
      // Light up the target immediately. Waiting for the scroll listener leaves
      // the wrong pill highlighted whenever the destination can't reach the top
      // of the viewport, which is normal for the last section.
      setActive(id);
      const top = el.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top: Math.max(top, 0), behavior });
    },
    [offset]
  );

  // Deep links like /social#inbox still land in the right place. All three
  // sections fetch their own data, so the page keeps growing for a beat after
  // mount and a single scroll fires against a layout that no longer exists.
  //
  // Re-anchor on a fixed schedule rather than stopping as soon as two
  // measurements agree: mid-fetch the layout holds still for a moment and looks
  // settled, so an early exit strands the reader at a stale offset.
  useEffect(() => {
    if (!hash) return;
    const id = hash.slice(1);
    let ticks = 0;

    const timer = window.setInterval(() => {
      scrollToSection(id, "auto");
      if (++ticks >= 16) window.clearInterval(timer);
    }, 100);

    // Hand control back the instant the reader takes it.
    const stop = () => window.clearInterval(timer);
    const events = ["wheel", "touchstart", "keydown"] as const;
    events.forEach((e) => window.addEventListener(e, stop, { passive: true, once: true }));

    return () => {
      window.clearInterval(timer);
      events.forEach((e) => window.removeEventListener(e, stop));
    };
  }, [hash, scrollToSection]);

  // Highlight whichever section the reader is currently in.
  useEffect(() => {
    const onScroll = () => {
      const line = offset + 1;
      let current: string = SECTIONS[0].id;
      for (const section of SECTIONS) {
        const el = document.getElementById(section.id);
        if (el && el.getBoundingClientRect().top <= line) current = section.id;
      }
      // Once the document bottom is reached the last section is what's on
      // screen, even if it never rose past the line — a short final section
      // otherwise leaves the previous pill lit.
      const doc = document.documentElement;
      if (window.scrollY + window.innerHeight >= doc.scrollHeight - 2) {
        current = SECTIONS[SECTIONS.length - 1].id;
      }
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [offset]);

  return (
    <div>
      <div
        ref={barRef}
        className="sticky z-20 -mx-6 mb-6 px-6 py-3"
        style={{
          top: headerHeight,
          background: "rgba(251,246,238,.92)",
          backdropFilter: "blur(10px)",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <nav className="flex items-center gap-2 overflow-x-auto">
          {SECTIONS.map((section) => {
            const isActive = active === section.id;
            return (
              <button
                key={section.id}
                onClick={() => scrollToSection(section.id)}
                aria-current={isActive ? "true" : undefined}
                className="flex shrink-0 items-baseline gap-2 rounded-full px-4 py-2 text-sm transition"
                style={
                  isActive
                    ? { background: "var(--ink-strong)", color: "var(--cream-text)", fontWeight: 700 }
                    : { background: "var(--surface-2)", color: "var(--muted)", fontWeight: 600 }
                }
              >
                {section.label}
                <span
                  className="hidden text-xs font-normal sm:inline"
                  style={{ color: isActive ? "var(--on-espresso-accent)" : "var(--muted-2)" }}
                >
                  {section.blurb}
                </span>
              </button>
            );
          })}
        </nav>
      </div>

      {SECTIONS.map(({ id, Component }, index) => (
        <section
          key={id}
          id={id}
          className={index > 0 ? "mt-14 border-t pt-14" : undefined}
          style={{ scrollMarginTop: offset, borderColor: "var(--border)" }}
        >
          <Component />
        </section>
      ))}

      {/* Lets the last section scroll up under the nav. Without it the browser
          clamps at the bottom of the document and the Brand button looks like
          it did nothing. */}
      <div aria-hidden className="h-[45vh]" />
    </div>
  );
}
