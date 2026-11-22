"""Idempotent boshlang'ich ma'lumotlar: rollar, ruxsatlar, kategoriyalar, VIP, yutuqlar, TON paketlari, provayderlar, vazifalar, savollar.
Mahsulotlar BU YERDA YARATILMAYDI (soxta mahsulot yo'q) - demo uchun: python -m app.seed_demo"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import PERMISSIONS, ROLE_PERMS
from .models import (Achievement, Category, PaymentProvider, Permission, Question, Role, RolePermission, Task, TonPackage, VIPTier)

CATS = [("premium", "goods", {"uz": "Telegram Premium"}, "⭐"), ("stars", "goods", {"uz": "Telegram Stars"}, "🌟"), ("gifts", "goods", {"uz": "Telegram Gifts"}, "🎁"),
        ("nft", "nft", {"uz": "Collectible / NFT"}, "💎"), ("abu_f", "abu_f", {"uz": "ABU F"}, "🪙"), ("abu_ton", "abu_ton", {"uz": "ABU TON"}, "💠"),
        ("stickers", "goods", {"uz": "Sticker / Emoji"}, "😀"), ("vouchers", "goods", {"uz": "Game voucher"}, "🎮")]
TIERS = [("Bronze", 1, 100_000, 1, "🥉"), ("Silver", 2, 500_000, 2, "🥈"), ("Gold", 3, 2_000_000, 3, "🥇"), ("Diamond", 4, 5_000_000, 5, "💎"), ("Abu Elite", 5, 15_000_000, 7, "👑")]
ACH = [("first_order", "Birinchi xarid", "Birinchi buyurtmani bering", "🛒", "orders", 1, 20), ("orders_10", "10 ta buyurtma", "10 ta buyurtma bering", "📦", "orders", 10, 50),
       ("first_topup", "Birinchi to'ldirish", "Balansni birinchi marta to'ldiring", "💳", "topups", 1, 20), ("streak_7", "7 kunlik streak", "7 kun ketma-ket bonus oling", "🔥", "streak", 7, 40),
       ("streak_30", "30 kunlik streak", "30 kun ketma-ket bonus oling", "🌋", "streak", 30, 150), ("ref_1", "Do'st taklif qildingiz", "1 do'st taklif qiling", "🤝", "referrals", 1, 30),
       ("ref_10", "Ambassador", "10 do'st taklif qiling", "📣", "referrals", 10, 150), ("gift_1", "Saxovatli", "Birinchi sovg'ani yuboring", "🎀", "gifts", 1, 20),
       ("rent_1", "Ijarachi", "Birinchi ijarani rasmiylashtiring", "🕒", "rentals", 1, 20), ("xp_500", "500 XP", "500 XP to'plang", "⚡", "xp", 500, 0)]
TASKS = [("first_order", "Birinchi xaridni amalga oshiring", "first_order", 20, 20), ("first_topup", "Balansni birinchi marta to'ldiring", "first_topup", 10, 20),
         ("invite_1", "1 ta do'stni taklif qiling", "invite_1", 25, 30), ("level_5", "5-darajaga yeting", "level_5", 30, 0)]
QUESTIONS = [("Telegram qaysi yili ishga tushirilgan?", ["2011", "2013", "2015", "2017"], 1), ("Toshkent qaysi davlat poytaxti?", ["Qozog'iston", "Qirg'iziston", "O'zbekiston", "Tojikiston"], 2),
             ("1 kilobayt necha bayt (ikkilik tizimda)?", ["100", "1000", "1024", "2048"], 2), ("Eng katta sayyora qaysi?", ["Mars", "Yupiter", "Saturn", "Neptun"], 1),
             ("HTTP 404 nimani anglatadi?", ["Server xatosi", "Topilmadi", "Ruxsat yo'q", "Muvaffaqiyat"], 1)]


async def seed(s: AsyncSession) -> None:
    perms = {p.code: p for p in (await s.execute(select(Permission))).scalars()}
    for code in PERMISSIONS:
        if code not in perms:
            perms[code] = Permission(code=code); s.add(perms[code])
    roles = {r.name: r for r in (await s.execute(select(Role))).scalars()}
    for name in ROLE_PERMS:
        if name not in roles:
            roles[name] = Role(name=name); s.add(roles[name])
    await s.flush()
    have = {(rp.role_id, rp.permission_id) for rp in (await s.execute(select(RolePermission))).scalars()}
    for name, codes in ROLE_PERMS.items():
        for code in (PERMISSIONS if codes == ["*"] else codes):
            if (roles[name].id, perms[code].id) not in have:
                s.add(RolePermission(role_id=roles[name].id, permission_id=perms[code].id))
    ex = set((await s.execute(select(Category.slug))).scalars())
    for i, (slug, kind, name, icon) in enumerate(CATS):
        if slug not in ex:
            s.add(Category(slug=slug, kind=kind, name=name, icon=icon, sort=i))
    ex = set((await s.execute(select(VIPTier.name))).scalars())
    for n, rank, spent, disc, badge in TIERS:
        if n not in ex:
            s.add(VIPTier(name=n, rank=rank, min_spent_uzs=spent, discount_percent=disc, badge=badge, perks=[f"{disc}% chegirma", "Maxsus belgi"]))
    ex = set((await s.execute(select(Achievement.code))).scalars())
    for code, title, desc, icon, metric, thr, xp in ACH:
        if code not in ex:
            s.add(Achievement(code=code, title=title, description=desc, icon=icon, metric=metric, threshold=thr, xp_reward=xp))
    if not (await s.execute(select(TonPackage.id).limit(1))).first():
        for i, (u, p) in enumerate([(200, 50_000), (400, 100_000), (800, 200_000), (1600, 400_000), (3200, 800_000), (6400, 1_600_000)]):
            s.add(TonPackage(units=u, price_uzs=p, sort=i))
    ex = set((await s.execute(select(PaymentProvider.code))).scalars())
    for i, (code, name) in enumerate([("stars", "Telegram Stars"), ("manual_card", "Karta (qo'lda tasdiq)"), ("click", "Click"), ("mock", "Mock (test)")]):
        if code not in ex:
            s.add(PaymentProvider(code=code, name=name, enabled=True, sort=i))
    ex = set((await s.execute(select(Task.code))).scalars())
    for code, title, kind, amt, xp in TASKS:
        if code not in ex:
            s.add(Task(code=code, title=title, kind=kind, amount=amt, xp=xp))
    if not (await s.execute(select(Question.id).limit(1))).first():
        for t, o, c in QUESTIONS:
            s.add(Question(text=t, options=o, correct_index=c))
    await s.flush()
