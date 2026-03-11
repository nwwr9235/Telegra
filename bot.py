import os
import re
import random
import asyncio
import logging
from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
)
from pyrogram.enums import ChatMemberStatus
from pytgcalls import PyTgCalls, idle
from pytgcalls.types import AudioPiped, AudioQuality
import yt_dlp

logging.basicConfig(level=logging.INFO)

API_ID    = int(os.environ.get("API_ID", 0))
API_HASH  = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

app   = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
calls = PyTgCalls(app)

# ============================
# 📦 قواعد البيانات
# ============================
warnings_db = {}
games       = {}
ranks       = {}
locked      = {}
whispers    = {}
music_queue = {}

# ============================
# 🏅 نظام الرتب
# ============================
RANK_ORDER = {
    "مالك أساسي 💎": 4,
    "مالك 🔱":        3,
    "أدمن ⚡":        2,
    "منشئ 👑":        1,
    "عضو":            0,
}

def rank_level(rank): return RANK_ORDER.get(rank, 0)

async def get_rank(chat_id, user_id):
    return ranks.get(chat_id, {}).get(user_id)

async def is_tg_admin(client, chat_id, user_id):
    try:
        m = await client.get_chat_member(chat_id, user_id)
        return m.status in [ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR]
    except:
        return False

async def can_act_on(chat_id, actor_id, target_id):
    a = rank_level(await get_rank(chat_id, actor_id))
    t = rank_level(await get_rank(chat_id, target_id))
    return a > t

def is_locked(chat_id, feature):
    return locked.get(chat_id, {}).get(feature, False)

# ============================
# 🎵 الموسيقى
# ============================
def search_youtube(query):
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if info and "entries" in info and info["entries"]:
                e = info["entries"][0]
                return {
                    "title": e.get("title", query),
                    "url": e.get("url"),
                    "webpage_url": e.get("webpage_url"),
                    "duration": e.get("duration", 0),
                }
    except Exception as e:
        logging.error(f"YT error: {e}")
    return None

def format_duration(s):
    if not s: return "؟"
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

async def play_song(client, chat_id, song, message=None):
    try:
        if chat_id not in music_queue:
            music_queue[chat_id] = []
        music_queue[chat_id].append(song)

        if len(music_queue[chat_id]) == 1:
            await calls.join_group_call(
                chat_id,
                AudioPiped(song["url"], AudioQuality.HIGH),
            )
            if message:
                await message.reply(
                    f"🎵 يعزف الآن:\n🎼 {song['title']}\n⏱ {format_duration(song.get('duration', 0))}"
                )
        else:
            if message:
                pos = len(music_queue[chat_id])
                await message.reply(f"➕ تمت الإضافة للقائمة #{pos}:\n🎼 {song['title']}")
    except Exception as e:
        logging.error(f"Play error: {e}")
        if message:
            await message.reply("❌ تأكد أن هناك مكالمة صوتية نشطة في المجموعة ثم حاول مجدداً!")

async def skip_song(client, chat_id, message=None):
    queue = music_queue.get(chat_id, [])
    if not queue:
        if message: await message.reply("❌ لا توجد أغاني!"); return
    queue.pop(0)
    if queue:
        try:
            await calls.change_stream(chat_id, AudioPiped(queue[0]["url"], AudioQuality.HIGH))
            if message: await message.reply(f"⏭ يعزف الآن: {queue[0]['title']}")
        except Exception as e:
            if message: await message.reply(f"❌ خطأ: {e}")
    else:
        try: await calls.leave_group_call(chat_id)
        except: pass
        if message: await message.reply("✅ انتهت القائمة!")

