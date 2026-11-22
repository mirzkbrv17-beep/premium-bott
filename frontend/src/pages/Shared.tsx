import { useState } from "react";
import { fail, idem, toast, haptic } from "../lib";
import { reloadMe } from "../App";

/** Har tugmada bir martalik kalit yaratiladi; qayta bosilsa server bir xil natijani qaytaradi (ikki marta to'lov yo'q). */
export function useSubmit() {
  const [busy, setBusy] = useState(false);
  const submit = async <T,>(fn: (key: string) => Promise<T>, okMsg?: string): Promise<T | undefined> => {
    if (busy) return;
    setBusy(true);
    const key = idem();
    try {
      const r = await fn(key);
      haptic("ok");
      if (okMsg) toast(okMsg, "ok");
      await reloadMe();
      return r;
    } catch (e) {
      haptic("err");
      fail(e);
    } finally { setBusy(false); }
  };
  return { busy, submit };
}

export function Tabs<T extends string>({ value, set, items }: { value: T; set: (v: T) => void; items: [T, string][] }) {
  return <div className="tabs" role="tablist">{items.map(([k, l]) => <button key={k} role="tab" aria-selected={value === k} className={value === k ? "on" : ""} onClick={() => set(k)}>{l}</button>)}</div>;
}

export function PayChooser({ value, set, f, ton }: { value: string; set: (v: string) => void; f?: boolean; ton?: boolean }) {
  return (
    <div className="chips">
      {f !== false && <div className={`chip ${value === "ABU_F" ? "on" : ""}`} onClick={() => set("ABU_F")}>🪙 ABU F</div>}
      {ton !== false && <div className={`chip ${value === "ABU_TON" ? "on" : ""}`} onClick={() => set("ABU_TON")}>💠 ABU TON</div>}
    </div>
  );
}


