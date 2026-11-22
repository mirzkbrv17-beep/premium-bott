import { useState } from "react";
import { get, post, put, patch, del, fdate, fmt, useAsync, toast, fail, idem } from "../lib";
import { Empty, ErrorBox, Skeletons, St, Switch } from "../ui";

const SECTIONS: [string, string][] = [
  ["dash", "Dashboard"], ["pay", "To‘lovlar"], ["orders", "Buyurtma/Ijara"], ["catalog", "Katalog"], ["rates", "Kurslar"], ["users", "Foydalanuvchi"],
  ["market", "Market"], ["disputes", "Nizolar"], ["gifts", "Sovg‘a"], ["bonus", "Bonus/Promo"], ["support", "Support"], ["audit", "Audit"], ["roles", "Rollar"],
];

export default function Admin() {
  const [sec, setSec] = useState("dash");
  return (
    <div className="admin">
      <div className="top"><h1>Admin panel</h1></div>
      <div className="adm-nav">{SECTIONS.map(([k, l]) => <button key={k} className={`chip ${sec === k ? "on" : ""}`} onClick={() => setSec(k)}>{l}</button>)}</div>
      <div style={{ marginTop: 10 }}>
        {sec === "dash" && <Dash />}{sec === "pay" && <Pay />}{sec === "orders" && <Orders />}{sec === "catalog" && <Catalog />}
        {sec === "rates" && <Rates />}{sec === "users" && <Users />}{sec === "market" && <MarketMod />}{sec === "disputes" && <Disputes />}
        {sec === "gifts" && <Gifts />}{sec === "bonus" && <Bonus />}{sec === "support" && <Support />}{sec === "audit" && <AuditLog />}{sec === "roles" && <Roles />}
      </div>
    </div>
  );
}

const Table = ({ head, rows }: { head: string[]; rows: (string | number | JSX.Element)[][] }) => (
  <div className="glass scroll-x"><table><thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table></div>
);
const Act = ({ label, onClick, danger, gold }: { label: string; onClick: () => void; danger?: boolean; gold?: boolean }) => (
  <button className={`btn sm ${danger ? "danger" : gold ? "gold" : ""}`} style={{ marginRight: 4, marginTop: 2 }} onClick={onClick}>{label}</button>
);
const run = (p: Promise<any>, ok = "Bajarildi") => p.then(() => toast(ok, "ok")).catch(fail);

function Dash() {
  const [period, setPeriod] = useState("week");
  const d = useAsync(() => get<any>(`/api/admin/dashboard?period=${period}`), [period]);
  if (d.error) return <ErrorBox msg={d.error} retry={d.reload} />;
  if (d.loading) return <Skeletons n={4} />;
  const x = d.data;
  const cards: [string, any][] = [["Foydalanuvchilar", `${x.users.total} (+${x.users.new})`], ["Sotuv", `${x.sales.orders} · ${fmt(x.sales.uzs)} so‘m`], ["Ijara (faol)", x.rentals.active],
    ["Kutilayotgan qaytarish", x.rentals.pending_return], ["To‘lovlar (UZS)", fmt(x.payments.success_uzs)], ["Tekshiruvda chek", x.payments.awaiting_review],
    ["Ochiq nizo", x.open.disputes], ["Ochiq murojaat", x.open.tickets], ["Market e‘lon (kutish)", x.open.listings_pending], ["Sovg‘a (tekshiruv)", x.open.gifts_pending]];
  return (
    <>
      <div className="tabs" style={{ maxWidth: 300 }}>{["day", "week", "month"].map((p) => <button key={p} className={period === p ? "on" : ""} onClick={() => setPeriod(p)}>{p === "day" ? "Kun" : p === "week" ? "Hafta" : "Oy"}</button>)}</div>
      <div className="stat">{cards.map(([l, v]) => <div key={l} className="glass"><span className="muted">{l}</span><b>{v}</b></div>)}</div>
      <h2>Eng ko‘p sotilgan</h2><Table head={["Mahsulot", "Soni"]} rows={x.top_sold.map((r: any) => [r.title, r.n])} />
      <h2>Eng ko‘p ijaraga</h2><Table head={["Buyum", "Marta"]} rows={x.top_rented.map((r: any) => [r.title, r.n])} />
    </>
  );
}