# ============================
# 🏅 رفع وتنزيل الرتبة
# ============================
async def promote_user(client, message, new_rank):
    chat_id = message.chat.id
    actor   = message.from_user
    if not message.reply_to_message:
        await message.reply("⚠️ رد على رسالة الشخص المراد رفعه"); return
    target    = message.reply_to_message.from_user
    if target.is_bot: await message.reply("❌ لا يمكن إعطاء رتبة لبوت!"); return
    if target.id == actor.id: await message.reply("❌ لا يمكنك رفع نفسك!"); return
    actor_lvl  = rank_level(await get_rank(chat_id, actor.id))
    target_lvl = rank_level(await get_rank(chat_id, target.id))
    new_lvl    = rank_level(new_rank)
    is_adm     = await is_tg_admin(client, chat_id, actor.id)
    if not is_adm:
        if actor_lvl < 3: await message.reply("❌ لا تملك صلاحية إعطاء الرتب!"); return
        if actor_lvl == 3 and new_lvl >= 3: await message.reply("❌ لا يمكنك رفع لرتبة مالك أو أعلى!"); return
        if target_lvl >= actor_lvl: await message.reply("❌ لا يمكنك رفع شخص بنفس رتبتك أو أعلى!"); return
    if chat_id not in ranks: ranks[chat_id] = {}
    ranks[chat_id][target.id] = new_rank
    await message.reply(f"✅ تم رفع [{target.first_name}](tg://user?id={target.id}) إلى {new_rank}!", disable_web_page_preview=True)

async def demote_user(client, message):
    chat_id = message.chat.id
    actor   = message.from_user
    if not message.reply_to_message:
        await message.reply("⚠️ رد على رسالة الشخص"); return
    target      = message.reply_to_message.from_user
    actor_lvl   = rank_level(await get_rank(chat_id, actor.id))
    target_rank = await get_rank(chat_id, target.id)
    target_lvl  = rank_level(target_rank)
    is_adm      = await is_tg_admin(client, chat_id, actor.id)
    if not is_adm and actor_lvl == 0: await message.reply("❌ لا تملك صلاحية التنزيل!"); return
    if not is_adm and target_lvl >= actor_lvl: await message.reply("❌ لا يمكنك تنزيل شخص بنفس رتبتك أو أعلى!"); return
    if target_lvl == 0: await message.reply("⚠️ هذا الشخص ليس لديه رتبة!"); return
    if not is_adm and actor_lvl == 3 and target_lvl >= 3: await message.reply("❌ لا يمكنك تنزيل مالك!"); return
    if chat_id in ranks and target.id in ranks[chat_id]:
        del ranks[chat_id][target.id]
    await message.reply(f"✅ تم تنزيل [{target.first_name}](tg://user?id={target.id}) من رتبة {target_rank}!", disable_web_page_preview=True)

# ============================
# 🔍 فحص المحتوى
# ============================
BANNED_WORDS = ["سكس","بورن","إباحي","شرموطة","porn","sex","nude","naked","xxx"]
BAD_PATTERNS = [r"t\.me/\+", r"https?://bit\.ly", r"تابعونا على", r"ربح.*سريع"]

async def check_content(client, message):
    if not message or not message.chat or not message.from_user: return
    chat_id = message.chat.id
    user    = message.from_user
    if await is_tg_admin(client, chat_id, user.id): return
    if rank_level(await get_rank(chat_id, user.id)) >= 1: return
    text = message.text or message.caption or ""
    bad  = any(w.lower() in text.lower() for w in BANNED_WORDS)
    if not bad:
        bad = any(re.search(p, text, re.IGNORECASE) for p in BAD_PATTERNS)
    if bad:
        try: await message.delete()
        except: pass

async def check_locks(client, message):
    if not message or not message.chat or not message.from_user: return
    chat_id = message.chat.id
    user    = message.from_user
    if await is_tg_admin(client, chat_id, user.id): return
    if rank_level(await get_rank(chat_id, user.id)) >= 1: return
    ls  = locked.get(chat_id, {})
    bad = False
    if ls.get("stickers") and message.sticker: bad = True
    if ls.get("links") and message.text and re.search(r'https?://|t\.me/', message.text): bad = True
    if ls.get("media") and (message.photo or message.video or message.document): bad = True
    if bad:
        try: await message.delete()
        except: pass

# ============================
# 🎮 الألعاب
# ============================
QUESTIONS = [
    "كم عدد أركان الإسلام؟", "ما اسم والدة النبي محمد ﷺ؟",
    "ما عاصمة المملكة العربية السعودية؟", "في أي سنة فُتحت مكة المكرمة؟",
    "ما أطول سورة في القرآن الكريم؟", "ما عاصمة مصر؟",
    "في أي دولة يقع برج خليفة؟", "ما عاصمة تركيا؟",
    "ما اسم أطول نهر في العالم؟", "كم عدد ركعات صلاة الفجر؟",
    "ما عاصمة فرنسا؟", "ما أكبر دولة في العالم مساحةً؟",
]

