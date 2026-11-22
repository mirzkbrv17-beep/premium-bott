import { useState } from "react";
import { applyAnimSettings, get, post, patch, fdate, fmt, t, useAsync, toast, go, setLang } from "../lib";
import type { Listing } from "../api";
import { Empty, ErrorBox, Sheet, Skeletons, St, Switch, flyCoins } from "../ui";
import { Tabs, useSubmit } from "./Shared";
import { useMe } from "../App";

export default function Cabinet({ sub }: { sub?: string }) {
  const { me } = useMe();
  if (!me) return <Skeletons n={2} grid={false} />;
  if (sub === "promo") return <Promo />;
  if (sub === "gift") return <Gift />;
  if (sub === "market") return <Market />;
  if (sub === "friends") return <Friends />;
  if (sub === "tasks") return <Tasks />;
  if (sub === "achievements") return <Achievements />;
  if (sub === "referral") return <Referral />;
  if (sub === "support") return <Support />;
  if (sub === "settings") return <Settings />;
  if (sub === "vip") return <Vip />;
  return <Home />;
}

function Home() {
  const { me } = useMe();
  const d = useAsync(() => get("/api/bonus/daily"), []);
  const lv = me!.level;
  const pct = Math.round((lv.xp_in_level / lv.xp_for_next) * 100);
  const items: [string, string, string][] = [
    ["🛍", "Market", "market"], ["👥", "Do‘stlar", "friends"], ["⚔️", "Duel", "friends"], ["🎯", "Vazifalar", "tasks"], ["🏆", "Yutuqlar", "achievements"],
    ["🤝", "Referal", "referral"], ["🏷", "Promo", "promo"], ["🎁", "Sovg‘a", "gift"], ["💎", "VIP", "vip"], ["⚙️", "Sozlamalar", "settings"], ["💬", "Yordam", "support"],
  ];
  return (
    <>
      <div className="top"><h1>Kabinet</h1></div>
      <div className="glass" style={{ display: "flex", gap: 14, alignItems: "center" }}>
        <div className="avatar" style={{ width: 60, height: 60, fontSize: 22 }}>{me!.photo_url ? <img src={me!.photo_url} alt="" /> : me!.first_name[0]}</div>
        <div className="sp"><b style={{ fontSize: 17 }}>{me!.first_name}</b><div className="muted">ID: {me!.abu_id}</div>
          {me!.vip && <div className="muted">{me!.vip.badge} {me!.vip.name} · −{me!.vip.discount_percent}%</div>}</div>
      </div>
      <div className="glass" style={{ marginTop: 12 }}>
        <div className="row"><b>Daraja {lv.level}</b><span className="sp" /><span className="muted">{lv.xp_in_level}/{lv.xp_for_next} XP</span></div>
        <div className="prog" style={{ marginTop: 8 }}><i style={{ width: pct + "%" }} /></div>
      </div>
      <div className="glass" style={{ marginTop: 12 }}>
        <div className="row"><div className="sp"><h3>🎁 Kunlik bonus</h3><div className="muted">Streak: {d.data?.streak ?? 0} · Keyingi: {d.data?.next_amount ?? "—"} ABU F</div></div>
          <DailyBtn claimed={!!d.data?.claimed_today} onDone={d.reload} /></div>
      </div>
      <div className="tiles" style={{ marginTop: 14 }}>
        {items.map(([e, l, k]) => <div key={l} className="tile" onClick={() => go("cabinet/" + k)}><span className="e">{e}</span>{l}</div>)}
      </div>
    </>
  );
}

function DailyBtn({ claimed, onDone }: { claimed: boolean; onDone: () => void }) {
  const { submit, busy } = useSubmit();
  return <button className="btn gold" disabled={claimed || busy} onClick={(e) => submit(() => post("/api/bonus/daily/claim"), "Bonus olindi 🎉").then((r) => { if (r) { flyCoins("ABU_F", e.currentTarget); onDone(); } })}>{claimed ? "Olingan ✓" : "Olish"}</button>;
}

