import { useEffect, useRef } from "react";

type Props = {
  chart: string;
  className?: string;
};

/**
 * Renders Mermaid state diagram (read-only). Dynamic-imports mermaid to keep initial bundle small.
 */
export function LifecycleMermaid({ chart, className }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const text = (chart || "").trim();
    if (!text) {
      el.innerHTML = "";
      return;
    }

    const run = async () => {
      el.innerHTML = "";
      const wrapper = document.createElement("div");
      wrapper.className = "mermaid";
      wrapper.textContent = text;
      el.appendChild(wrapper);
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "loose",
          theme: document.documentElement.classList.contains("dark") ? "dark" : "default",
        });
        await mermaid.run({ nodes: [wrapper] });
      } catch {
        el.innerHTML = "";
        const pre = document.createElement("pre");
        pre.className =
          "text-xs whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-4 text-muted-foreground";
        pre.textContent = text;
        el.appendChild(pre);
      }
    };

    void run();
  }, [chart]);

  return <div ref={hostRef} className={className ?? "overflow-x-auto min-h-[260px] py-2"} />;
}