async def auto_unmute(client, chat_id, user_id, user_name, delay):
    await asyncio.sleep(delay)
    if games.get(chat_id, {}).get("phase") == "answering":
        try:
            await client.restrict_chat_member(chat_id, user_id, until_date=None)
            await client.send_message(chat_id, f"⏰ انتهت مدة الكتم على {user_name}! لم يجب 😄")
        except: pass
        games.get(chat_id, {}).update({"active": False})

# ============================
# 📨 معالج الرسائل
# ============================
@app.on_message(filters.text & filters.group)
async def handle_text(client, message: Message):
    text    = message.text.strip()
    chat_id = message.chat.id
    user    = message.from_user
    reply   = message.reply_to_message

    await check_content(client, message)
    await check_locks(client, message)

    is_adm    = await is_tg_admin(client, chat_id, user.id)
    user_rank = await get_rank(chat_id, user.id)
    user_lvl  = rank_level(user_rank)

    # ─── الإدارة ───
    if text == "حظر":
        if not is_adm and user_lvl < 4: await message.reply("❌ لا تملك صلاحية الحظر!"); return
        if not reply: await message.reply("⚠️ رد على رسالة المستخدم"); return
        t = reply.from_user
        if not await can_act_on(chat_id, user.id, t.id) and not is_adm: await message.reply("❌ لا يمكنك حظر شخص بنفس رتبتك!"); return
        await client.ban_chat_member(chat_id, t.id)
        await message.reply(f"🚫 تم حظر [{t.first_name}](tg://user?id={t.id})!", disable_web_page_preview=True)

    elif text == "رفع الحظر":
        if not is_adm and user_lvl < 4: await message.reply("❌ لا تملك صلاحية رفع الحظر!"); return
        if not reply: await message.reply("⚠️ رد على رسالة المستخدم"); return
        await client.unban_chat_member(chat_id, reply.from_user.id)
        await message.reply(f"✅ تم رفع الحظر عن {reply.from_user.first_name}!")

    elif text == "كتم":
        if not is_adm and user_lvl < 3: await message.reply("❌ لا تملك صلاحية الكتم!"); return
        if not reply: await message.reply("⚠️ رد على رسالة المستخدم"); return
        t = reply.from_user
        if not await can_act_on(chat_id, user.id, t.id) and not is_adm: await message.reply("❌ لا يمكنك كتم شخص بنفس رتبتك!"); return
        until = datetime.now() + timedelta(hours=1)
        await client.restrict_chat_member(chat_id, t.id, until_date=until)
        await message.reply(f"🔇 تم كتم {t.first_name} ساعة!")

    elif text == "رفع الكتم":
        if not is_adm and user_lvl < 3: await message.reply("❌ لا تملك صلاحية رفع الكتم!"); return
        if not reply: await message.reply("⚠️ رد على رسالة المستخدم"); return
        await client.restrict_chat_member(chat_id, reply.from_user.id, until_date=None)
        await message.reply(f"🔊 تم رفع الكتم عن {reply.from_user.first_name}!")

    elif text == "طرد":
        if not is_adm and user_lvl < 3: await message.reply("❌ لا تملك صلاحية الطرد!"); return
        if not reply: await message.reply("⚠️ رد على رسالة المستخدم"); return
        t = reply.from_user
        if not await can_act_on(chat_id, user.id, t.id) and not is_adm: await message.reply("❌ لا يمكنك طرد شخص بنفس رتبتك!"); return
        await client.ban_chat_member(chat_id, t.id)
        await client.unban_chat_member(chat_id, t.id)
        await message.reply(f"👢 تم طرد {t.first_name}!")

    elif text == "تحذير":
        if not is_adm and user_lvl < 2: await message.reply("❌ لا تملك صلاحية التحذير!"); return
        if not reply: await message.reply("⚠️ رد على رسالة المستخدم"); return
        t = reply.from_user
        if not await can_act_on(chat_id, user.id, t.id): await message.reply("❌ لا يمكنك تحذير شخص بنفس رتبتك!"); return
        key = f"{chat_id}_{t.id}"
        warnings_db[key] = warnings_db.get(key, 0) + 1
        count = warnings_db[key]
        if count >= 3:
            await client.ban_chat_member(chat_id, t.id)
            warnings_db[key] = 0
            await message.reply(f"🚫 {t.first_name} وصل 3 تحذيرات وتم حظره!")
        else:
            await message.reply(f"⚠️ تحذير لـ {t.first_name} - التحذيرات: {count}/3")

    elif text == "حذف":
        if not is_adm and user_lvl < 4: await message.reply("❌ لا تملك صلاحية حذف الرسائل!"); return
        if not reply: await message.reply("⚠️ رد على الرسالة المراد حذفها"); return
        try: await reply.delete(); await message.delete()
        except: await message.reply("❌ لا يمكن حذف الرسالة!")

    # ─── الرتب ───
    elif text == "رفع مالك أساسي": await promote_user(client, message, "مالك أساسي 💎")
    elif text == "رفع مالك":        await promote_user(client, message, "مالك 🔱")
    elif text == "رفع أدمن":        await promote_user(client, message, "أدمن ⚡")
    elif text == "رفع منشئ":        await promote_user(client, message, "منشئ 👑")
    elif text == "تنزيل":           await demote_user(client, message)

    elif text == "رتبتي":
        await message.reply(f"🏅 رتبتك: {user_rank}" if user_rank else "👤 ليس لديك رتبة بعد")

    elif text == "رتبة" and reply:
        t = reply.from_user
        r = await get_rank(chat_id, t.id)
        await message.reply(f"🏅 رتبة {t.first_name}: {r}" if r else f"👤 {t.first_name} ليس لديه رتبة")

    elif text == "الرتب":
        if not ranks.get(chat_id): await message.reply("⚠️ لا توجد رتب بعد!"); return
        txt = "🏅 قائمة الرتب:\n\n"
        for uid, r in ranks[chat_id].items():
            try:
                m = await client.get_chat_member(chat_id, uid)
                txt += f"• {m.user.first_name}: {r}\n"
            except: pass
        await message.reply(txt)

    # ─── القفل ───
    elif text in ["قفل الملصقات","فتح الملصقات","قفل الروابط","فتح الروابط",
                  "قفل الوسائط","فتح الوسائط","قفل الهمسات","فتح الهمسات","قفل الألعاب","فتح الألعاب"]:
        if not is_adm and user_lvl < 4: await message.reply("❌ فقط المالك الأساسي يمكنه القفل!"); return
        cmds = {
            "قفل الملصقات":("stickers",True),"فتح الملصقات":("stickers",False),
            "قفل الروابط":("links",True),"فتح الروابط":("links",False),
            "قفل الوسائط":("media",True),"فتح الوسائط":("media",False),
            "قفل الهمسات":("whisper",True),"فتح الهمسات":("whisper",False),
            "قفل الألعاب":("games",True),"فتح الألعاب":("games",False),
        }
        feat, state = cmds[text]
        if chat_id not in locked: locked[chat_id] = {}
        locked[chat_id][feat] = state
        names = {"stickers":"الملصقات","links":"الروابط","media":"الوسائط","whisper":"الهمسات","games":"الألعاب"}
        await message.reply(f"{'🔒 تم قفل' if state else '🔓 تم فتح'} {names[feat]}!")

    # ─── الايدي ───
    elif text in ["ا","اا","الايدي"]:
        t = reply.from_user if reply else user
        r = await get_rank(chat_id, t.id)
        caption = (f"👤 معلومات:\n\n"
                   f"الاسم: [{t.first_name}](tg://user?id={t.id})\n"
                   f"🆔 الايدي: `{t.id}`\n"
                   f"👤 يوزر: @{t.username or 'لا يوجد'}"
                   + (f"\n🏅 الرتبة: {r}" if r else ""))
        try:
            photos = await client.get_profile_photos(t.id, limit=1)
            if photos:
                await message.reply_photo(photos[0].file_id, caption=caption)
            else:
                await message.reply(caption, disable_web_page_preview=True)
        except:
            await message.reply(caption, disable_web_page_preview=True)

    # ─── الهمسات ───
    elif text.startswith("همسة") or text.startswith("همسه"):
        if is_locked(chat_id, "whisper") and user_lvl < 1:
            await message.reply("🔒 الهمسات مقفلة!"); return
        if not reply: await message.reply("⚠️ رد على رسالة الشخص الذي تريد همسه!"); return
        receiver = reply.from_user
        if user.id == receiver.id: await message.reply("😂 لا يمكنك همس لنفسك!"); return
        if receiver.is_bot: await message.reply("😂 لا يمكنك همس لبوت!"); return
        parts = text.split(None, 1)
        wtext = parts[1] if len(parts) > 1 else ""
        if not wtext: await message.reply("⚠️ اكتب نص الهمسة!\nمثال: همسة أهلاً كيف حالك؟"); return
        wid = f"{user.id}_{receiver.id}_{random.randint(1000,9999)}"
        whispers[wid] = {"from_id":user.id,"from_name":user.first_name,"to_id":receiver.id,"to_name":receiver.first_name,"text":wtext}
        try: await message.delete()
        except: pass
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("👁 اقرأ الهمسة", callback_data=f"w_{wid}")]])
        await client.send_message(chat_id,
            f"💌 همسة سرية من {user.first_name} إلى {receiver.first_name}\nفقط {receiver.first_name} يمكنه قراءتها 🤫",
            reply_markup=kb)

    # ─── الزواج ───
    elif text == "زواج":
        if not reply: await message.reply("⚠️ رد على رسالة الشخص!"); return
        u2 = reply.from_user
        if user.id == u2.id: await message.reply("😂 لا يمكنك الزواج من نفسك!"); return
        if u2.is_bot: await message.reply("😂 لا يمكنك الزواج من بوت!"); return
        await message.reply(
            f"💍 تم عقد الزواج!\n\n"
            f"🤵 [{user.first_name}](tg://user?id={user.id})\n"
            f"👰 [{u2.first_name}](tg://user?id={u2.id})\n\n"
            f"🎊 مبروك! بالرفاه والبنين! 🌹",
            disable_web_page_preview=True)

    # ─── معلومات ───
    elif text == "القواعد":
        await message.reply("📜 قواعد المجموعة:\n\n1️⃣ الاحترام المتبادل\n2️⃣ ممنوع السبّ\n3️⃣ ممنوع الإعلانات\n4️⃣ ممنوع السبام\n\n⚠️ مخالفة القواعد = تحذير ثم حظر!")

    elif text == "معلومات":
        chat  = await client.get_chat(chat_id)
        count = await client.get_chat_members_count(chat_id)
        await message.reply(f"ℹ️ المجموعة:\n📛 {chat.title}\n🆔 {chat_id}\n👥 الأعضاء: {count}")

    # ─── الموسيقى ───
    elif text.startswith("بحث "):
        query = text[4:].strip()
        if not query: await message.reply("⚠️ مثال: بحث يا ليل"); return
        msg = await message.reply("🔍 جاري البحث...")
        song = await asyncio.get_event_loop().run_in_executor(None, search_youtube, query)
        if not song: await msg.edit("❌ لم يتم العثور على نتائج!"); return
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("▶️ تشغيل في المكالمة", callback_data=f"play_{chat_id}|{song['webpage_url']}")]])
        await msg.edit(
            f"🎵 نتيجة البحث:\n\n🎼 {song['title']}\n⏱ {format_duration(song.get('duration',0))}\n\nاضغط ▶️ للتشغيل",
            reply_markup=kb)

    elif text.startswith("تشغيل "):
        query = text[6:].strip()
        if not query: await message.reply("⚠️ مثال: تشغيل يا ليل"); return
        msg = await message.reply("⏳ جاري التحميل...")
        song = await asyncio.get_event_loop().run_in_executor(None, search_youtube, query)
        if not song: await msg.edit("❌ لم يتم العثور على الأغنية!"); return
        await msg.edit(f"🎵 جاري التشغيل...\n🎼 {song['title']}")
        await play_song(client, chat_id, song, message)

    elif text == "ايقاف":
        if not is_adm and user_lvl < 2: await message.reply("❌ لا تملك صلاحية الإيقاف!"); return
        try:
            await calls.leave_group_call(chat_id)
            music_queue.pop(chat_id, None)
            await message.reply("⏹ تم إيقاف الموسيقى!")
        except:
            await message.reply("❌ لا توجد موسيقى تعزف الآن!")

    elif text == "تخطي":
        if not is_adm and user_lvl < 2: await message.reply("❌ لا تملك صلاحية التخطي!"); return
        await skip_song(client, chat_id, message)

    elif text == "الأغاني":
        queue = music_queue.get(chat_id, [])
        if not queue: await message.reply("📭 قائمة الأغاني فارغة!"); return
        txt = "🎵 قائمة الأغاني:\n\n"
        for i, s in enumerate(queue, 1):
            txt += f"{'▶️' if i==1 else f'{i}.'} {s['title']}\n"
        await message.reply(txt)

    # ─── الألعاب ───
    elif text == "احكام":
        if is_locked(chat_id, "games"): await message.reply("🔒 الألعاب مقفلة!"); return
        if games.get(chat_id, {}).get("active"): await message.reply("⚠️ يوجد لعبة جارية! اكتب انهاء أولاً."); return
        games[chat_id] = {"active":True,"type":"احكام","starter_id":user.id,"starter_name":user.first_name,"players":[{"id":user.id,"name":user.first_name}],"phase":"joining"}
        await message.reply(f"⚖️ بدأت لعبة الأحكام!\n\n• تم تسجيلك {user.first_name} .\n• اللي يبيلعب يرسل ( انا ) .")

    elif text == "عقاب":
        if is_locked(chat_id, "games"): await message.reply("🔒 الألعاب مقفلة!"); return
        if games.get(chat_id, {}).get("active"): await message.reply("⚠️ يوجد لعبة جارية! اكتب انهاء أولاً."); return
        games[chat_id] = {"active":True,"type":"عقاب","starter_id":user.id,"starter_name":user.first_name,"players":[{"id":user.id,"name":user.first_name}],"phase":"joining","punished_id":None}
        await message.reply(f"😈 بدأت لعبة العقاب!\n\n• تم تسجيلك {user.first_name} .\n• اللي يبيلعب يرسل ( انا ) .")

    elif text == "انهاء":
        if games.get(chat_id, {}).get("active"):
            if is_adm or user.id == games[chat_id]["starter_id"] or user_lvl >= 1:
                games[chat_id]["active"] = False
                await message.reply("✅ تم إنهاء اللعبة!")
            else: await message.reply("❌ فقط من بدأ اللعبة أو الأدمن!")
        else: await message.reply("⚠️ لا توجد لعبة جارية!")

    elif games.get(chat_id, {}).get("active"):
        game = games[chat_id]
        if game["phase"] == "joining":
            if text == "انا":
                if any(p["id"] == user.id for p in game["players"]):
                    await message.reply("• انت مضاف من قبل .")
                else:
                    game["players"].append({"id":user.id,"name":user.first_name})
                    await message.reply(f"• تم إضافتك للعبة .\n• للانتهاء يرسل نعم اللي بداء اللعبة .")
            elif text == "نعم":
                if user.id != game["starter_id"]: await message.reply("❌ فقط من بدأ اللعبة!"); return
                if len(game["players"]) < 2: await message.reply("⚠️ يجب أن ينضم لاعب واحد على الأقل!"); return
                if game["type"] == "احكام":
                    h, mp = random.sample(game["players"], 2)
                    games[chat_id]["active"] = False
                    await message.reply(
                        f"⚖️ نتيجة الأحكام!\n\n"
                        f"👨‍⚖️ الحاكم: [{h['name']}](tg://user?id={h['id']})\n"
                        f"😬 المحكوم: [{mp['name']}](tg://user?id={mp['id']})\n\n"
                        f"على {h['name']} إصدار الحكم! 😄",
                        disable_web_page_preview=True)
                elif game["type"] == "عقاب":
                    p = random.choice(game["players"])
                    q = random.choice(QUESTIONS)
                    game["phase"]        = "answering"
                    game["punished_id"]  = p["id"]
                    game["punished_name"]= p["name"]
                    until = datetime.now() + timedelta(minutes=3)
                    try: await client.restrict_chat_member(chat_id, p["id"], until_date=until)
                    except: pass
                    await message.reply(
                        f"😈 نتيجة العقاب!\n\n"
                        f"🎯 المعاقب: [{p['name']}](tg://user?id={p['id']})\n"
                        f"🔇 كتم 3 دقائق حتى يجاوب:\n\n❓ {q}",
                        disable_web_page_preview=True)
                    asyncio.create_task(auto_unmute(client, chat_id, p["id"], p["name"], 180))
        elif game["phase"] == "answering" and user.id == game.get("punished_id"):
            try: await client.restrict_chat_member(chat_id, user.id, until_date=None)
            except: pass
            games[chat_id]["active"] = False
            await message.reply(f"✅ أجاب {game['punished_name']}! تم رفع الكتم 🎉")

