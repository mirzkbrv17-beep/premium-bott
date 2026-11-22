import { useState } from "react";
import { get, useAsync } from "../lib";
import type { Item } from "../api";
import { Empty, ErrorBox, Media, Skeletons } from "../ui";
import { useSubmit } from "./Shared";
import { post, go, fmt, t } from "../lib";
import { flyCoins, Sheet } from "../ui";

export default function Nft() {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("new");
  const list = useAsync(() => get<Item[]>(`/api/shop/nft?${new URLSearchParams({ ...(q ? { q } : {}), sort })}`), [q, sort]);
  const [open, setOpen] = useState<Item | null>(null);
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label="NFT qidirish" />
        <select value={sort} onChange={(e) => setSort(e.target.value)} style={{ width: 130 }} aria-label="Saralash">
          <option value="new">Yangi</option><option value="price_asc">Arzon</option><option value="price_desc">Qimmat</option>
        </select>
      </div>
      {list.error ? <ErrorBox msg={list.error} retry={list.reload} /> : list.loading ? <Skeletons /> : !list.data?.length ? <Empty icon="💎" text="NFT yo‘q" /> : (
        <div className="grid2">{list.data.map((i) => <ItemCard key={i.id} i={i} onOpen={() => setOpen(i)} />)}</div>
      )}
      {open && <NftSheet i={open} onClose={() => setOpen(null)} />}
    </>
  );
}

export function ItemCard({ i, onOpen, rent }: { i: Item; onOpen: () => void; rent?: boolean }) {
  return (
    <div className={`pcard ${i.available ? "" : "off"}`} style={{ ["--c" as any]: i.color }} onClick={onOpen} role="button" tabIndex={0} aria-label={i.title}>
      {rent && i.max_days && <span className="badge">{i.min_days}–{i.max_days} kun</span>}
      <div className="media"><Media m={i.media} /></div>
      <div className="nm">{i.title}</div>
      <div className="sb">{i.subtitle}</div>
      <div className="price"><span>{rent ? `${fmt(i.rent_price_per_day!)} so‘m / kun dan` : `${fmt(i.price_uzs)} so‘m`}</span></div>
    </div>
  );
}

function NftSheet({ i, onClose }: { i: Item; onClose: () => void }) {
  const { busy, submit } = useSubmit();
  const buy = async (e: any, cur: string) => {
    const r = await submit((key) => post("/api/shop/orders", { product_id: i.product_id, inventory_item_id: i.id, qty: 1, pay_currency: cur, idempotency_key: key }), "Sotib olindi ✅");
    if (r) { flyCoins(cur, e?.currentTarget); onClose(); go("orders"); }
  };
  return (
    <Sheet onClose={onClose} title={`${i.title} ${i.ref}`}>
      <div className="row" style={{ alignItems: "flex-start" }}>
        <div className="pcard" style={{ ["--c" as any]: i.color, width: 140, minHeight: 150, padding: 8, cursor: "default" }}><div className="media"><Media m={i.media} /></div></div>
        <div className="sp">
          {Object.entries(i.attrs || {}).map(([k, v]) => <div key={k} className="muted">{k}: <b style={{ color: "var(--tx)" }}>{String(v)}</b></div>)}
          <div style={{ fontSize: 20, fontWeight: 800, marginTop: 8 }}>{fmt(i.price_uzs)} so‘m</div>
        </div>
      </div>
      <div className="row" style={{ marginTop: 14 }}>
        <button className="btn gold sp" disabled={busy || !i.available} onClick={(e) => buy(e, "ABU_F")}>🪙 ABU F bilan</button>
        <button className="btn sp" disabled={busy || !i.available} onClick={(e) => buy(e, "ABU_TON")}>💠 ABU TON bilan</button>
      </div>
    </Sheet>
  );
}
