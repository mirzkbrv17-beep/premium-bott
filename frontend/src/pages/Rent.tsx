import { useMemo, useState } from "react";
import { get, post, go, fmt, t, useAsync } from "../lib";
import type { Item } from "../api";
import { Empty, ErrorBox, Skeletons, Sheet, flyCoins } from "../ui";
import { useSubmit, PayChooser } from "./Shared";
import { ItemCard } from "./Nft";

const dstr = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export default function Rent() {
  const [q, setQ] = useState("");
  const list = useAsync(() => get<Item[]>(`/api/rent/items?${new URLSearchParams(q ? { q } : {})}`), [q]);
  const [open, setOpen] = useState<Item | null>(null);
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} aria-label="Ijara qidirish" />
      </div>
      {list.error ? <ErrorBox msg={list.error} retry={list.reload} /> : list.loading ? <Skeletons /> : !list.data?.length ? <Empty icon="🕒" text="Ijaraga buyum yo‘q" /> : (
        <div className="grid2">{list.data.map((i) => <ItemCard key={i.id} i={i} rent onOpen={() => setOpen(i)} />)}</div>
      )}
      {open && <RentSheet i={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function RentSheet({ i, onClose }: { i: Item; onClose: () => void }) {
  const min = i.min_days ?? 1, max = i.max_days ?? 30;
  const [start, setStart] = useState(dstr(new Date(Date.now() + 86400000)));
  const [days, setDays] = useState(min);
  const [cur, setCur] = useState("ABU_F");
  const [cal, setCal] = useState<{ start: string; end: string; type: string }[]>([]);
  const [month, setMonth] = useState(new Date());
  const { busy, submit } = useSubmit();
  useAsync(() => get<{ busy: any[] }>(`/api/rent/items/${i.id}/calendar`).then((r) => { setCal(r.busy); return r; }), [i.id]);

  const isBusy = (d: Date) => cal.some((b) => new Date(b.start) <= new Date(d.getTime() + 86399999) && new Date(b.end) > d);
  const days_ = useMemo(() => {
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const offset = (first.getDay() + 6) % 7;
    return Array.from({ length: 42 }, (_, k) => new Date(first.getFullYear(), first.getMonth(), k - offset + 1));
  }, [month]);
  const today0 = new Date(); today0.setHours(0, 0, 0, 0);
  const total = days * (i.rent_price_per_day ?? 0);
  const rentIt = async (e: any) => {
    const r = await submit((key) => post("/api/rent", { inventory_item_id: i.id, start_date: start, days, pay_currency: cur, idempotency_key: key }), "Ijara rasmiylashtirildi ✅");
    if (r) { flyCoins(cur, e?.currentTarget); onClose(); go("orders"); }
  };
  return (
    <Sheet onClose={onClose} title={`${i.title} ${i.ref}`}>
      <div className="muted">{fmt(i.rent_price_per_day!)} so‘m / kun · {min}–{max} kun</div>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn sm" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>‹</button>
        <b className="sp center">{month.toLocaleDateString("uz-UZ", { month: "long", year: "numeric" })}</b>
        <button className="btn sm" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>›</button>
      </div>
      <div className="cal">{["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"].map((d) => <b key={d}>{d}</b>)}
        {days_.map((d, k) => {
          const past = d < today0, busyDay = isBusy(d), inMonth = d.getMonth() === month.getMonth();
          const sel = dstr(d) === start;
          return <div key={k} className={`${busyDay ? "busy" : ""} ${past ? "past" : ""} ${sel ? "sel" : ""}`} style={{ opacity: inMonth ? 1 : 0.35 }}
            onClick={() => { if (!past && !busyDay) setStart(dstr(d)); }} aria-label={dstr(d)}>{d.getDate()}</div>;
        })}
      </div>
      <label>Muddat (kun)</label>
      <div className="row"><button className="btn sm" onClick={() => setDays(Math.max(min, days - 1))}>−</button><b className="sp center">{days} kun</b><button className="btn sm" onClick={() => setDays(Math.min(max, days + 1))}>+</button></div>
      <label>To‘lov valyutasi</label>
      <PayChooser value={cur} set={setCur} />
      <div className="glass" style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}><span>Jami</span><b>{fmt(total)} so‘m</b></div>
      <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy} onClick={rentIt}>{busy ? "..." : t("rent_btn")}</button>
    </Sheet>
  );
}
