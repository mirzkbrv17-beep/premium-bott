import { useState } from "react";
import { get, t, useAsync, post, go, fmt, CUR, toast } from "../lib";
import type { Cat, Product } from "../api";
import { Empty, ErrorBox, Media, Skeletons, Sheet, flyCoins } from "../ui";
import { useSubmit, PayChooser } from "./Shared";

export default function Shop() {
  const [cat, setCat] = useState("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("new");
  const cats = useAsync(() => get<Cat[]>("/api/shop/categories"), []);
  const list = useAsync(() => get<Product[]>(`/api/shop/products?${new URLSearchParams({ ...(cat !== "all" ? { category: cat } : {}), ...(q ? { q } : {}), sort })}`), [cat, q, sort]);
  const [open, setOpen] = useState<Product | null>(null);
  const shopCats = (cats.data ?? []).filter((c) => c.kind === "goods");
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Qidirish" />
        <select value={sort} onChange={(e) => setSort(e.target.value)} style={{ width: 130 }} aria-label="Saralash">
          <option value="new">Yangi</option><option value="price_asc">Arzon</option><option value="price_desc">Qimmat</option>
        </select>
      </div>
      <div className="chips">
        <div className={`chip ${cat === "all" ? "on" : ""}`} onClick={() => setCat("all")}>{t("all")}</div>
        {shopCats.map((c) => <div key={c.slug} className={`chip ${cat === c.slug ? "on" : ""}`} onClick={() => setCat(c.slug)}>{c.icon} {c.name.uz}</div>)}
      </div>
      {list.error ? <ErrorBox msg={list.error} retry={list.reload} /> : list.loading ? <Skeletons /> : !list.data?.length ? <Empty icon="🛍" text="Bu bo‘limda hozircha mahsulot yo‘q" /> : (
        <div className="grid2">
          {list.data.map((p) => <ProductCard key={p.id} p={p} onOpen={() => setOpen(p)} />)}
        </div>
      )}
      {open && <BuySheet p={open} onClose={() => setOpen(null)} />}
    </>
  );
}

export function ProductCard({ p, onOpen }: { p: Product; onOpen: () => void }) {
  return (
    <div className={`pcard ${p.available ? "" : "off"}`} style={{ ["--c" as any]: p.color }} onClick={onOpen} role="button" tabIndex={0} aria-label={p.title}>
      {p.discount_percent > 0 && <span className="badge">-{p.discount_percent}%</span>}
      <div className="media"><Media m={p.media} emoji={p.category === "premium" ? "⭐" : "🎁"} /></div>
      <div className="nm">{p.title}</div>
      <div className="sb">{p.subtitle || ""}</div>
      <div className="price">
        <span>{p.discount_percent > 0 && <i className="old">{fmt(p.price_uzs)}</i>}{fmt(p.final_price_uzs)} so‘m</span>
      </div>
      {!p.available && <div className="sb" style={{ marginTop: 4 }}>{t("out_of_stock")}</div>}
    </div>
  );
}

function BuySheet({ p, onClose }: { p: Product; onClose: () => void }) {
  const [cur, setCur] = useState("ABU_F");
  const [qty, setQty] = useState(1);
  const { busy, submit } = useSubmit();
  const pkgs = useAsync(() => get("/api/topup/options"), []);
  const [topupUnits, setTopup] = useState(100);
  const isTopup = p.action !== "buy";

  const buy = async (e: any) => {
    const r = await submit((key) => post("/api/shop/orders", { product_id: p.id, qty, pay_currency: cur, idempotency_key: key }), "Buyurtma qabul qilindi ✅");
    if (r) { flyCoins(cur, e?.currentTarget); onClose(); go("orders"); }
  };
  const topup = async (e: any) => {
    const isF = p.action === "topup_f";
    const body = isF ? { currency: "ABU_F", provider: "manual_card", units: topupUnits } : { currency: "ABU_TON", provider: "manual_card", package_id: topupUnits };
    const r = await submit((key) => post("/api/topup", { ...body, idempotency_key: key }));
    if (r) { onClose(); if (r.pay?.type === "manual") toast(`To‘lovdan so‘ng chekni shu botga skrinshot qilib yuboring.`, "ok"); go("balance/topups"); }
  };

  const sumF = qty * p.final_price_uzs / (pkgs.data?.abu_f?.uzs_per_unit || 10);
  return (
    <Sheet onClose={onClose} title={p.title}>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div className="pcard" style={{ ["--c" as any]: p.color, width: 120, minHeight: 130, padding: 8, cursor: "default" }}><div className="media"><Media m={p.media} emoji="🎁" /></div></div>
        <div className="sp">
          <div className="muted">{p.subtitle}</div>
          <div style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{fmt(p.final_price_uzs)} so‘m</div>
          {p.stock !== null && <div className="muted">Omborda: {p.stock}</div>}
        </div>
      </div>
      {p.description && <p className="muted">{p.description}</p>}
      {!isTopup ? (
        <>
          <label>To‘lov valyutasi</label>
          <PayChooser value={cur} set={setCur} f={true} ton={true} />
          {p.stock !== null && p.stock > 1 && (
            <div className="row" style={{ marginTop: 8 }}>
              <span className="sp">Soni</span>
              <button className="btn sm" onClick={() => setQty(Math.max(1, qty - 1))}>−</button><b>{qty}</b><button className="btn sm" onClick={() => setQty(Math.min(p.stock!, qty + 1))}>+</button>
            </div>
          )}
          <div className="glass" style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}><span>Jami</span><b>{fmt(qty * p.final_price_uzs)} so‘m ≈ {fmt(Math.ceil(sumF))} {CUR[cur]}</b></div>
          <button className="btn gold block" style={{ marginTop: 14 }} disabled={busy || !p.available} onClick={buy}>{busy ? "..." : t("buy")}</button>
        </>
      ) : (
        <>
          <label>{p.action === "topup_f" ? `Miqdor (ABU F, min ${pkgs.data?.abu_f?.min_units ?? 5})` : "Paket"}</label>
          {p.action === "topup_f" ? (
            <input type="number" min={pkgs.data?.abu_f?.min_units ?? 5} value={topupUnits} onChange={(e) => setTopup(Number(e.target.value))} />
          ) : (
            <div className="grid2">{(pkgs.data?.abu_ton_packages ?? []).map((k: any) => (
              <div key={k.id} className={`chip ${topupUnits === k.id ? "on" : ""}`} style={{ textAlign: "center" }} onClick={() => setTopup(k.id)}>💠 {k.units} · {fmt(k.price_uzs)} so‘m</div>
            ))}</div>
          )}
          <button className="btn gold block" style={{ marginTop: 14 }} disabled={busy} onClick={topup}>{t("topup")}</button>
        </>
      )}
    </Sheet>
  );
}