function Pay() {
  const [st, setSt] = useState("awaiting_review");
  const l = useAsync(() => get<any[]>(`/api/admin/topups?status=${st}`), [st]);
  const review = (x: any, approve: boolean) => {
    const note = approve ? undefined : prompt("Rad etish sababi") || "";
    if (!approve && note === "") return;
    run(post(`/api/admin/topups/${x.internal_id}/review`, { approve, note }), approve ? "Tasdiqlandi" : "Rad etildi").then(l.reload);
  };
  const viewReceipt = async (x: any) => {
    const r = await fetch(`/api/admin/topups/${x.internal_id}/receipt`, { headers: { Authorization: `Bearer ${sessionStorage.getItem("abu_token")}` } });
    if (!r.ok) return fail(new Error("Chek topilmadi"));
    window.open(URL.createObjectURL(await r.blob()), "_blank");
  };
  return (
    <>
      <div className="chips">{["awaiting_review", "pending", "success", "failed", ""].map((s) => <div key={s} className={`chip ${st === s ? "on" : ""}`} onClick={() => setSt(s)}>{s || "Barchasi"}</div>)}</div>
      {l.error ? <ErrorBox msg={l.error} retry={l.reload} /> : l.loading ? <Skeletons n={2} grid={false} /> : !l.data?.length ? <Empty text="Yozuv yo‘q" /> : (
        <Table head={["ID", "Foydalanuvchi", "Valyuta", "UZS", "Provayder", "Holat", "Sana", ""]}
          rows={l.data.map((x) => [x.id, x.user, `${x.units} ${x.currency}`, fmt(x.uzs_amount), x.provider, <St s={x.status} />, fdate(x.created_at),
            <span key="a">{x.has_receipt && <Act label="Chek" onClick={() => viewReceipt(x)} />}{x.status === "awaiting_review" && <><Act label="Tasdiq" gold onClick={() => review(x, true)} /><Act label="Rad" danger onClick={() => review(x, false)} /></>}</span>])} />
      )}
    </>
  );
}

function Orders() {
  const [tab, setTab] = useState<"orders" | "rentals">("orders");
  const o = useAsync(() => get<any[]>("/api/admin/orders"), []);
  const r = useAsync(() => get<any[]>("/api/admin/rentals"), []);
  return (
    <>
      <div className="tabs"><button className={tab === "orders" ? "on" : ""} onClick={() => setTab("orders")}>Buyurtmalar</button><button className={tab === "rentals" ? "on" : ""} onClick={() => setTab("rentals")}>Ijaralar</button></div>
      {tab === "orders" && (o.loading ? <Skeletons n={2} grid={false} /> : o.error ? <ErrorBox msg={o.error} /> : (
        <Table head={["ID", "Foydalanuvchi", "Mahsulot", "Summa", "Holat", "Amal"]} rows={(o.data ?? []).map((x) => [x.public_id, x.user, x.items[0]?.title, `${fmt(x.pay_amount)} ${x.pay_currency}`, <St s={x.status} />,
          <span key="a">
            {x.status === "paid" && <Act label="Jarayonda" onClick={() => run(post(`/api/admin/orders/${x.id}/status`, { status: "processing" })).then(o.reload)} />}
            {["paid", "processing"].includes(x.status) && <Act label="Topshirildi" gold onClick={() => { const n = prompt("Yetkazish izohi (masalan: akkaunt login/parol, ssilka)"); if (n) run(post(`/api/admin/orders/${x.id}/status`, { status: "completed", note: n })).then(o.reload); }} />}
            {!["refunded", "cancelled", "completed"].includes(x.status) && <Act label="Qaytarish" danger onClick={() => { const n = prompt("Qaytarish sababi"); if (n) run(post(`/api/admin/orders/${x.id}/status`, { status: "cancelled", note: n }), "Qaytarildi").then(o.reload); }} />}
          </span>])} />
      ))}
      {tab === "rentals" && (r.loading ? <Skeletons n={2} grid={false} /> : (
        <Table head={["ID", "Foydalanuvchi", "Buyum", "Boshlanish", "Tugash", "Holat", "Amal"]} rows={(r.data ?? []).map((x) => [x.public_id, x.user, x.item, fdate(x.start_at), fdate(x.end_at), <St s={x.status} />,
          ["active", "expired", "disputed"].includes(x.status) ? <Act key="a" label="Qaytdi ✓" gold onClick={() => run(post(`/api/admin/rentals/${x.id}/returned`), "Qaytarish tasdiqlandi").then(r.reload)} /> : "—"])} />
      ))}
    </>
  );
}

