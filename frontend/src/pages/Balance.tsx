import { useState } from "react";
import { get, post, fdate, fmt, useAsync, t, CUR, toast, fail, go } from "../lib";
import type { Options, Topup, Tx } from "../api";
import { AnimNumber, Coin, Empty, ErrorBox, Sheet, Skeletons, St } from "../ui";
import { Tabs, useSubmit } from "./Shared";
import { useMe } from "../App";
const tgw = (): any => (window as any).Telegram?.WebApp;

export default function Balance({ sub }: { sub?: string }) {
  const { me, refresh } = useMe();
  const [tab, setTab] = useState<"all" | "topups">(sub === "topups" ? "topups" : "all");
  const [sheet, setSheet] = useState<"topup" | null>(null);
  const hide = !!me?.settings?.hide_balance;
  if (!me) return <Skeletons n={1} grid={false} />;
  const f = me.balances.ABU_F, ton = me.balances.ABU_TON;
  return (
    <>
      <div className="top"><h1>{t("balance")}</h1></div>
      <div className="bal" id="bal-target" onClick={() => {}}>
        <div className="lbl">{t("my_balance")}</div>
        <div className="big"><AnimNumber value={f.balance} hidden={hide} /> <small style={{ fontSize: 16, color: "var(--gold)" }}>ABU F</small></div>
        <div className="muted">Jami to‘ldirilgan: {hide ? "••••" : fmt(f.topped_up)} · Sarflangan: {hide ? "••••" : fmt(f.spent)}</div>
      </div>
      <div className="grid2" style={{ marginTop: 12 }}>
        <div className="cur"><Coin cur="ABU_TON" size={40} /><div><div className="muted">ABU TON</div><b><AnimNumber value={ton.balance} hidden={hide} /></b></div></div>
        <div className="cur"><Coin cur="ABU_F" size={40} /><div><div className="muted">ABU F</div><b><AnimNumber value={f.balance} hidden={hide} /></b></div></div>
      </div>
      <div className="tiles" style={{ marginTop: 14 }}>
        <div className="tile" onClick={() => setSheet("topup")}><span className="e">➕</span>{t("topup")}</div>
        <div className="tile" onClick={() => go("cabinet/gift")}><span className="e">🎁</span>Sovg‘a</div>
        <div className="tile" onClick={() => go("cabinet/promo")}><span className="e">🏷</span>Promo</div>
      </div>
      <h2>{t("recent")}</h2>
      <Tabs value={tab} set={setTab} items={[["all", "Barchasi"], ["topups", "To‘ldirishlar"]]} />
      {tab === "all" ? <TxList /> : <TopupList />}
      {sheet === "topup" && <TopupSheet onClose={() => { setSheet(null); refresh(); }} />}
    </>
  );
}

const FILTERS: [string, string][] = [["", "Barchasi"], ["topup", "To‘ldirish"], ["spend", "Xarid"], ["bonus", "Bonus"], ["gift", "Sovg‘a"], ["refund", "Qaytarish"], ["market", "Market"]];

