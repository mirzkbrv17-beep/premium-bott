import { ReactNode, useEffect, useRef, useState } from "react";
import coinRaw from "@assets/abu_f_coin.svg?raw";
import gemRaw from "@assets/abu_ton_diamond.svg?raw";
import { bindToast, CUR, fmt } from "./lib";

export const Coin = ({ cur, size = 46 }: { cur: string; size?: number }) => (
  <span className="coin" style={{ width: size, height: size, display: "inline-block", flex: "none" }} dangerouslySetInnerHTML={{ __html: cur === "ABU_TON" ? gemRaw : coinRaw }} />
);

export function Sheet({ onClose, children, title }: { onClose: () => void; children: ReactNode; title?: string }) {
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="grab" />
        {title && <h3 style={{ fontSize: 18, marginBottom: 10 }}>{title}</h3>}
        {children}
      </div>
    </div>
  );
}

export function ToastHost() {
  const [t, set] = useState<{ msg: string; kind: string } | null>(null);
  useEffect(() => bindToast(set as any), []);
  return t ? <div className={`toast ${t.kind}`} role="status">{t.msg}</div> : null;
}

export const Skeletons = ({ n = 4, grid = true }: { n?: number; grid?: boolean }) => (
  <div className={grid ? "grid2" : "stack"}>{Array.from({ length: n }, (_, i) => <div key={i} className="skel" style={{ minHeight: grid ? 200 : 70 }} />)}</div>
);
export const Empty = ({ icon = "🫧", text = "Hozircha bo‘sh" }: { icon?: string; text?: string }) => <div className="empty"><div className="big">{icon}</div>{text}</div>;
export const ErrorBox = ({ msg, retry }: { msg: string; retry?: () => void }) => <div className="empty"><div className="big">⚠️</div>{msg}<div style={{ marginTop: 10 }}>{retry && <button className="btn sm" onClick={retry}>Qayta urinish</button>}</div></div>;
export const St = ({ s }: { s: string }) => <span className={`st ${s}`}>{({ success: "muvaffaqiyatli", pending: "kutilmoqda", awaiting_review: "tekshiruvda", failed: "xato", canceled: "bekor", cancelled: "bekor", paid: "to‘langan", processing: "jarayonda", completed: "bajarildi", refunded: "qaytarildi", disputed: "nizo", reserved: "band qilingan", active: "faol", expired: "muddati tugadi", returned: "qaytarildi", held: "escrow", delivered: "topshirildi", open: "ochiq", answered: "javob berildi", closed: "yopiq", rewarded: "mukofotlangan", rejected: "rad etilgan", flagged: "tekshiruvda", hidden: "yashirin", sold_out: "sotilgan", removed: "o‘chirilgan", invited: "taklif", finished: "tugadi", pending_review: "tekshiruvda" } as any)[s] || s}</span>;
export const Switch = ({ on, set }: { on: boolean; set: (v: boolean) => void }) => <div className={`sw ${on ? "on" : ""}`} role="switch" aria-checked={on} onClick={() => set(!on)} />;

export function AnimNumber({ value, hidden }: { value: number; hidden?: boolean }) {
  const [v, setV] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const off = document.documentElement.dataset.anim === "off" || document.documentElement.dataset.lite === "1" || matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (off || from.current === value) { setV(value); from.current = value; return; }
    const start = performance.now(), a = from.current, d = 700; let raf = 0;
    const step = (n: number) => { const p = Math.min(1, (n - start) / d); setV(Math.round(a + (value - a) * (1 - Math.pow(1 - p, 3)))); if (p < 1) raf = requestAnimationFrame(step); else from.current = value; };
    raf = requestAnimationFrame(step); return () => cancelAnimationFrame(raf);
  }, [value]);
  return <>{hidden ? "••••" : fmt(v)}</>;
}

export function Money({ n, cur, sign }: { n: number; cur: string; sign?: boolean }) {
  return <span className={sign ? (n >= 0 ? "pos" : "neg") : ""}>{sign && n > 0 ? "+" : ""}{fmt(n)} {CUR[cur] || cur}</span>;
}

/** Bonus olinganda tanga/olmos balans belgisiga uchib boradi (animatsiya o'chiq bo'lsa ko'rsatilmaydi). */
export function flyCoins(cur: string, from?: HTMLElement | null) {
  const root = document.documentElement;
  if (root.dataset.anim === "off" || root.dataset.lite === "1" || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const target = document.getElementById("bal-target")?.getBoundingClientRect();
  const s = from?.getBoundingClientRect() ?? { left: innerWidth / 2, top: innerHeight / 2, width: 0, height: 0 } as any;
  if (!target) return;
  for (let i = 0; i < 8; i++) {
    const el = document.createElement("div"); el.className = "fly";
    el.innerHTML = cur === "ABU_TON" ? gemRaw : coinRaw;
    el.style.left = s.left + s.width / 2 + (Math.random() * 40 - 20) + "px"; el.style.top = s.top + s.height / 2 + (Math.random() * 30 - 15) + "px";
    el.style.setProperty("--dx", target.left - s.left + "px"); el.style.setProperty("--dy", target.top - s.top + "px"); el.style.animationDelay = i * 70 + "ms";
    document.body.appendChild(el); setTimeout(() => el.remove(), 1200 + i * 70);
  }
}

/** Telegram'ning real formatlari: rasm/GIF -> <img>, WebM -> <video>, Lottie JSON va TGS(gzip) -> lottie-web. */
export function Media({ m, emoji }: { m?: { kind: string; url: string } | null; emoji?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [bad, setBad] = useState(false);
  useEffect(() => {
    if (!m || (m.kind !== "lottie" && m.kind !== "tgs")) return;
    let anim: any, dead = false;
    (async () => {
      try {
        const res = await fetch(m.url); let data: any;
        if (m.kind === "tgs") {
          const ds = new (window as any).DecompressionStream("gzip");
          data = JSON.parse(await new Response(res.body!.pipeThrough(ds)).text());
        } else data = await res.json();
        const lottie = (await import("lottie-web")).default;
        if (!dead && ref.current) anim = lottie.loadAnimation({ container: ref.current, renderer: "svg", loop: true, autoplay: document.documentElement.dataset.anim !== "off", animationData: data });
      } catch { setBad(true); }
    })();
    return () => { dead = true; anim?.destroy(); };
  }, [m?.url, m?.kind]);
  if (!m || bad) return <div className="ph">{emoji || "🎁"}</div>;
  if (m.kind === "webm") return <video src={m.url} autoPlay loop muted playsInline />;
  if (m.kind === "lottie" || m.kind === "tgs") return <div ref={ref} style={{ width: 100, height: 100 }} />;
  return <img src={m.url} alt="" loading="lazy" onError={() => setBad(true)} />;
}

const I = (d: string) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>;
export const Icons = {
  shop: I("M3 10l9-7 9 7v10a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z"),
  nft: I("M12 3l2.6 5.6 6.1.7-4.5 4.2 1.2 6L12 16.5 6.6 19.5l1.2-6L3.3 9.3l6.1-.7z"),
  rent: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>,
  orders: I("M6 8h12l-1 12H7zM9 8a3 3 0 016 0"),
  balance: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><rect x="3" y="6" width="18" height="13" rx="3" /><path d="M16 12.5h2M3 10h18" /></svg>,
};