function Catalog() {
  const [cat, setCat] = useState<any[]>([]);
  useAsync(() => get<any[]>("/api/admin/categories").then((c) => { setCat(c); return c; }), []);
  const prods = useAsync(() => get<any[]>("/api/admin/products"), []);
  const [edit, setEdit] = useState<any | null>(null);
  const [form, setForm] = useState<any>({ category_id: 1, title: "", price_uzs: 0, discount_percent: 0, sale_enabled: true, rent_enabled: false, stock: null, is_unique: false, color: "#2a2a35", active: true });
  const save = () => run(edit ? patch(`/api/admin/products/${edit.id}`, form) : post("/api/admin/products", form), "Saqlandi").then(() => { setEdit(null); prods.reload(); });
  const up = async (pid: number, f: File) => { const fd = new FormData(); fd.append("product_id", String(pid)); fd.append("file", f); try { const r = await fetch("/api/admin/media", { method: "POST", body: fd, headers: { Authorization: `Bearer ${sessionStorage.getItem("abu_token")}` } }); if (!r.ok) throw new Error((await r.json()).error?.message); toast("Media yuklandi", "ok"); } catch (e) { fail(e); } };
  return (
    <>
      <div className="glass">
        <h3>{edit ? "Mahsulotni tahrirlash" : "Yangi mahsulot"}</h3>
        <div className="grid2">
          <div><label>Kategoriya</label><select value={form.category_id} onChange={(e) => setForm({ ...form, category_id: Number(e.target.value) })}>{cat.map((c) => <option key={c.id} value={c.id}>{c.icon} {c.name.uz}</option>)}</select></div>
          <div><label>Nomi</label><input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
          <div><label>Narx (so‘m)</label><input type="number" value={form.price_uzs} onChange={(e) => setForm({ ...form, price_uzs: Number(e.target.value) })} /></div>
          <div><label>Chegirma %</label><input type="number" value={form.discount_percent} onChange={(e) => setForm({ ...form, discount_percent: Number(e.target.value) })} /></div>
          <div><label>Ombor (bo‘sh = cheksiz)</label><input type="number" value={form.stock ?? ""} onChange={(e) => setForm({ ...form, stock: e.target.value === "" ? null : Number(e.target.value) })} /></div>
          <div><label>Rang</label><input type="color" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} /></div>
        </div>
        <div className="row" style={{ marginTop: 10, flexWrap: "wrap", gap: 14 }}>
          <label style={{ margin: 0 }}>Sotuvda</label><Switch on={form.sale_enabled} set={(v) => setForm({ ...form, sale_enabled: v })} />
          <label style={{ margin: 0 }}>Ijara</label><Switch on={form.rent_enabled} set={(v) => setForm({ ...form, rent_enabled: v })} />
          <label style={{ margin: 0 }}>Noyob (NFT)</label><Switch on={form.is_unique} set={(v) => setForm({ ...form, is_unique: v })} />
        </div>
        {form.rent_enabled && <div className="grid2"><div><label>Kunlik narx</label><input type="number" value={form.rent_price_per_day ?? 0} onChange={(e) => setForm({ ...form, rent_price_per_day: Number(e.target.value) })} /></div><div><label>Min/Max kun</label><div className="row"><input type="number" value={form.rent_min_days ?? 1} onChange={(e) => setForm({ ...form, rent_min_days: Number(e.target.value) })} /><input type="number" value={form.rent_max_days ?? 30} onChange={(e) => setForm({ ...form, rent_max_days: Number(e.target.value) })} /></div></div></div>}
        <div className="row" style={{ marginTop: 12 }}><button className="btn gold" onClick={save}>Saqlash</button>{edit && <button className="btn" onClick={() => setEdit(null)}>Bekor</button>}</div>
      </div>
      <h2>Mahsulotlar</h2>
      {prods.loading ? <Skeletons n={2} grid={false} /> : <Table head={["ID", "Nomi", "Narx", "Ombor", "Holat", "Amal"]} rows={(prods.data ?? []).map((p) => [p.id, p.title, fmt(p.price_uzs), p.stock ?? "∞", p.active ? "faol" : "o‘chiq",
        <span key="a"><Act label="Tahrir" onClick={() => { setEdit(p); setForm(p); }} /><label className="btn sm" style={{ marginLeft: 4 }}>📎 Media<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden onChange={(e) => e.target.files?.[0] && up(p.id, e.target.files[0])} /></label><Act label="O‘chirish" danger onClick={() => confirm("O‘chirilsinmi?") && run(del(`/api/admin/products/${p.id}`)).then(prods.reload)} /></span>])} />}
      <h2>NFT / buyumlar</h2>
      <InventoryBox products={prods.data ?? []} />
    </>
  );
}