function Back({ title }: { title: string }) {
  return <div className="top"><button className="btn sm" onClick={() => go("cabinet")}>←</button><h1>{title}</h1></div>;
}

function Promo() {
  const [code, setCode] = useState("");
  const { busy, submit } = useSubmit();
  return (
    <>
      <Back title="Promo kod" />
      <div className="glass">
        <label>Promo kodni kiriting</label>
        <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="MASALAN: ABU2026" />
        <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy || code.length < 2} onClick={() => submit((k) => post("/api/promo/redeem", { code }), "Promo qo‘llandi 🎁").then((r) => r && setCode(""))}>Qo‘llash</button>
      </div>
    </>
  );
}

function Gift() {
  const [to, setTo] = useState(""), [cur, setCur] = useState("ABU_F"), [amount, setAmount] = useState(10), [msg, setMsg] = useState("");
  const { busy, submit } = useSubmit();
  const hist = useAsync(() => get<any[]>("/api/gifts"), []);
  return (
    <>
      <Back title="Sovg‘a yuborish" />
      <div className="glass">
        <label>Qabul qiluvchi ABU ID</label><input value={to} onChange={(e) => setTo(e.target.value.toUpperCase())} placeholder="ABU-XXXXXXXX" />
        <label>Valyuta</label>
        <div className="chips"><div className={`chip ${cur === "ABU_F" ? "on" : ""}`} onClick={() => setCur("ABU_F")}>🪙 ABU F</div><div className={`chip ${cur === "ABU_TON" ? "on" : ""}`} onClick={() => setCur("ABU_TON")}>💠 ABU TON</div></div>
        <label>Miqdor</label><input type="number" min={1} value={amount} onChange={(e) => setAmount(Number(e.target.value))} />
        <label>Xabar (ixtiyoriy)</label><input value={msg} onChange={(e) => setMsg(e.target.value)} maxLength={200} />
        <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy || !to} onClick={() => submit((k) => post("/api/gifts", { to_abu_id: to, currency: cur, amount, message: msg, idempotency_key: k }), "Sovg‘a yuborildi").then((r) => r && (setTo(""), hist.reload()))}>Yuborish</button>
      </div>
      <h2>Tarix</h2>
      <div className="glass">{(hist.data ?? []).length === 0 ? <div className="muted">Hozircha yo‘q</div> : hist.data!.map((g) => (
        <div key={g.id} className="tx"><div className="ic">{g.direction === "out" ? "⬆️" : "⬇️"}</div><div className="sp"><b>{g.other}</b><div className="muted">{g.message}</div></div><div style={{ textAlign: "right" }}><b>{g.direction === "out" ? "−" : "+"}{fmt(g.amount)} {g.currency.replace("_", " ")}</b><St s={g.status} /></div></div>
      ))}</div>
    </>
  );
}