# ============================
# 🔘 الأزرار
# ============================
@app.on_callback_query()
async def handle_callback(client, query: CallbackQuery):
    data = query.data

    if data.startswith("w_"):
        wid = data[2:]
        if wid not in whispers: await query.answer("❌ انتهت صلاحية الهمسة!", show_alert=True); return
        w = whispers[wid]
        if query.from_user.id != w["to_id"]: await query.answer("❌ هذه الهمسة ليست لك! 😄", show_alert=True); return
        try:
            await client.send_message(query.from_user.id, f"💌 همسة من {w['from_name']}:\n\n{w['text']}")
            await query.answer("✅ تم إرسال الهمسة لرسائلك الخاصة!", show_alert=True)
            del whispers[wid]
        except:
            await query.answer("❌ افتح محادثة مع البوت أولاً!", show_alert=True)

    elif data.startswith("play_"):
        parts = data.split("|", 1)
        if len(parts) < 2: return
        chat_id = int(parts[0].replace("play_", ""))
        url     = parts[1]
        await query.answer("⏳ جاري التحميل...")
        def get_info():
            ydl_opts = {"format":"bestaudio/best","quiet":True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return {"title":info.get("title"),"url":info.get("url"),"duration":info.get("duration",0)}
        try:
            song = await asyncio.get_event_loop().run_in_executor(None, get_info)
            await play_song(client, chat_id, song)
            await query.message.edit(f"▶️ جاري التشغيل:\n🎼 {song['title']}")
        except:
            await query.message.edit("❌ حدث خطأ أثناء التشغيل!")

# ============================
# 🎵 انتهاء الأغنية
# ============================
@calls.on_stream_end()
async def on_end(client, update):
    chat_id = update.chat_id
    queue   = music_queue.get(chat_id, [])
    if queue: queue.pop(0)
    if queue:
        try:
            await calls.change_stream(chat_id, AudioPiped(queue[0]["url"], AudioQuality.HIGH))
            await app.send_message(chat_id, f"🎵 يعزف الآن: {queue[0]['title']}")
        except: pass
    else:
        try: await calls.leave_group_call(chat_id)
        except: pass

# ============================
# 👋 ترحيب
# ============================
@app.on_message(filters.new_chat_members)
async def welcome(client, message: Message):
    for m in message.new_chat_members:
        if not m.is_bot:
            await message.reply(f"👋 أهلاً {m.first_name}!\nاكتب القواعد 📜")

# ============================
# /start
# ============================
@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    await message.reply(
        "👋 مرحباً!\n\n"
        "🛡 الإدارة:\n"
        "حظر • رفع الحظر • كتم • رفع الكتم • طرد • تحذير • حذف\n\n"
        "🏅 الرتب (رد على شخص):\n"
        "رفع مالك أساسي • رفع مالك • رفع أدمن • رفع منشئ • تنزيل\n"
        "رتبتي • رتبة • الرتب\n\n"
        "🔒 القفل:\n"
        "قفل/فتح: الملصقات • الروابط • الوسائط • الهمسات • الألعاب\n\n"
        "🆔 الايدي: ا أو اا\n\n"
        "💌 الهمسات: همسة [النص] (رد على شخص)\n\n"
        "🎵 الموسيقى:\n"
        "بحث [أغنية] • تشغيل [أغنية] • ايقاف • تخطي • الأغاني\n\n"
        "🎮 الألعاب: احكام • عقاب • زواج • انهاء"
    )

# ============================
# 🚀 تشغيل
# ============================
async def main():
    await app.start()
    await calls.start()
    print("✅ البوت يعمل!")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