function InventoryBox({ products }: { products: any[] }) {
  const [pid, setPid] = useState<number | null>(null);
  const inv = useAsync(() => (pid ? get<any[]>(`/api/admin/inventory?product_id=${pid}`) : Promise.resolve([])), [pid]);
  const [f, setF] = useState({ item_ref: "", name: "", color: "#2a2a35", rent_price_per_day: 0, attrs: {} as any });
  const add = () => run(post("/api/admin/inventory", { product_id: pid, ...f }), "Buyum qo‘shildi").then(inv.reload);
  return (
    <div className="glass">
      <label>Mahsulot (noyob)</label>
      <select value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))}><option value="">—</option>{products.filter((p) => p.is_unique).map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}</select>
      {pid && <>
        <div className="grid2"><div><label>Ref (#1234)</label><input value={f.item_ref} onChange={(e) => setF({ ...f, item_ref: e.target.value })} /></div><div><label>Nomi</label><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div></div>
        <div className="grid2"><div><label>Ijara narxi/kun</label><input type="number" value={f.rent_price_per_day} onChange={(e) => setF({ ...f, rent_price_per_day: Number(e.target.value) })} /></div><div><label>Rang</label><input type="color" value={f.color} onChange={(e) => setF({ ...f, color: e.target.value })} /></div></div>
        <button className="btn gold" style={{ marginTop: 10 }} onClick={add}>+ Buyum qo‘shish</button>
        <div style={{ marginTop: 12 }}><Table head={["Ref", "Nomi", "Holat", "Ijara/kun"]} rows={(inv.data ?? []).map((i) => [i.item_ref, i.name, i.status, i.rent_price_per_day ?? "—"])} /></div>
      </>}
    </div>
  );
}

function Rates() {
  const s = useAsync(() => get<any>("/api/admin/settings"), []);
  const [v, setV] = useState<Record<string, any>>({});
  const save = (k: string, val: any) => run(put(`/api/admin/settings/${k}`, { value: val }), "Saqlandi").then(s.reload);
  if (s.loading) return <Skeletons n={2} grid={false} />;
  const d = s.data ?? {};
  const f = (k: string, label: string) => (
    <div className="row" style={{ marginBottom: 8 }}><span className="sp">{label}</span><input type="number" style={{ width: 130 }} value={v[k] ?? d[k] ?? ""} onChange={(e) => setV({ ...v, [k]: Number(e.target.value) })} /><button className="btn sm gold" onClick={() => save(k, v[k] ?? d[k])}>Saqlash</button></div>
  );
  return (
    <div className="glass">
      <h3>Kurslar (faqat rates.manage)</h3>
      {f("abu_f_uzs_per_unit", "1 ABU F = so‘m")}{f("abu_ton_uzs_per_unit", "1 ABU TON = so‘m")}{f("uzs_per_star", "1 Stars = so‘m")}
      <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>Kurs o‘zgarganda eski to‘lovlar eski kurs bilan qoladi (snapshot).</div>
      <h3 style={{ marginTop: 16 }}>To‘lov usullari</h3>
      <Table head={["Usul", "Holat"]} rows={(d.providers_list ?? []).map((p: any) => [p.name, p.enabled ? "yoqilgan" : "o‘chiq"])} />
      <h3 style={{ marginTop: 16 }}>Bonus sozlamalari</h3>
      {f("daily_question_xp", "Kun savoli XP")}{f("referral_reward_f", "Referal ABU F")}{f("referral_reward_ton", "Referal ABU TON")}{f("referral_wait_minutes", "Referal kutish (daq)")}{f("market_commission_percent", "Market komissiya %")}
    </div>
  );
}