function Referral() {
  const r = useAsync(() => get<any>("/api/referral"), []);
  const copy = async () => { await navigator.clipboard?.writeText(r.data.link); toast("Havola nusxalandi", "ok"); };
  const share = () => { const u = `https://t.me/share/url?url=${encodeURIComponent(r.data.link)}&text=${encodeURIComponent("ABU BOT - do‘kon, ijara, market!")}`; tg_open(u); };
  if (r.error) return <ErrorBox msg={r.error} retry={r.reload} />;
  if (r.loading) return <Skeletons n={1} grid={false} />;
  const d = r.data;
  return (
    <>
      <Back title="Referal" />
      <div className="glass center">
        <div className="muted">Har bir qo‘shilgan do‘st uchun</div>
        <div style={{ fontSize: 24, fontWeight: 800, margin: "6px 0" }}>+{d.reward_f} ABU F · +{d.reward_ton} ABU TON</div>
        <div className="muted">Mukofot {d.wait_minutes} daqiqadan keyin, do‘st majburiy obunani bajargach beriladi.</div>
        <div className="row" style={{ marginTop: 12 }}><button className="btn sp" onClick={copy}>📋 Nusxalash</button><button className="btn gold sp" onClick={share}>📤 Ulashish</button></div>
      </div>
      <div className="grid2" style={{ marginTop: 12 }}>
        <div className="glass center"><b style={{ fontSize: 20 }}>{d.counts.total}</b><div className="muted">Taklif</div></div>
        <div className="glass center"><b style={{ fontSize: 20 }}>{d.counts.rewarded}</b><div className="muted">Mukofotlangan</div></div>
      </div>
      <h2>Do‘stlar</h2>
      <div className="glass">{d.items.length === 0 ? <div className="muted">Hali hech kim yo‘q</div> : d.items.map((x: any, i: number) => (
        <div key={i} className="tx"><div className="sp"><b>{x.name}</b><div className="muted">{fdate(x.created_at)}</div></div><St s={x.status} /></div>
      ))}</div>
    </>
  );
}
function tg_open(u: string) { const w = (window as any).Telegram?.WebApp; w?.openTelegramLink ? w.openTelegramLink(u) : window.open(u, "_blank"); }

function Friends() {
  const [abu, setAbu] = useState("");
  const { busy, submit } = useSubmit();
  const f = useAsync(() => get<any[]>("/api/friends"), []);
  const d = useAsync(() => get<any[]>("/api/duels"), []);
  return (
    <>
      <Back title="Do‘stlar va Duel" />
      <div className="glass">
        <label>Do‘st ABU ID</label>
        <div className="row"><input value={abu} onChange={(e) => setAbu(e.target.value.toUpperCase())} placeholder="ABU-XXXXXXXX" /><button className="btn" disabled={busy || !abu} onClick={() => submit(() => post("/api/friends/request", { abu_id: abu }), "So‘rov yuborildi").then((r) => r && (setAbu(""), f.reload()))}>+ Qo‘shish</button></div>
      </div>
      <h2>Do‘stlar</h2>
      <div className="glass">{(f.data ?? []).length === 0 ? <div className="muted">Hali yo‘q</div> : f.data!.map((x) => (
        <div key={x.id} className="tx"><div className="ic">👤</div><div className="sp"><b>{x.name}</b><div className="muted">{x.abu_id}</div></div>
          {x.incoming ? <button className="btn sm gold" onClick={() => submit(() => post(`/api/friends/${x.id}/accept`)).then(() => f.reload())}>Qabul</button> : <St s={x.status} />}</div>
      ))}</div>
      <h2>Duellar <span className="muted" style={{ fontSize: 12 }}>(pul tikishsiz)</span></h2>
      <div className="glass">{(d.data ?? []).length === 0 ? <div className="muted">Duel yo‘q</div> : d.data!.map((x) => (
        <DuelRow key={x.id} x={x} onDone={d.reload} />
      ))}</div>
    </>
  );
}

function DuelRow({ x, onDone }: { x: any; onDone: () => void }) {
  const { submit } = useSubmit();
  const [ans, setAns] = useState<number[]>([]);
  return (
    <div className="tx" style={{ flexDirection: "column", alignItems: "stretch" }}>
      <div className="row"><div className="ic">⚔️</div><div className="sp"><b>{x.opponent}</b><div className="muted">{x.status}</div></div>
        {x.incoming && <button className="btn sm gold" onClick={() => submit(() => post(`/api/duels/${x.id}/accept`, { accept: true })).then(onDone)}>Qabul</button>}
        {x.status === "finished" && <b>{x.winner_me === true ? "🏆 G‘alaba" : x.winner_me === false ? "😔 Mag‘lubiyat" : "🤝 Durrang"}</b>}</div>
      {x.status === "active" && !x.answered && x.questions.map((q: any, qi: number) => (
        <div key={qi} style={{ marginTop: 8 }}><div>{q.text}</div><div className="chips">{q.options.map((o: string, oi: number) => <div key={oi} className={`chip ${ans[qi] === oi ? "on" : ""}`} onClick={() => setAns(Object.assign([...ans], { [qi]: oi }))}>{o}</div>)}</div></div>
      ))}
      {x.status === "active" && !x.answered && <button className="btn gold sm" style={{ marginTop: 8 }} disabled={ans.length < x.questions.length} onClick={() => submit(() => post(`/api/duels/${x.id}/answer`, { answers: ans })).then(onDone)}>Yuborish</button>}
    </div>
  );
}