function TxList() {
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<Tx[]>([]);
  const [open, setOpen] = useState<Tx | null>(null);
  const q = useAsync(() => get<{ items: Tx[]; has_more: boolean }>(`/api/me/transactions?${new URLSearchParams({ ...(type ? { type } : {}), page: String(page) })}`).then((r) => { setItems(page === 1 ? r.items : [...items, ...r.items]); return r; }), [type, page]);
  return (
    <>
      <div className="chips">{FILTERS.map(([k, l]) => <div key={k} className={`chip ${type === k ? "on" : ""}`} onClick={() => { setType(k); setPage(1); }}>{l}</div>)}</div>
      {q.error ? <ErrorBox msg={q.error} retry={q.reload} /> : !items.length && q.loading ? <Skeletons n={3} grid={false} /> : !items.length ? <Empty icon="🧾" text="Operatsiyalar yo‘q" /> : (
        <div className="glass">
          {items.map((x) => (
            <div key={x.tx_id} className="tx" onClick={() => setOpen(x)} role="button">
              <div className="ic">{x.amount > 0 ? "⬇️" : "⬆️"}</div>
              <div className="sp"><b>{x.title}</b><div className="muted">{fdate(x.ts)} · {x.tx_id}</div></div>
              <div style={{ textAlign: "right" }}><div className={`amt ${x.amount >= 0 ? "pos" : "neg"}`}>{x.amount > 0 ? "+" : ""}{fmt(x.amount)} {CUR[x.currency]}</div><St s={x.status} /></div>
            </div>
          ))}
          {q.data?.has_more && <button className="btn block" style={{ marginTop: 10 }} onClick={() => setPage(page + 1)}>Ko‘proq</button>}
        </div>
      )}
      {open && <TxSheet tx={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function TxSheet({ tx, onClose }: { tx: Tx; onClose: () => void }) {
  const [d, setD] = useState<any>(null);
  useAsync(() => get(`/api/me/transactions/${encodeURIComponent(tx.tx_id)}`).then(setD), [tx.tx_id]);
  return (
    <Sheet onClose={onClose} title={tx.title}>
      <div className="row"><span className="sp muted">Summa</span><b>{tx.amount > 0 ? "+" : ""}{fmt(tx.amount)} {CUR[tx.currency]}</b></div>
      <div className="row"><span className="sp muted">Holat</span><St s={tx.status} /></div>
      <div className="row"><span className="sp muted">Usul</span><span>{tx.method}</span></div>
      <div className="row"><span className="sp muted">Sana</span><span>{fdate(tx.ts)}</span></div>
      {tx.uzs_amount && <div className="row"><span className="sp muted">To‘lov (UZS)</span><span>{fmt(tx.uzs_amount)} so‘m</span></div>}
      <div className="row"><span className="sp muted">ID</span><code>{tx.tx_id}</code></div>
      {d?.note && <div className="muted" style={{ marginTop: 8 }}>{d.note}</div>}
      {d?.receipt && <div className="glass" style={{ marginTop: 12, fontSize: 13 }}>🧾 Chek raqami: <b>{d.receipt.number}</b> · {d.receipt.valid ? "✅ haqiqiy" : "⏳ kutilmoqda"}</div>}
    </Sheet>
  );
}

function TopupList() {
  const list = useAsync(() => get<Topup[]>("/api/topups"), []);
  const attach = async (id: string, file: File) => {
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await fetch(`/api/topup/${id}/receipt`, { method: "POST", body: fd, headers: { Authorization: `Bearer ${sessionStorage.getItem("abu_token")}` } });
      if (!r.ok) throw new Error((await r.json()).error?.message || "Yuklash xatosi");
      toast("Chek yuborildi. Admin tekshiradi.", "ok"); list.reload();
    } catch (e) { fail(e); }
  };
  if (list.error) return <ErrorBox msg={list.error} retry={list.reload} />;
  if (list.loading) return <Skeletons n={2} grid={false} />;
  if (!list.data?.length) return <Empty icon="💳" text="To‘ldirishlar yo‘q" />;
  return (
    <div className="glass">
      {list.data.map((x) => (
        <div key={x.id} className="tx" style={{ flexWrap: "wrap" }}>
          <div className="ic">💳</div>
          <div className="sp"><b>{x.currency.replace("_", " ")} · {fmt(x.units)}</b><div className="muted">{fdate(x.created_at)} · {x.provider}</div></div>
          <div style={{ textAlign: "right" }}><St s={x.status} /><div className="muted">{fmt(x.uzs_amount)} so‘m</div></div>
          {x.provider === "manual_card" && ["pending", "awaiting_review"].includes(x.status) && (
            <label className="btn sm" style={{ width: "100%", textAlign: "center", marginTop: 8 }}>
              📎 Chek yuklash
              <input type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => e.target.files?.[0] && attach(x.id, e.target.files[0])} />
            </label>
          )}
          {x.review_note && <div className="muted" style={{ width: "100%" }}>Izoh: {x.review_note}</div>}
        </div>
      ))}
    </div>
  );
}

function TopupSheet({ onClose }: { onClose: () => void }) {
  const opts = useAsync(() => get<Options>("/api/topup/options"), []);
  const [cur, setCur] = useState<"ABU_F" | "ABU_TON">("ABU_F");
  const [units, setUnits] = useState(100);
  const [pkg, setPkg] = useState<number | null>(null);
  const [provider, setProvider] = useState("");
  const [info, setInfo] = useState<any>(null);
  const { busy, submit } = useSubmit();
  const o = opts.data;
  const provs = (o?.providers ?? []).filter((p) => p.status === "ready");
  const cost = cur === "ABU_F" ? units * (o?.abu_f.uzs_per_unit ?? 10) : (o?.abu_ton_packages.find((p) => p.id === pkg)?.price_uzs ?? 0);
  const create = async () => {
    const body = cur === "ABU_F" ? { currency: cur, provider, units } : { currency: cur, provider, package_id: pkg };
    const r = await submit((key) => post("/api/topup", { ...body, idempotency_key: key }), "To‘lov yaratildi");
    if (r) {
      const pay = r.pay;
      if (pay.type === "invoice" || pay.type === "url") { (tgw() ? tgw().openLink(pay.url) : window.open(pay.url, "_blank")); }
      if (pay.type === "manual") { setInfo(pay); return; }
      onClose();
    }
  };
  const copy = (v: string) => { navigator.clipboard?.writeText(v); toast("Nusxalandi", "ok"); };
  if (info) return (
    <Sheet onClose={() => { setInfo(null); onClose(); }} title="To‘lov ma‘lumoti">
      <div className="glass">
        <div className="muted">Karta raqami</div>
        <div className="row" style={{ marginTop: 4 }}>
          <b className="sp" style={{ fontSize: 18, letterSpacing: 1 }}>{info.card_number}</b>
          <button className="btn sm gold" onClick={() => copy(info.card_number.replace(/\s/g, ""))}>📋 Nusxa</button>
        </div>
        <div className="muted" style={{ marginTop: 6 }}>Egasi: {info.card_holder}</div>
        <div className="row" style={{ marginTop: 10 }}><span className="sp muted">Summa</span><b>{fmt(info.amount_uzs)} so‘m</b></div>
        <div className="row" style={{ marginTop: 6 }}><span className="sp muted">Izoh</span><code>{info.comment}</code><button className="btn sm" onClick={() => copy(info.comment)}>📋</button></div>
      </div>
      <div className="muted" style={{ marginTop: 10 }}>To‘lovdan so‘ng chekning skrinshotini shu botga yuboring. Admin tasdiqlagach balans qo‘shiladi.</div>
      <button className="btn gold block" style={{ marginTop: 12 }} onClick={() => { setInfo(null); onClose(); }}>Tushunarli</button>
    </Sheet>
  );
  return (
    <Sheet onClose={onClose} title="Balansni to‘ldirish">
      {opts.loading ? <Skeletons n={1} grid={false} /> : (
        <>
          <div className="tabs"><button className={cur === "ABU_F" ? "on" : ""} onClick={() => setCur("ABU_F")}>🪙 ABU F</button><button className={cur === "ABU_TON" ? "on" : ""} onClick={() => setCur("ABU_TON")}>💠 ABU TON</button></div>
          {cur === "ABU_F" ? (
            <>
              <label>Miqdor (min {o?.abu_f.min_units}) · 1 ABU F = {o?.abu_f.uzs_per_unit} so‘m</label>
              <input type="number" value={units} min={o?.abu_f.min_units} onChange={(e) => setUnits(Number(e.target.value))} />
            </>
          ) : (
            <div className="grid2" style={{ marginTop: 8 }}>{o?.abu_ton_packages.map((p) => (
              <div key={p.id} className={`chip ${pkg === p.id ? "on" : ""}`} style={{ textAlign: "center", padding: 12 }} onClick={() => setPkg(p.id)}>💠 {p.units}<br /><span style={{ fontSize: 11 }}>{fmt(p.price_uzs)} so‘m</span></div>
            ))}</div>
          )}
          <label>To‘lov usuli</label>
          <div className="chips">{provs.map((p) => <div key={p.code} className={`chip ${provider === p.code ? "on" : ""}`} onClick={() => setProvider(p.code)}>{p.name}</div>)}</div>
          {!provs.length && <div className="muted">Hozircha faol to‘lov usuli yo‘q (admin sozlashi kerak).</div>}
          <div className="glass" style={{ marginTop: 12, display: "flex", justifyContent: "space-between" }}><span>To‘lov</span><b>{fmt(cost)} so‘m</b></div>
          <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy || !provider || (cur === "ABU_TON" && !pkg)} onClick={create}>{busy ? "..." : "Davom etish"}</button>
        </>
      )}
    </Sheet>
  );
}