function Users() {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<any | null>(null);
  const l = useAsync(() => get<any[]>(`/api/admin/users?q=${encodeURIComponent(q)}`), [q]);
  return (
    <>
      <input placeholder="ABU ID, username yoki Telegram ID" value={q} onChange={(e) => setQ(e.target.value)} />
      <div style={{ marginTop: 10 }}>{l.loading ? <Skeletons n={2} grid={false} /> : <Table head={["ABU ID", "Ism", "XP", "Holat", ""]} rows={(l.data ?? []).map((u) => [u.abu_id, u.name, u.xp, u.is_banned ? <St s="banned" /> : "faol", <Act key="a" label="Ochish" onClick={() => get(`/api/admin/users/${u.abu_id}`).then(setSel).catch(fail)} />])} />}</div>
      {sel && <UserCard u={sel} onChange={() => get(`/api/admin/users/${sel.abu_id}`).then(setSel)} />}
    </>
  );
}

function UserCard({ u, onChange }: { u: any; onChange: () => void }) {
  const [cur, setCur] = useState("ABU_F"), [amt, setAmt] = useState(0), [reason, setReason] = useState("");
  return (
    <div className="glass" style={{ marginTop: 12 }}>
      <h3>{u.name} · {u.abu_id}</h3>
      <div className="muted">Balans: F {fmt(u.balances.ABU_F.balance)} · TON {fmt(u.balances.ABU_TON.balance)} · XP {u.xp}</div>
      <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
        <Act label={u.is_banned ? "Cheklovni olish" : "Cheklash"} danger={!u.is_banned} onClick={() => { const r = u.is_banned ? "" : prompt("Sabab") || ""; if (!u.is_banned && !r) return; run(post(`/api/admin/users/${u.abu_id}/ban`, { banned: !u.is_banned, reason: r })).then(onChange); }} />
      </div>
      <h3 style={{ marginTop: 14 }}>Balansni tuzatish</h3>
      <div className="grid2"><div><label>Valyuta</label><select value={cur} onChange={(e) => setCur(e.target.value)}><option>ABU_F</option><option>ABU_TON</option></select></div><div><label>Miqdor (−/+)</label><input type="number" value={amt} onChange={(e) => setAmt(Number(e.target.value))} /></div></div>
      <label>Sabab (kamida 5 belgi, majburiy)</label><input value={reason} onChange={(e) => setReason(e.target.value)} />
      <button className="btn gold" style={{ marginTop: 10 }} disabled={!amt || reason.length < 5} onClick={() => run(post(`/api/admin/users/${u.abu_id}/adjust`, { currency: cur, amount: amt, reason, idempotency_key: idem() }), "Tuzatildi").then(onChange)}>Tuzatish</button>
      <h3 style={{ marginTop: 14 }}>Oxirgi yozuvlar (ledger)</h3>
      <Table head={["TX", "Tur", "Summa", "Sana"]} rows={u.ledger.map((e: any) => [e.tx_id, e.kind, `${e.amount} ${e.currency}`, fdate(e.created_at)])} />
    </div>
  );
}

function MarketMod() {
  const [st, setSt] = useState("pending");
  const l = useAsync(() => get<any[]>(`/api/admin/listings?status=${st}`), [st]);
  const sel = useAsync(() => get<any[]>("/api/admin/sellers?status=pending"), []);
  const mod = (x: any, s: string) => { const note = s === "active" ? "" : prompt("Izoh") || ""; run(post(`/api/admin/listings/${x.id}/moderate`, { status: s, note }), "Saqlandi").then(l.reload); };
  return (
    <>
      <div className="chips">{["pending", "active", "rejected", "hidden", ""].map((s) => <div key={s} className={`chip ${st === s ? "on" : ""}`} onClick={() => setSt(s)}>{s || "Barchasi"}</div>)}</div>
      {l.loading ? <Skeletons n={2} grid={false} /> : <Table head={["Sarlavha", "Narx", "Holat", "Amal"]} rows={(l.data ?? []).map((x) => [x.title, `${fmt(x.price_amount)} ${x.price_currency}`, <St s={x.status} />,
        <span key="a">{x.status !== "active" && <Act label="Tasdiq" gold onClick={() => mod(x, "active")} />}{x.status !== "rejected" && <Act label="Rad" danger onClick={() => mod(x, "rejected")} />}{x.status === "active" && <Act label="O‘chirish" danger onClick={() => mod(x, "removed")} />}</span>])} />}
      <h2>Sotuvchi tasdiqlari</h2>
      {(sel.data ?? []).length === 0 ? <div className="muted">Kutilayotgan yo‘q</div> : <Table head={["Foydalanuvchi", "Sotuv", "Amal"]} rows={sel.data!.map((s) => [s.name || s.abu_id, s.sales, <span key="a"><Act label="Tasdiq" gold onClick={() => run(post(`/api/admin/sellers/${s.user_id}`, { verified: true })).then(sel.reload)} /><Act label="Rad" danger onClick={() => run(post(`/api/admin/sellers/${s.user_id}`, { verified: false })).then(sel.reload)} /></span>])} />}
    </>
  );
}