function Tasks() {
  const t_ = useAsync(() => get<any[]>("/api/tasks"), []);
  const { submit } = useSubmit();
  return (
    <>
      <Back title="Vazifalar" />
      {t_.loading ? <Skeletons n={3} grid={false} /> : (t_.data ?? []).map((x) => (
        <div key={x.id} className="glass" style={{ marginBottom: 10 }}>
          <div className="row"><div className="sp"><h3>{x.title}</h3><div className="muted">+{x.amount} {x.currency.replace("_", " ")} · +{x.xp} XP</div></div>
            {x.claimed ? <St s="completed" /> : <button className="btn sm gold" disabled={!x.ready} onClick={() => submit(() => post(`/api/tasks/${x.id}/claim`), "Mukofot olindi 🎉").then(t_.reload)}>{x.ready ? "Olish" : "Bajaring"}</button>}
          </div>
        </div>
      ))}
    </>
  );
}

function Achievements() {
  const a = useAsync(() => get<any[]>("/api/achievements"), []);
  return (
    <>
      <Back title="Yutuqlar" />
      <div className="grid2">{(a.data ?? []).map((x) => (
        <div key={x.code} className="glass center" style={{ opacity: x.unlocked ? 1 : 0.45 }}><div style={{ fontSize: 34 }}>{x.icon}</div><b>{x.title}</b><div className="muted" style={{ fontSize: 12 }}>{x.description}</div><div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{x.unlocked ? "✅ ochilgan" : "🔒"}</div></div>
      ))}</div>
    </>
  );
}

function Vip() {
  const v = useAsync(() => get<any>("/api/vip"), []);
  if (v.loading) return <Skeletons n={1} grid={false} />;
  return (
    <>
      <Back title="VIP" />
      <div className="glass"><b>Joriy: {v.data.current ? `${v.data.current.badge} ${v.data.current.name}` : "—"}</b>
        <div className="muted">Sarflangan: {fmt(v.data.spent_uzs)} so‘m</div>
        {v.data.next && <div className="muted">Keyingi daraja: {v.data.next.name} — {fmt(v.data.next.min_spent_uzs - v.data.spent_uzs)} so‘m qoldi</div>}</div>
      {v.data.tiers.map((x: any) => <div key={x.id} className="glass" style={{ marginTop: 10 }}><b>{x.badge} {x.name}</b><div className="muted">{fmt(x.min_spent_uzs)} so‘mdan · −{x.discount_percent}% chegirma</div></div>)}
    </>
  );
}

function Market() {
  const [tab, setTab] = useState<"browse" | "mine" | "new" | "orders">("browse");
  return (
    <>
      <Back title="ABU MARKET" />
      <Tabs value={tab} set={setTab} items={[["browse", "Bozor"], ["mine", "Mening e‘lonlarim"], ["new", "+ E‘lon"], ["orders", "Bitimlar"]]} />
      {tab === "browse" && <Browse />}
      {tab === "mine" && <Mine />}
      {tab === "new" && <NewListing onDone={() => setTab("mine")} />}
      {tab === "orders" && <MarketOrdersList />}
    </>
  );
}

