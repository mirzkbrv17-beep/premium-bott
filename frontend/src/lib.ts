import { useCallback, useEffect, useState } from "react";

export const tg = (): any => (window as any).Telegram?.WebApp;
let token: string | null = sessionStorage.getItem("abu_token");
export const setToken = (t: string | null) => { token = t; t ? sessionStorage.setItem("abu_token", t) : sessionStorage.removeItem("abu_token"); };
export const hasToken = () => !!token;

export class ApiError extends Error { constructor(public code: string, message: string, public status: number) { super(message); } }

export async function api<T = any>(method: string, url: string, body?: any, form?: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(url, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const e = data?.error;
    throw new ApiError(typeof e === "string" ? e : e?.code || "error", e?.message || data?.message || `Xatolik (${res.status})`, res.status);
  }
  return data as T;
}
export const get = <T = any>(u: string) => api<T>("GET", u);
export const post = <T = any>(u: string, b: any = {}) => api<T>("POST", u, b);
export const patch = <T = any>(u: string, b: any) => api<T>("PATCH", u, b);
export const put = <T = any>(u: string, b: any) => api<T>("PUT", u, b);
export const del = <T = any>(u: string) => api<T>("DELETE", u);
export const idem = () => (crypto as any).randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;

export async function loginTelegram(): Promise<any> {
  const w = tg();
  const initData = w?.initData;
  if (!initData) {
    if (token) return get("/api/me").then((me) => ({ me }));
    throw new ApiError("no_telegram", "Ilovani Telegram ichida oching (@premiumabu_bot)", 0);
  }
  w.ready(); w.expand?.();
  const r = await post("/api/auth/telegram", { init_data: initData, start_param: w.initDataUnsafe?.start_param });
  setToken(r.token);
  return r;
}

// ---------------------------------------------------------------- format
export const fmt = (n: number | null | undefined) => (n ?? 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
export const uzs = (n: number) => `${fmt(n)} so‘m`;
export const CUR: Record<string, string> = { ABU_F: "ABU F", ABU_TON: "ABU TON", UZS: "so‘m" };
export const fdate = (s: string) => new Date(s).toLocaleString("uz-UZ", { timeZone: "Asia/Tashkent", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
export const fday = (s: string) => new Date(s).toLocaleDateString("uz-UZ", { timeZone: "Asia/Tashkent", day: "2-digit", month: "2-digit", year: "numeric" });

// ---------------------------------------------------------------- i18n (uz default; ru/en kengaytiriladi)
const uz: Record<string, string> = {
  shop: "Do‘kon", nft: "NFT", rent: "Ijara", orders: "Buyurtmalar", balance: "Balans", cabinet: "Kabinet", buy: "Sotib olish", rent_btn: "Ijaraga olish",
  search: "Qidirish...", all: "Hammasi", total: "Jami", pay_with: "To‘lov valyutasi", confirm: "Tasdiqlash", cancel: "Bekor qilish", topup: "To‘ldirish",
  my_balance: "Mening balansim", recent: "Oxirgi operatsiyalar", all_tx: "Barcha tranzaksiyalar", out_of_stock: "Tugagan", settings: "Sozlamalar", language: "Til",
  notifications: "Bildirishnomalar", animations: "Animatsiyalar", privacy: "Maxfiylik", hide_balance: "Balansni yashirish", help: "Yordam", loading: "Yuklanmoqda...",
  retry: "Qayta urinish", empty: "Hozircha bo‘sh", error: "Xatolik yuz berdi", per_day: "kun", from: "dan",
};
const ru: Record<string, string> = { shop: "Магазин", rent: "Аренда", orders: "Заказы", balance: "Баланс", cabinet: "Кабинет", buy: "Купить", search: "Поиск...", all: "Все", settings: "Настройки", language: "Язык", loading: "Загрузка..." };
const en: Record<string, string> = { shop: "Shop", rent: "Rent", orders: "Orders", balance: "Balance", cabinet: "Cabinet", buy: "Buy", search: "Search...", all: "All", settings: "Settings", language: "Language", loading: "Loading..." };
let lang = "uz";
export const setLang = (l: string) => { lang = l; };
export const t = (k: string) => ({ uz, ru, en } as any)[lang]?.[k] ?? uz[k] ?? k;

// ---------------------------------------------------------------- hooks
export function useAsync<T>(fn: () => Promise<T>, deps: any[] = []) {
  const [state, set] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true });
  const run = useCallback(() => { set((s) => ({ ...s, loading: true, error: undefined })); fn().then((data) => set({ data, loading: false })).catch((e) => set({ error: e.message, loading: false })); }, deps); // eslint-disable-line
  useEffect(run, [run]);
  return { ...state, reload: run };
}

export function useRoute(): string[] {
  const parse = () => (location.hash.replace(/^#\/?/, "") || "shop").split("/");
  const [r, set] = useState(parse);
  useEffect(() => { const h = () => set(parse()); window.addEventListener("hashchange", h); return () => window.removeEventListener("hashchange", h); }, []);
  return r;
}
export const go = (p: string) => { location.hash = "#/" + p; };

type Toast = { msg: string; kind: "ok" | "err" | "" } | null;
let toastSet: ((t: Toast) => void) | null = null;
export const bindToast = (f: (t: Toast) => void) => { toastSet = f; };
export const toast = (msg: string, kind: "ok" | "err" | "" = "") => { toastSet?.({ msg, kind }); setTimeout(() => toastSet?.(null), 3200); };
export const fail = (e: any) => toast(e?.message || t("error"), "err");

export function haptic(kind: "ok" | "err" = "ok") { try { tg()?.HapticFeedback?.notificationOccurred(kind === "ok" ? "success" : "error"); } catch { /* */ } }

export function applyAnimSettings(mode: string) {
  const el = document.documentElement;
  const weak = ((navigator as any).deviceMemory && (navigator as any).deviceMemory <= 2) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 3);
  el.dataset.anim = mode === "off" ? "off" : "on";
  el.dataset.lite = mode === "auto" && weak ? "1" : "0"; // sekin qurilmada yengil variant
}