function Disputes() {
  const l = useAsync(() => get<any[]>("/api/admin/disputes?status=open"), []);
  const res = (d: any, decision: string) => { const note = prompt("Izoh") || ""; run(post(`/api/admin/disputes/${d.id}/resolve`, { decision, note }), "Hal qilindi").then(l.reload); };
  if (l.loading) return <Skeletons n={2} grid={false} />;
  return (l.data ?? []).length === 0 ? <Empty icon="⚖️" text="Ochiq nizo yo‘q" /> : (
    <Table head={["ID", "Tur", "Sabab", "Summa", "Amal"]} rows={l.data!.map((d) => [d.id, d.ref_type, d.reason, d.amount ? `${fmt(d.amount)} ${d.currency}` : "—",
      <span key="a">{d.ref_type === "market_order" && <><Act label="Sotuvchiga" gold onClick={() => res(d, "release_to_seller")} /><Act label="Xaridorga" danger onClick={() => res(d, "refund_buyer")} /></>}{d.ref_type !== "market_order" && <Act label="Yopish" onClick={() => res(d, "resolved")} />}</span>])} />
  );
}

function Gifts() {
  const l = useAsync(() => get<any[]>("/api/admin/gifts?status=pending_review"), []);
  const rv = (g: any, approve: boolean) => run(post(`/api/admin/gifts/${g.id}/review`, { approve }), approve ? "Tasdiqlandi" : "Rad etildi").then(l.reload);
  return (l.data ?? []).length === 0 ? <Empty icon="🎁" text="Tekshiruvda sovg‘a yo‘q" /> : (
    <Table head={["ID", "Miqdor", "Valyuta", "Xabar", "Amal"]} rows={l.data!.map((g) => [g.public_id, fmt(g.amount), g.currency, g.message || "—", <span key="a"><Act label="Tasdiq" gold onClick={() => rv(g, true)} /><Act label="Rad" danger onClick={() => rv(g, false)} /></span>])} />
  );
}

function Bonus() {
  const promos = useAsync(() => get<any[]>("/api/admin/promo"), []);
  const [f, setF] = useState<any>({ code: "", mode: "limited_uses", currency: "ABU_F", amount: 10, max_uses: 100 });
  const create = () => run(post("/api/admin/promo", f), "Promo yaratildi").then(promos.reload);
  return (
    <>
      <div className="glass">
        <h3>Yangi promo</h3>
        <div className="grid2">
          <div><label>Kod</label><input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase() })} /></div>
          <div><label>Rejim</label><select value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}><option value="limited_uses">Limitli</option><option value="time_limited">Muddatli</option><option value="unlimited">Cheksiz</option></select></div>
          <div><label>Valyuta</label><select value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}><option>ABU_F</option><option>ABU_TON</option></select></div>
          <div><label>Miqdor</label><input type="number" value={f.amount} onChange={(e) => setF({ ...f, amount: Number(e.target.value) })} /></div>
          {f.mode === "limited_uses" && <div><label>Limit</label><input type="number" value={f.max_uses ?? ""} onChange={(e) => setF({ ...f, max_uses: Number(e.target.value) })} /></div>}
          {f.mode === "time_limited" && <div><label>Tugash (ISO)</label><input placeholder="2026-12-31T23:59:00Z" value={f.expires_at ?? ""} onChange={(e) => setF({ ...f, expires_at: e.target.value })} /></div>}
        </div>
        <button className="btn gold" style={{ marginTop: 10 }} onClick={create}>Yaratish</button>
      </div>
      <h2>Promo kodlar</h2>
      {promos.loading ? <Skeletons n={1} grid={false} /> : <Table head={["Kod", "Rejim", "Miqdor", "Ishlatilgan", "Holat"]} rows={(promos.data ?? []).map((p) => [p.code, p.mode, `${p.amount} ${p.currency}`, `${p.used_count}${p.max_uses ? "/" + p.max_uses : ""}`, p.active ? "faol" : "o‘chiq"])} />}
    </>
  );
}