function Browse() {
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const l = useAsync(() => get<Listing[]>(`/api/market/listings?${new URLSearchParams({ ...(cat ? { category: cat } : {}), ...(q ? { q } : {}) })}`), [cat, q]);
  const [open, setOpen] = useState<Listing | null>(null);
  return (
    <>
      <input placeholder={t("search")} value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 8 }} />
      <div className="chips">{["", "stars", "gift", "nft", "premium", "voucher", "sticker", "other"].map((c) => <div key={c} className={`chip ${cat === c ? "on" : ""}`} onClick={() => setCat(c)}>{c || t("all")}</div>)}</div>
      {l.error ? <ErrorBox msg={l.error} retry={l.reload} /> : l.loading ? <Skeletons n={3} grid={false} /> : !l.data?.length ? <Empty icon="🛍" text="E‘lonlar yo‘q" /> : (
        <div className="glass">{l.data.map((x) => (
          <div key={x.id} className="tx" onClick={() => setOpen(x)} role="button">
            <div className="ic">{x.promoted ? "🔥" : "🏷"}</div>
            <div className="sp"><b>{x.title}</b><div className="muted">{x.seller?.name} {x.seller?.verified ? "✔️" : ""} · ⭐ {x.seller?.rating?.toFixed(1)} ({x.seller?.rating_count})</div></div>
            <div style={{ textAlign: "right" }}><b>{fmt(x.price_amount)} {x.price_currency.replace("_", " ")}</b><div className="muted">{x.quantity} ta</div></div>
          </div>
        ))}</div>
      )}
      {open && <ListingSheet x={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function ListingSheet({ x, onClose }: { x: Listing; onClose: () => void }) {
  const { submit, busy } = useSubmit();
  const [qty, setQty] = useState(1);
  return (
    <Sheet onClose={onClose} title={x.title}>
      <p className="muted">{x.description}</p>
      <div className="row"><span className="sp muted">Narx</span><b>{fmt(x.price_amount)} {x.price_currency.replace("_", " ")}</b></div>
      <div className="row"><span className="sp muted">Sotuvchi</span><span>{x.seller?.name} · {x.seller?.sales} sotuv</span></div>
      <div className="row" style={{ marginTop: 10 }}><span className="sp">Soni</span><button className="btn sm" onClick={() => setQty(Math.max(1, qty - 1))}>−</button><b>{qty}</b><button className="btn sm" onClick={() => setQty(Math.min(x.quantity, qty + 1))}>+</button></div>
      <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy} onClick={(e) => submit((k) => post(`/api/market/listings/${x.id}/buy`, { qty, idempotency_key: k }), "Escrow'ga to‘landi. Sotuvchi topshirgach tasdiqlang.").then((r) => { if (r) { flyCoins(x.price_currency, e.currentTarget); onClose(); go("orders"); } })}>Sotib olish (escrow)</button>
      <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>Pul sotuvchiga tovar tasdiqlanguncha escrow'da turadi. Komissiya sotuvchi ulushidan olinadi.</div>
    </Sheet>
  );
}

function Mine() {
  const l = useAsync(() => get<Listing[]>("/api/market/my/listings"), []);
  const st = useAsync(() => get<any>("/api/market/my/stats"), []);
  const { submit } = useSubmit();
  return (
    <>
      {st.data && <div className="grid2"><div className="glass center"><b>{st.data.listings}</b><div className="muted">E‘lon</div></div><div className="glass center"><b>{st.data.views}</b><div className="muted">Ko‘rish</div></div></div>}
      {st.data && st.data.verification_status !== "verified" && <button className="btn block" style={{ marginTop: 10 }} disabled={st.data.verification_status === "pending"} onClick={() => submit(() => post("/api/market/seller/apply"), "So‘rov yuborildi").then(st.reload)}>{st.data.verification_status === "pending" ? "Tasdiqlash kutilmoqda…" : "Sotuvchi sifatida tasdiqlanish"}</button>}
      <div className="glass" style={{ marginTop: 12 }}>{(l.data ?? []).length === 0 ? <div className="muted">E‘lonlaringiz yo‘q</div> : l.data!.map((x) => (
        <div key={x.id} className="tx"><div className="sp"><b>{x.title}</b><div className="muted">{fmt(x.price_amount)} {x.price_currency.replace("_", " ")} · {x.quantity} ta</div>{x.moderation_note && <div className="muted">{x.moderation_note}</div>}</div><St s={x.status} />
          {["active", "hidden", "sold_out"].includes(x.status) && <button className="btn sm" style={{ marginLeft: 8 }} onClick={() => submit(() => post(`/api/market/listings/${x.id}/toggle`)).then(l.reload)}>{x.status === "active" ? "Yashirish" : "Chiqarish"}</button>}
          {x.status === "active" && <button className="btn sm gold" style={{ marginLeft: 6 }} onClick={() => submit(() => post(`/api/market/listings/${x.id}/promote`), "Targ‘ib qilindi 🔥").then(l.reload)}>🔥</button>}
        </div>
      ))}</div>
    </>
  );
}

function NewListing({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ category: "stars", title: "", description: "", price_amount: 1000, price_currency: "ABU_F", quantity: 1 });
  const { busy, submit } = useSubmit();
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  return (
    <div className="glass">
      <label>Kategoriya</label>
      <select value={f.category} onChange={(e) => set("category", e.target.value)}>{["stars", "gift", "nft", "premium", "voucher", "sticker", "other"].map((c) => <option key={c}>{c}</option>)}</select>
      <label>Sarlavha</label><input value={f.title} onChange={(e) => set("title", e.target.value)} maxLength={120} />
      <label>Tavsif</label><textarea rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} maxLength={2000} />
      <div className="grid2"><div><label>Narx</label><input type="number" value={f.price_amount} onChange={(e) => set("price_amount", Number(e.target.value))} /></div>
        <div><label>Valyuta</label><select value={f.price_currency} onChange={(e) => set("price_currency", e.target.value)}><option value="ABU_F">ABU F</option><option value="ABU_TON">ABU TON</option></select></div></div>
      <label>Soni</label><input type="number" value={f.quantity} onChange={(e) => set("quantity", Number(e.target.value))} />
      <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy || f.title.length < 3} onClick={() => submit(() => post("/api/market/listings", f), "E‘lon moderatsiyaga yuborildi").then((r) => r && onDone())}>E‘lon berish</button>
    </div>
  );
}

