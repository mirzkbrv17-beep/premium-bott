import { useEffect, useState } from "react";
import { applyAnimSettings, get, go, loginTelegram, t, tg, useRoute, ApiError, setLang } from "./lib";
import { Icons, ToastHost } from "./ui";
import type { Me } from "./api";
import Shop from "./pages/Shop";
import Nft from "./pages/Nft";
import Rent from "./pages/Rent";
import Orders from "./pages/Orders";
import Cabinet from "./pages/Cabinet";
import Balance from "./pages/Balance";
import Admin from "./pages/Admin";
import { Subscribe, Detail } from "./pages/Gates";

export const MeCtx: { me: Me | null; refresh: () => Promise<void> } = { me: null, refresh: async () => {} };
export const reloadMe = () => MeCtx.refresh();

const TABS = [
  { k: "shop", icon: Icons.shop, label: () => t("shop") },
  { k: "nft", icon: Icons.nft, label: () => t("nft") },
  { k: "rent", icon: Icons.rent, label: () => t("rent") },
  { k: "orders", icon: Icons.orders, label: () => t("orders") },
  { k: "balance", icon: Icons.balance, label: () => t("balance") },
];

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "subscribe" | "error">("loading");
  const [err, setErr] = useState("");
  const route = useRoute();

  const boot = async () => {
    setState("loading");
    try {
      const r = await loginTelegram();
      setMe(r.me); setLang(r.me.settings?.language || "uz");
      applyAnimSettings(r.me.settings?.animations || "auto");
      const sub = await get("/api/subscription");
      setState(sub.ok || sub.unverifiable ? "ready" : "subscribe");
    } catch (e: any) {
      setErr(e instanceof ApiError && e.status === 401 ? "Sessiya tugadi. Qayta oching." : e.message);
      setState("error");
    }
  };
  useEffect(() => {
    tg()?.setHeaderColor?.("#07070b"); tg()?.setBackgroundColor?.("#07070b");
    boot();
    MeCtx.refresh = async () => { try { setMe(await get("/api/me")); } catch { /* */ } };
  }, []);

  if (state === "loading") return <div className="app"><div className="skel" style={{ height: 180, marginTop: 40 }} /></div>;
  if (state === "error") return <div className="app"><div className="empty"><div className="big">🔒</div>{err}<div style={{ marginTop: 14 }}><button className="btn gold" onClick={boot}>Qayta urinish</button></div></div></div>;
  if (state === "subscribe") return <Subscribe onOk={boot} />;

  const tab = route[0];
  const sub = route[1];
  const isAdmin = tab === "admin";
  const page = (() => {
    switch (tab) {
      case "nft": return <Nft />;
      case "rent": return <Rent />;
      case "orders": return <Orders />;
      case "balance": return <Balance sub={sub} />;
      case "cabinet": return <Cabinet sub={sub} />;
      case "product": return <Detail id={sub} />;
      case "admin": return me?.is_admin ? <Admin /> : <div className="empty">Ruxsat yo‘q</div>;
      default: return <Shop />;
    }
  })();
  const active = TABS.find((x) => x.k === tab)?.k ?? (tab === "cabinet" ? "" : "shop");

  return (
    <MeContext.Provider value={{ me, refresh: MeCtx.refresh }}>
      <div className={isAdmin ? "app admin" : "app"}>
        {!isAdmin && <Header me={me} />}
        {page}
      </div>
      {!isAdmin && (
        <nav className="nav" aria-label="Asosiy">
          {TABS.map((x) => (
            <a key={x.k} href={`#/${x.k}`} className={active === x.k ? "on" : ""}>{x.icon}<span>{x.label()}</span></a>
          ))}
        </nav>
      )}
      <ToastHost />
    </MeContext.Provider>
  );
}

import { createContext, useContext } from "react";
export const MeContext = createContext<{ me: Me | null; refresh: () => Promise<void> }>({ me: null, refresh: async () => {} });
export const useMe = () => useContext(MeContext);

function Header({ me }: { me: Me | null }) {
  const name = me?.first_name || "";
  return (
    <div className="top">
      <h1>ABU {me?.vip ? me.vip.badge : ""}</h1>
      <span className="pill" onClick={() => go("cabinet")}>⭐ {me?.level.level ?? 1}-daraja</span>
      <div className="avatar" onClick={() => go("cabinet")} title={name}>
        {me?.photo_url ? <img src={me.photo_url} alt="" /> : (name[0] || "A")}
      </div>
    </div>
  );
}
