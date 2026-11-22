import { useState } from "react";
import { get, tg, toast, fail, useAsync } from "../lib";
import { Empty, Skeletons } from "../ui";

export function Subscribe({ onOk }: { onOk: () => void }) {
  const ch = useAsync(() => get<{ missing: { title: string; url?: string }[]; unverifiable: boolean }>("/api/subscription"), []);
  const [checking, setChecking] = useState(false);
  const check = async () => {
    setChecking(true);
    try {
      const r = await get("/api/subscription");
      if (r.ok || r.unverifiable) onOk();
      else toast("Hali obuna to'liq emas", "err");
    } catch (e) { fail(e); } finally { setChecking(false); }
  };
  const missing = ch.data?.missing ?? [];
  return (
    <div className="app">
      <div className="glass center" style={{ marginTop: 40, padding: 22 }}>
        <div style={{ fontSize: 46 }}>📢</div>
        <h2 style={{ margin: "8px 0" }}>Majburiy obuna</h2>
        <p className="muted">ABU BOT'dan foydalanish uchun quyidagi kanal(lar)ga obuna bo‘ling va «Obunani tekshirish» tugmasini bosing.</p>
        {ch.loading ? <Skeletons n={1} grid={false} /> : missing.map((c, i) => (
          <a key={i} className="btn block" style={{ marginTop: 10, textAlign: "center" }} href={c.url} target="_blank" rel="noreferrer"
            onClick={(e) => { if (c.url && tg()?.openTelegramLink) { e.preventDefault(); tg().openTelegramLink(c.url); } }}>
            📢 {c.title}
          </a>
        ))}
        <button className="btn gold block" style={{ marginTop: 14 }} disabled={checking} onClick={check}>{checking ? "Tekshirilmoqda..." : "✅ Obunani tekshirish"}</button>
      </div>
    </div>
  );
}

/** Mahsulot to'g'ridan-to'g'ri havola bilan ochilganda (hozircha ro'yxatga qaytaradi). */
export function Detail(_: { id?: string }) {
  return (
    <div>
      <div className="top"><button className="btn sm" onClick={() => history.back()}>←</button><h1>Mahsulot</h1></div>
      <Empty icon="🔎" text="Mahsulotni ro‘yxatdan tanlang" />
    </div>
  );
}