function MarketOrdersList() {
  const l = useAsync(() => get<any[]>("/api/market/my/orders"), []);
  const { submit } = useSubmit();
  if (l.loading) return <Skeletons n={2} grid={false} />;
  return (
    <div className="glass">{(l.data ?? []).length === 0 ? <div className="muted">Bitimlar yo‘q</div> : l.data!.map((m) => (
      <div key={m.id} className="tx" style={{ flexWrap: "wrap" }}><div className="ic">{m.role === "buyer" ? "🛒" : "💰"}</div><div className="sp"><b>{m.title}</b><div className="muted">{m.role === "buyer" ? "Xarid" : "Sotuv"}</div></div><St s={m.status} />
        <div style={{ width: "100%", display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {m.role === "seller" && m.status === "held" && <button className="btn sm" onClick={() => submit(() => post(`/api/market/orders/${m.id}/deliver`)).then(l.reload)}>Topshirdim</button>}
          {m.role === "buyer" && ["held", "delivered"].includes(m.status) && <button className="btn sm gold" onClick={() => submit(() => post(`/api/market/orders/${m.id}/confirm`), "Tasdiqlandi").then(l.reload)}>Tasdiqlash</button>}
          {["held", "delivered"].includes(m.status) && <button className="btn sm danger" onClick={() => { const r = prompt("Nizo sababi (kamida 5 belgi)"); if (r && r.length >= 5) submit(() => post(`/api/market/orders/${m.id}/dispute`, { reason: r })).then(l.reload); }}>Nizo</button>}
        </div></div>
    ))}</div>
  );
}

function Settings() {
  const { me, refresh } = useMe();
  const s = me!.settings;
  const save = async (patchBody: any) => {
    const r = await patch("/api/me/settings", patchBody);
    if (patchBody.language) setLang(patchBody.language);
    if (patchBody.animations) applyAnimSettings(patchBody.animations);
    toast("Saqlandi", "ok"); refresh(); return r;
  };
  const notif = (k: string, v: boolean) => save({ notifications: { [k]: v } });
  const labels: Record<string, string> = { order: "Buyurtma", rental: "Ijara", payment: "To‘lov", bonus: "Bonus", product: "Mahsulot", promo: "Promo", referral: "Referal", market: "Market", support: "Yordam" };
  return (
    <>
      <Back title="Sozlamalar" />
      <div className="glass">
        <label>Til</label>
        <select value={s.language} onChange={(e) => save({ language: e.target.value })}><option value="uz">O‘zbekcha</option><option value="ru">Русский</option><option value="en">English</option></select>
        <label>Animatsiyalar</label>
        <select value={s.animations} onChange={(e) => save({ animations: e.target.value })}><option value="auto">Avto (qurilmaga qarab)</option><option value="on">Yoqilgan</option><option value="off">O‘chirilgan</option></select>
        <div className="row" style={{ marginTop: 12 }}><span className="sp">Balansni yashirish</span><Switch on={!!s.hide_balance} set={(v) => save({ hide_balance: v })} /></div>
        <div className="row" style={{ marginTop: 12 }}><span className="sp">Reytingda ko‘rinish</span><Switch on={!!s.show_in_leaderboard} set={(v) => save({ show_in_leaderboard: v })} /></div>
      </div>
      <h2>Bildirishnomalar</h2>
      <div className="glass">{Object.entries(labels).map(([k, l]) => (
        <div key={k} className="row" style={{ padding: "6px 0" }}><span className="sp">{l}</span><Switch on={s.notifications?.[k] !== false} set={(v) => notif(k, v)} /></div>
      ))}</div>
      <div className="muted center" style={{ marginTop: 14 }}>Sizning ABU ID: <b>{me!.abu_id}</b></div>
    </>
  );
}

function Support() {
  const faq = useAsync(() => get<any>("/api/support/faq"), []);
  const tickets = useAsync(() => get<any[]>("/api/support/tickets"), []);
  const [subject, setSubject] = useState(""), [body, setBody] = useState("");
  const { busy, submit } = useSubmit();
  return (
    <>
      <Back title="Yordam" />
      {faq.data?.faq?.map((x: any, i: number) => <details key={i} className="glass" style={{ marginBottom: 8 }}><summary><b>{x.q}</b></summary><div className="muted" style={{ marginTop: 8 }}>{x.a}</div></details>)}
      <h2>Murojaat yuborish</h2>
      <div className="glass">
        <label>Mavzu</label><input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={160} />
        <label>Xabar</label><textarea rows={4} value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} />
        <button className="btn gold block" style={{ marginTop: 12 }} disabled={busy || subject.length < 3 || !body} onClick={() => submit(() => post("/api/support/tickets", { subject, body }), "Yuborildi").then((r) => r && (setSubject(""), setBody(""), tickets.reload()))}>Yuborish</button>
      </div>
      <h2>Mening murojaatlarim</h2>
      <div className="glass">{(tickets.data ?? []).length === 0 ? <div className="muted">Yo‘q</div> : tickets.data!.map((x) => <div key={x.id} className="tx"><div className="sp"><b>{x.subject}</b></div><St s={x.status} /></div>)}</div>
    </>
  );
}

// yordamchi: sahifa tanlashni chetlab o'tish (eslatma: barcha yo'llar Cabinet ichida)
