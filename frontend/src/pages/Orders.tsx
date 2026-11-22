import { useState } from "react";
import { get, post, go, fdate, fmt, useAsync, t } from "../lib";
import type { Order, Rental } from "../api";
import { Empty, ErrorBox, Skeletons, Sheet, St } from "../ui";
import { Tabs, useSubmit } from "./Shared";

export default function Orders() {
  const [tab, setTab] = useState<"orders" | "rentals" | "market">("orders");
  return (
    <>
      <div className="top"><h1>{t("orders")}</h1></div>
      <Tabs value={tab} set={setTab} items={[["orders", "Xaridlar"], ["rentals", "Ijaralar"], ["market", "Market"]]} />
      {tab === "orders" && <OrdersList />}
      {tab === "rentals" && <RentalsList />}
      {tab === "market" && <MarketOrders />}
    </>
  );
}

function OrdersList() {
  const list = useAsync(() => get<Order[]>("/api/orders"), []);
  const [open, setOpen] = useState<Order | null>(null);
  if (list.error) return <ErrorBox msg={list.error} retry={list.reload} />;
  if (list.loading) return <Skeletons n={3} grid={false} />;
  if (!list.data?.length) return <Empty icon="🧾" text="Hozircha buyurtma yo‘q" />;
  return (
    <div className="glass">
      {list.data.map((o) => (
        <div key={o.id} className="tx" onClick={() => setOpen(o)} role="button">
          <div className="ic">{o.kind === "rent" ? "🕒" : "🛒"}</div>
          <div className="sp"><b>{o.items[0]?.title ?? o.public_id}</b><div className="muted">{fdate(o.created_at)}</div></div>
          <div style={{ textAlign: "right" }}><div className="amt">{fmt(o.pay_amount)} {o.pay_currency.replace("_", " ")}</div><St s={o.status} /></div>
        </div>
      ))}
      {open && <OrderSheet o={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function OrderSheet({ o, onClose }: { o: Order; onClose: () => void }) {
  const { busy, submit } = useSubmit();
  const [reason, setReason] = useState("");
  const dispute = () => submit(() => post(`/api/orders/${o.id}/dispute`, { reason }), "Nizo ochildi").then((r) => r && onClose());
  return (
    <Sheet onClose={onClose} title={o.public_id}>
      <div className="row"><span className="sp muted">Holat</span><St s={o.status} /></div>
      <div className="row"><span className="sp muted">Summa</span><b>{fmt(o.total_uzs)} so‘m</b></div>
      <div className="row"><span className="sp muted">To‘langan</span><b>{fmt(o.pay_amount)} {o.pay_currency.replace("_", " ")}</b></div>
      {o.delivery_note && <div className="glass" style={{ marginTop: 10 }}>📦 {o.delivery_note}</div>}
      {!["refunded", "cancelled", "disputed"].includes(o.status) && (
        <details style={{ marginTop: 14 }}>
          <summary className="muted">Nizo ochish</summary>
          <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Sababini yozing (kamida 5 belgi)" />
          <button className="btn danger block" style={{ marginTop: 8 }} disabled={busy || reason.trim().length < 5} onClick={dispute}>Nizo ochish</button>
        </details>
      )}
    </Sheet>
  );
}

function RentalsList() {
  const list = useAsync(() => get<Rental[]>("/api/rentals"), []);
  const [rate, setRate] = useState<Rental | null>(null);
  if (list.error) return <ErrorBox msg={list.error} retry={list.reload} />;
  if (list.loading) return <Skeletons n={2} grid={false} />;
  if (!list.data?.length) return <Empty icon="🕒" text="Ijaralar yo‘q" />;
  return (
    <div className="glass">
      {list.data.map((r) => (
        <div key={r.id} className="tx">
          <div className="ic">🕒</div>
          <div className="sp"><b>{r.item}</b><div className="muted">{fday(r.start_at)} – {fday(r.end_at)} · {r.days} kun</div></div>
          <div style={{ textAlign: "right" }}><St s={r.status} />
            {r.status === "returned" && !r.rating && <div><button className="btn sm" style={{ marginTop: 6 }} onClick={() => setRate(r)}>Baholash</button></div>}
          </div>
        </div>
      ))}
      {rate && <RateSheet r={rate} onClose={() => { setRate(null); list.reload(); }} />}
    </div>
  );
}
const fday = (s: string) => new Date(s).toLocaleDateString("uz-UZ", { timeZone: "Asia/Tashkent", day: "2-digit", month: "2-digit" });

function RateSheet({ r, onClose }: { r: Rental; onClose: () => void }) {
  const { busy, submit } = useSubmit();
  const [v, setV] = useState(5);
  return (
    <Sheet onClose={onClose} title="Ijarani baholang">
      <div className="row" style={{ justifyContent: "center", fontSize: 30 }}>{[1, 2, 3, 4, 5].map((n) => <span key={n} style={{ cursor: "pointer", opacity: n <= v ? 1 : 0.3 }} onClick={() => setV(n)}>⭐</span>)}</div>
      <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy} onClick={() => submit(() => post(`/api/rentals/${r.id}/rate`, { rating: v }), "Rahmat!").then((x) => x && onClose())}>Yuborish</button>
    </Sheet>
  );
}

function MarketOrders() {
  const list = useAsync(() => get<any[]>("/api/market/my/orders"), []);
  if (list.error) return <ErrorBox msg={list.error} retry={list.reload} />;
  if (list.loading) return <Skeletons n={2} grid={false} />;
  if (!list.data?.length) return <Empty icon="🛍" text="Market bitimlari yo‘q" />;
  return (
    <div className="glass">
      {list.data.map((m) => (
        <div key={m.id} className="tx" onClick={() => go(`market/order/${m.id}`)}>
          <div className="ic">{m.role === "buyer" ? "🛒" : "💰"}</div>
          <div className="sp"><b>{m.title}</b><div className="muted">{m.role === "buyer" ? "Xarid" : "Sotuv"} · x{m.qty}</div></div>
          <div style={{ textAlign: "right" }}><div className="amt">{fmt(m.amount)} {m.currency.replace("_", " ")}</div><St s={m.status} /></div>
        </div>
      ))}
    </div>
  );
}
