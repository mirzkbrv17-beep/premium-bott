export type Balances = Record<string, { balance: number; topped_up: number; spent: number }>;
export type Me = {
  abu_id: string; first_name: string; username?: string; photo_url?: string; referral_code: string;
  level: { level: number; xp: number; xp_in_level: number; xp_for_next: number };
  vip: { name: string; badge: string; discount_percent: number } | null; is_admin: boolean;
  balances: Balances; uzs: { topped_up: number; spent: number }; settings: any; bot_username: string;
};
export type Media = { id: number; kind: string; url: string } | null;
export type Product = {
  type: "product"; id: number; title: string; subtitle?: string; description?: string; price_uzs: number; final_price_uzs: number;
  discount_percent: number; color: string; category: string; category_kind: string; action: "buy" | "topup_f" | "topup_ton";
  available: boolean; stock: number | null; media: Media;
};
export type Item = {
  type: "item"; id: number; product_id: number; ref: string; title: string; subtitle?: string; attrs: Record<string, any>; color: string;
  price_uzs: number; media: Media; available: boolean; rent_price_per_day?: number; min_days?: number; max_days?: number; category: string;
};
export type Cat = { id: number; slug: string; kind: string; name: Record<string, string>; icon: string };
export type Order = { id: number; public_id: string; kind: string; status: string; total_uzs: number; discount_uzs: number; pay_currency: string; pay_amount: number; delivery_note?: string; created_at: string; items: { title: string; qty: number }[] };
export type Rental = { id: number; public_id: string; item: string; item_id: number; start_at: string; end_at: string; days: number; total_uzs: number; status: string; rating?: number };
export type Topup = { id: string; currency: string; units: number; uzs_amount: number; stars_amount?: number; provider: string; status: string; created_at: string; review_note?: string; has_receipt: boolean };
export type Tx = { tx_id: string; kind: string; title: string; amount: number; currency: string; status: string; method: string; ts: string; uzs_amount?: number; balance_after?: number; ref?: string };
export type Options = { abu_f: { uzs_per_unit: number; min_units: number }; abu_ton_packages: { id: number; units: number; price_uzs: number }[]; uzs_per_star: number; providers: { code: string; name: string; status: string; kind: string }[] };
export type Listing = { id: number; public_id: string; category: string; title: string; description?: string; price_amount: number; price_currency: string; quantity: number; status: string; promoted: boolean; views: number; seller?: { abu_id: string; name: string; verified: boolean; rating: number; rating_count: number; sales: number }; moderation_note?: string };