function Support() {
  const l = useAsync(() => get<any[]>("/api/admin/tickets?status=open"), []);
  const [sel, setSel] = useState<any | null>(null);
  const [reply, setReply] = useState("");
  const open = (id: number) => get(`/api/admin/tickets/${id}`).then(setSel).catch(fail);
  const send = (close: boolean) => run(post(`/api/admin/tickets/${sel.id}/reply`, { body: reply, close }), "Yuborildi").then(() => { setReply(""); open(sel.id); l.reload(); });
  return (
    <>
      {l.loading ? <Skeletons n={2} grid={false} /> : (l.data ?? []).length === 0 ? <Empty text="Ochiq murojaat yo‘q" /> : <Table head={["ID", "Mavzu", "Foydalanuvchi", ""]} rows={l.data!.map((t) => [t.id, t.subject, t.user, <Act key="a" label="Ochish" onClick={() => open(t.id)} />])} />}
      {sel && <div className="glass" style={{ marginTop: 12 }}>
        <h3>{sel.subject}</h3>
        {sel.messages.map((m: any, i: number) => <div key={i} className="glass" style={{ marginTop: 6, background: m.staff ? "rgba(232,197,101,.08)" : undefined }}><div className="muted" style={{ fontSize: 11 }}>{m.staff ? "Support" : "Foydalanuvchi"} · {fdate(m.created_at)}</div>{m.body}</div>)}
        <textarea rows={3} style={{ marginTop: 10 }} value={reply} onChange={(e) => setReply(e.target.value)} />
        <div className="row" style={{ marginTop: 8 }}><button className="btn gold" disabled={!reply} onClick={() => send(false)}>Javob</button><button className="btn" disabled={!reply} onClick={() => send(true)}>Javob + yopish</button></div>
      </div>}
    </>
  );
}

function AuditLog() {
  const [a, setA] = useState("");
  const l = useAsync(() => get<any[]>(`/api/admin/audit${a ? `?action=${encodeURIComponent(a)}` : ""}`), [a]);
  return (
    <>
      <input placeholder="Amal bo‘yicha filtr (masalan: topup)" value={a} onChange={(e) => setA(e.target.value)} />
      <div style={{ marginTop: 10 }}>{l.loading ? <Skeletons n={2} grid={false} /> : <Table head={["Vaqt", "Admin", "Amal", "Obyekt", "Tafsilot"]} rows={(l.data ?? []).map((x) => [fdate(x.created_at), x.admin_user_id, x.action, `${x.entity_type ?? ""} ${x.entity_id ?? ""}`, <code key="d" style={{ fontSize: 11 }}>{JSON.stringify(x.detail)}</code>])} />}</div>
    </>
  );
}

function Roles() {
  const r = useAsync(() => get<any>("/api/admin/roles"), []);
  const [abu, setAbu] = useState(""), [role, setRole] = useState("moderator");
  const set = (r_: string | null) => run(post("/api/admin/admins", { abu_id: abu, role: r_ }), "Saqlandi").then(() => { setAbu(""); r.reload(); });
  if (r.loading) return <Skeletons n={1} grid={false} />;
  return (
    <>
      <div className="glass">
        <h3>Admin tayinlash</h3>
        <div className="grid2"><div><label>ABU ID</label><input value={abu} onChange={(e) => setAbu(e.target.value.toUpperCase())} /></div>
          <div><label>Rol</label><select value={role} onChange={(e) => setRole(e.target.value)}>{["admin", "moderator", "support", "finance-view"].map((x) => <option key={x}>{x}</option>)}</select></div></div>
        <div className="row" style={{ marginTop: 10 }}><button className="btn gold" onClick={() => set(role)}>Tayinlash</button><button className="btn danger" onClick={() => set(null)}>Olib tashlash</button></div>
      </div>
      <h2>Adminlar</h2>
      <Table head={["ABU ID", "Ism", "Rol", "Holat"]} rows={(r.data?.admins ?? []).map((a: any) => [a.abu_id, a.name, a.role, a.active ? "faol" : "o‘chiq"])} />
    </>
  );
}
