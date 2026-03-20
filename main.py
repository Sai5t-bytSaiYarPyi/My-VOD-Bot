import asyncio
import logging
import os
import re
from aiohttp import web
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, BotCommand, BotCommandScopeDefault, BotCommandScopeChat
from motor.motor_asyncio import AsyncIOMotorClient

# ==========================================
# ၁။ လိုအပ်သော အချက်အလက်များ (.env မှ ဖတ်ယူခြင်း)
# ==========================================
load_dotenv() # .env ဖိုင်ထဲက အချက်အလက်တွေကို ဆွဲထုတ်မည်

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# ==========================================
# ၂။ Database နှင့် Bot ချိတ်ဆက်ခြင်း
# ==========================================
cluster = AsyncIOMotorClient(MONGO_URI)
db = cluster.vod_bot_db
users_col = db.users
series_col = db.series

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

async def get_user(user_id: int):
    return await users_col.find_one({"user_id": user_id})

async def register_user(user_id: int):
    user = await get_user(user_id)
    if not user:
        await users_col.insert_one({
            "user_id": user_id,
            "is_vip": False,
            "purchased_series": []
        })

# ==========================================
# ၃။ User Flow (Deep Link & Menu System)
# ==========================================
@dp.message(CommandStart())
async def start_handler(message: Message, command: CommandObject):
    user_id = message.from_user.id
    await register_user(user_id)

    series_id = command.args 

    if not series_id:
        await message.answer("🎬 မင်္ဂလာပါ။ ရုပ်ရှင်ကြည့်ရှုရန် သက်ဆိုင်ရာ Link မှတစ်ဆင့် ဝင်ရောက်ပါ။\n\nVIP ဝယ်ယူရန် @NaJu_New သို့ ဆက်သွယ်ပါ။")
        return

    series_info = await series_col.find_one({"series_id": series_id})
    
    if not series_info:
        await message.answer("❌ အမှားအယွင်းဖြစ်နေပါသည်။ လင့်ခ် မှားယွင်းနေပါသည် (သို့) ဇာတ်ကား ဖျက်ခံလိုက်ရပါသည်။")
        return

    keyboard_buttons = []
    episodes = series_info.get("episodes", [])
    
    if not episodes:
        await message.answer("⚠️ ဤဇာတ်ကားအတွက် အပိုင်းများ မတင်ရသေးပါ။")
        return

    # ==========================================
    # 🌟 နံပါတ်စဉ်အလိုက် အလိုအလျောက် စီပေးမည့်စနစ် (Natural Sorting)
    # ==========================================
    # "Ninja Scroll 1", "Ninja Scroll 10", "Ninja Scroll 2" များကို 1, 2, 10 အဖြစ် အမှန်တကယ် ဂဏန်းစဉ်အတိုင်း စီပေးမည်
    def natural_sort_key(ep):
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', ep['name'])]
    
    episodes.sort(key=natural_sort_key) # အပိုင်းများကို အစဉ်လိုက် စီလိုက်ပါပြီ

    # ==========================================
    # 🌟 Hidden Order နှင့် နံပါတ်စဉ်အလိုက် စီပေးမည့်စနစ် (New Update)
    # ==========================================
    def sort_logic(ep):
        # Admin က သတ်မှတ်ထားတဲ့ order ရှိရင် အဲ့ဒီ order ကို ယူမည်၊ မရှိရင် 9999 (အောက်ဆုံး) ဟု မှတ်မည်
        custom_order = ep.get('order', 9999) 
        # မူလ အလိုအလျောက် စီမည့်စနစ် (Natural Sort)
        name_sort = [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', ep['name'])]
        
        # ပထမဆုံး custom_order ဖြင့် စီမည်၊ တူညီနေပါက နာမည်ဖြင့် ဆက်စီမည်
        return (custom_order, name_sort)
    
    episodes.sort(key=sort_logic)
    # ==========================================
    # ==========================================

    # စီပြီးသား အပိုင်းများကို ခလုတ်အဖြစ် ပြောင်းမည်
    for ep in episodes:
        callback_data = f"watch|{series_id}|{ep['msg_id']}"
        btn = InlineKeyboardButton(text=f"▶️ {ep['name']}", callback_data=callback_data)
        keyboard_buttons.append([btn])

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer(
        f"<b>{series_info['title']}</b>\n\nℹ️ ကြည့်ရှုလိုသည့် အပိုင်းကို အောက်ပါ ခလုတ်များတွင် ရွေးချယ်ပါ။",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

# ==========================================
# ၄။ Access Check (ကြည့်ရှုခွင့် စစ်ဆေးခြင်း)
# ==========================================
@dp.callback_query(F.data.startswith("watch|"))
async def handle_watch_button(callback: CallbackQuery):
    user_id = callback.from_user.id
    data_parts = callback.data.split("|")
    
    series_id = data_parts[1]
    msg_id = int(data_parts[2])
    
    user_data = await get_user(user_id)
    if not user_data:
        await register_user(user_id)
        user_data = await get_user(user_id)

    has_access = False
    
    if user_data.get("is_vip", False):
        has_access = True
    elif series_id in user_data.get("purchased_series", []):
        has_access = True

    # Popup (show_alert) အစား ရိုးရိုး Message ပို့မည့်အပိုင်း
    if not has_access:
        alert_text = (
            "🔒 <b>ဤကားကို ကြည့်ရှုရန် ဝယ်ယူရန် လိုအပ်ပါသည်။</b>\n\n"
            "တစ်သက်တာ VIP (သို့) တစ်ကားချင်း ဝယ်ယူရန် @NaJu_New သို့ ဆက်သွယ်ပါ။\n\n"
            "💳 ဝယ်ယူရန်အတွက် အောက်ပါ သင့်ရဲ့ ID ကို Admin ထံ Copy ကူးပြီး ပို့ပေးပါ:\n\n"
            f"သင့်ရဲ့ ID 👉 <code>{user_id}</code>" 
        )
        await callback.answer() 
        # Markdown အစား HTML ကို ပြောင်းသုံးလိုက်ပါ
        await bot.send_message(chat_id=user_id, text=alert_text, parse_mode="HTML")
        return

    await callback.answer("✅ ဗီဒီယို ပို့ပေးနေပါသည်...")
    
    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=STORAGE_CHANNEL_ID,
            message_id=msg_id,
            protect_content=True
        )
    except Exception as e:
        await bot.send_message(user_id, "⚠️ ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ။ Admin ကို ဆက်သွယ်ပါ။")
        logging.error(f"Error copying message {msg_id}: {e}")

# ==========================================
# ၅။ Admin Commands (Content & User Management)
# ==========================================
@dp.message(Command("newseries"))
async def add_new_series(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args:
        await message.answer("✍️ အသုံးပြုနည်း: `/newseries [series_id] [ခေါင်းစဉ်]`", parse_mode="Markdown")
        return
    args = command.args.split(maxsplit=1)
    if len(args) < 2: return await message.answer("⚠️ ခေါင်းစဉ် ထည့်ရန် ကျန်နေပါသည်။")
    series_id, title = args[0], args[1]
    if await series_col.find_one({"series_id": series_id}):
        return await message.answer("⚠️ ဤ ID ရှိပြီးသားပါ။")
    await series_col.insert_one({"series_id": series_id, "title": title, "episodes": []})
    await message.answer(f"✅ `/addep {series_id} [Message_ID] [အပိုင်းအမည်]` ဖြင့် အပိုင်းများ ထပ်ထည့်ပါ။", parse_mode="Markdown")

@dp.message(Command("addep"))
async def add_episode(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args: return await message.answer("✍️ အသုံးပြုနည်း: `/addep [series_id] [message_id] [အပိုင်းအမည်]`", parse_mode="Markdown")
    args = command.args.split(maxsplit=2)
    if len(args) < 3 or not args[1].isdigit(): return await message.answer("⚠️ အချက်အလက် မှားယွင်းနေပါသည်။")
    series_id, msg_id, ep_name = args[0], args[1], args[2]
    res = await series_col.update_one({"series_id": series_id}, {"$push": {"episodes": {"name": ep_name, "msg_id": int(msg_id)}}})
    if res.modified_count > 0: await message.answer(f"✅ အောင်မြင်ပါသည်။")

@dp.message(Command("addvip"))
async def add_vip(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args or not command.args.isdigit(): return
    target_id = int(command.args)
    await register_user(target_id)
    await users_col.update_one({"user_id": target_id}, {"$set": {"is_vip": True}})
    await message.answer(f"✅ User `{target_id}` ကို VIP ပေးလိုက်ပါပြီ။", parse_mode="Markdown")

@dp.message(Command("addseries"))
async def add_series(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id, series_id = int(command.args.split()[0]), command.args.split()[1]
        await register_user(target_id)
        await users_col.update_one({"user_id": target_id}, {"$addToSet": {"purchased_series": series_id}})
        await message.answer(f"✅ ဖွင့်ပေးလိုက်ပါပြီ။")
    except: pass

@dp.message(Command("remove"))
async def remove_access(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args or not command.args.isdigit(): return
    target_id = int(command.args)
    await users_col.update_one({"user_id": target_id}, {"$set": {"is_vip": False, "purchased_series": []}})
    await message.answer(f"❌ ရုပ်သိမ်းလိုက်ပါပြီ။")

@dp.message(Command("check"))
async def check_user(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    if not command.args or not command.args.isdigit(): return
    target_id = int(command.args)
    user = await get_user(target_id)
    if not user: return await message.answer("⚠️ Database တွင် မရှိပါ။")
    is_vip = "✅ Yes" if user.get("is_vip") else "❌ No"
    purchased = ", ".join(user.get("purchased_series", [])) or "ဘာမှ မဝယ်ထားပါ"
    await message.answer(f"🔍 **ID:** `{target_id}`\n👑 **VIP:** {is_vip}\n🎬 **ဝယ်ထားသည်များ:** {purchased}", parse_mode="Markdown")

    # /editname [series_id] [msg_id] [နာမည်အသစ်]
@dp.message(Command("editname"))
async def edit_ep_name(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    
    if not command.args:
        await message.answer("✍️ အသုံးပြုနည်း: `/editname [series_id] [msg_id] [နာမည်အသစ်]`\n\nဥပမာ: `/editname ninja_scroll 105 00. Ninja Scroll (1993)`", parse_mode="HTML")
        return

    args = command.args.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("⚠️ အချက်အလက် မပြည့်စုံပါ။ (Series ID, Message ID နှင့် နာမည်အသစ် အားလုံးထည့်ပါ)")
        return

    series_id, msg_id_str, new_name = args[0], args[1], args[2]
    
    if not msg_id_str.isdigit():
        await message.answer("⚠️ Message ID သည် ဂဏန်းသာ ဖြစ်ရပါမည်။")
        return

    msg_id = int(msg_id_str)

    # Database ထဲရှိ သက်ဆိုင်ရာ အပိုင်း၏ နာမည်ကို သွားရောက် ပြင်ဆင်ခြင်း
    res = await series_col.update_one(
        {"series_id": series_id, "episodes.msg_id": msg_id},
        {"$set": {"episodes.$.name": new_name}}
    )

    if res.modified_count > 0:
        await message.answer(f"✅ နာမည်ကို <b>{new_name}</b> သို့ အောင်မြင်စွာ ပြောင်းလဲလိုက်ပါပြီ။", parse_mode="HTML")
    else:
        await message.answer("❌ ရှာမတွေ့ပါ။ Series ID နှင့် Message ID မှန်ကန်မှုရှိမရှိ စစ်ဆေးပါ။")

        # /setorder [series_id] [msg_id] [စဉ်နံပါတ်]
@dp.message(Command("setorder"))
async def set_episode_order(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    
    if not command.args:
        await message.answer("✍️ အသုံးပြုနည်း: `/setorder [series_id] [msg_id] [စဉ်နံပါတ်]`\n\nဥပမာ: `/setorder ninja_scroll 105 1`", parse_mode="HTML")
        return

    args = command.args.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("⚠️ အချက်အလက် မပြည့်စုံပါ။")
        return

    series_id, msg_id_str, order_str = args[0], args[1], args[2]
    
    if not msg_id_str.isdigit() or not order_str.isdigit():
        await message.answer("⚠️ Message ID နှင့် စဉ်နံပါတ်တို့သည် ဂဏန်းများသာ ဖြစ်ရပါမည်။")
        return

    msg_id = int(msg_id_str)
    order_num = int(order_str)

    # Database ထဲတွင် လျှို့ဝှက် Order နံပါတ် သွားထည့်မည်
    res = await series_col.update_one(
        {"series_id": series_id, "episodes.msg_id": msg_id},
        {"$set": {"episodes.$.order": order_num}}
    )

    if res.modified_count > 0:
        await message.answer(f"✅ ထိုအပိုင်းကို နံပါတ်စဉ် <b>{order_num}</b> သို့ ရွှေ့လိုက်ပါပြီ။ (နာမည်ပြောင်းသွားမည် မဟုတ်ပါ) 💯", parse_mode="HTML")
    else:
        await message.answer("❌ ရှာမတွေ့ပါ။ Series ID နှင့် Message ID မှန်ကန်မှုရှိမရှိ စစ်ဆေးပါ။")

# ==========================================
# 🌟 အလွယ်တကူ အထက်/အောက် ရွှေ့နိုင်မည့် Feature
# ==========================================
@dp.message(Command("sortep"))
async def sort_episodes_menu(message: Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID: return
    
    if not command.args:
        await message.answer("✍️ အသုံးပြုနည်း: `/sortep [series_id]`\n\nဥပမာ: `/sortep ninja_scroll`", parse_mode="HTML")
        return

    series_id = command.args.strip()
    series_info = await series_col.find_one({"series_id": series_id})
    
    if not series_info or not series_info.get("episodes"):
        await message.answer("⚠️ ဇာတ်ကားရှာမတွေ့ပါ (သို့) အပိုင်းများ မရှိသေးပါ။")
        return

    episodes = series_info["episodes"]

    # လက်ရှိ အစီအစဉ်အတိုင်း အရင်စီမည်
    def sort_logic(ep):
        return (ep.get('order', 9999), [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', ep['name'])])
    episodes.sort(key=sort_logic)

    keyboard_buttons = []
    for ep in episodes:
        row = [
            InlineKeyboardButton(text=f"{ep['name']}", callback_data="noop"),
            InlineKeyboardButton(text="⬆️", callback_data=f"mv|u|{series_id}|{ep['msg_id']}"),
            InlineKeyboardButton(text="⬇️", callback_data=f"mv|d|{series_id}|{ep['msg_id']}")
        ]
        keyboard_buttons.append(row)

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await message.answer(f"↕️ <b>{series_info['title']}</b> ၏ အပိုင်းများကို အထက်/အောက် ရွှေ့ရန် ခလုတ်များကို နှိပ်ပါ။", reply_markup=reply_markup, parse_mode="HTML")

# ခလုတ်အလွတ် (နာမည်) ကို နှိပ်မိပါက Loading မဖြစ်အောင် တားခြင်း
@dp.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await callback.answer()

# ⬆️ ⬇️ ခလုတ်များကို နှိပ်သောအခါ အလုပ်လုပ်မည့်စနစ်
@dp.callback_query(F.data.startswith("mv|"))
async def handle_move_episode(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    parts = callback.data.split("|")
    direction = parts[1]
    series_id = parts[2]
    msg_id = int(parts[3])

    series_info = await series_col.find_one({"series_id": series_id})
    if not series_info: 
        return await callback.answer("⚠️ Error: Series မတွေ့ပါ။", show_alert=True)

    episodes = series_info.get("episodes", [])
    
    def sort_logic(ep):
        return (ep.get('order', 9999), [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', ep['name'])])
    episodes.sort(key=sort_logic)

    # ရွှေ့ချင်တဲ့ အပိုင်းရဲ့ လက်ရှိ Index ကို ရှာမည်
    target_idx = next((i for i, ep in enumerate(episodes) if ep['msg_id'] == msg_id), None)
    
    if target_idx is None:
        return await callback.answer("⚠️ အပိုင်းကို ရှာမတွေ့ပါ။", show_alert=True)

    # အထက်/အောက် နေရာချိန်းမည်
    if direction == "u" and target_idx > 0:
        episodes[target_idx], episodes[target_idx - 1] = episodes[target_idx - 1], episodes[target_idx]
    elif direction == "d" and target_idx < len(episodes) - 1:
        episodes[target_idx], episodes[target_idx + 1] = episodes[target_idx + 1], episodes[target_idx]
    else:
        return await callback.answer("အစွန်းရောက်နေပါပြီ (ရွှေ့၍ မရတော့ပါ)", show_alert=False)

    # အသစ်ဖြစ်သွားတဲ့ အစီအစဉ်အတိုင်း Database ထဲမှ order နံပါတ်တွေကို Auto ပြန်စီပေးမည်
    for idx, ep in enumerate(episodes):
        ep['order'] = idx + 1

    # Database ထဲ Save မည်
    await series_col.update_one({"series_id": series_id}, {"$set": {"episodes": episodes}})

    # ခလုတ်အသစ်ပြန်ဆောက်ပြီး Message ကို ပြင်မည် (Edit လုပ်မည်)
    keyboard_buttons = []
    for ep in episodes:
        row = [
            InlineKeyboardButton(text=f"{ep['name']}", callback_data="noop"),
            InlineKeyboardButton(text="⬆️", callback_data=f"mv|u|{series_id}|{ep['msg_id']}"),
            InlineKeyboardButton(text="⬇️", callback_data=f"mv|d|{series_id}|{ep['msg_id']}")
        ]
        keyboard_buttons.append(row)

    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback.message.edit_reply_markup(reply_markup=reply_markup)
    await callback.answer("✅ နေရာရွှေ့ပြီးပါပြီ")

    # ==========================================
# 🌟 အလွယ်တကူ Auto-Add လုပ်မည့်စနစ် (Forward ပို့၍ ထည့်ခြင်း)
# ==========================================
@dp.message(F.forward_origin)
async def handle_forwarded_video(message: Message):
    if message.from_user.id != ADMIN_ID: return
    
    origin = message.forward_origin
    
    # Storage Channel ကနေ Forward လုပ်လာတာ ဟုတ်မဟုတ် စစ်ဆေးခြင်း
    if origin.type == "channel" and origin.chat.id == STORAGE_CHANNEL_ID:
        msg_id = origin.message_id
        
        # Caption မပါရင် 'အပိုင်းသစ်' လို့ မှတ်မည်၊ ပါရင် ပါတဲ့စာကို ယူမည် (ဥပမာ - Ninja Scroll 1)
        caption = message.caption if message.caption else f"Episode (ID: {msg_id})"
        
        # Database ထဲမှာရှိတဲ့ Series အကုန်လုံးကို ဆွဲထုတ်မည်
        all_series = await series_col.find().to_list(length=50) 
        
        if not all_series:
            await message.reply("⚠️ Database ထဲမှာ Series မရှိသေးပါ။ အရင်ဆုံး /newseries ဖြင့် ဖန်တီးပါ။")
            return
            
        # Series တွေကို ရွေးချယ်စရာ ခလုတ် (Inline Keyboard) အဖြစ် ပြောင်းမည်
        kb = []
        for s in all_series:
            # callback data ကို autoadd|series_id|msg_id ပုံစံ သိမ်းမည်
            cb_data = f"autoadd|{s['series_id']}|{msg_id}"
            kb.append([InlineKeyboardButton(text=s['title'], callback_data=cb_data)])
        
        reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)
        
        # Admin ထံ ရွေးချယ်ခိုင်းမည်
        await message.reply(
            f"📥 <b>ဗီဒီယို ဖမ်းယူရရှိပါသည်</b>\n"
            f"ID: <code>{msg_id}</code>\n"
            f"Caption: {caption}\n\n"
            f"👇 <b>မည်သည့် Series ထဲသို့ ထည့်မည်နည်း?</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

# ခလုတ်နှိပ်လိုက်သောအခါ Database ထဲသို့ ထည့်သွင်းမည့် အပိုင်း
@dp.callback_query(F.data.startswith("autoadd|"))
async def process_autoadd(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    # Data ခွဲထုတ်ခြင်း (ဥပမာ - autoadd, ninja_scroll, 105)
    _, series_id, msg_id_str = callback.data.split("|")
    msg_id = int(msg_id_str)
    
    # မူလ Message ထဲမှ Caption နာမည်ကို ပြန်ရှာခြင်း
    text_lines = callback.message.text.split("\n")
    caption = "အပိုင်းသစ်"
    for line in text_lines:
        if line.startswith("Caption: "):
            caption = line.replace("Caption: ", "").strip()
            break
            
    # Database ထဲသို့ ထည့်သွင်းခြင်း
    res = await series_col.update_one(
        {"series_id": series_id},
        {"$push": {"episodes": {"name": caption, "msg_id": msg_id}}}
    )
    
    if res.modified_count > 0:
        await callback.message.edit_text(
            f"✅ <b>{caption}</b> ကို <code>{series_id}</code> ထဲသို့ အောင်မြင်စွာ ထည့်သွင်းပြီးပါပြီ။", 
            parse_mode="HTML"
        )
    else:
        await callback.answer("❌ Error: Series ကို Database တွင် ရှာမတွေ့ပါ။", show_alert=True)

# ==========================================
# ၆။ Bot ကို စတင် Run မည့် အပိုင်း
# ==========================================
async def main():
    print("🚀 Version 3.0 Bot is starting securely...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

# ==========================================
# ၇။ Menu Commands များ ဖန်တီးသည့် အပိုင်း (အသစ် ထပ်တိုး)
# ==========================================
async def setup_bot_commands(bot: Bot):
    # (က) ရိုးရိုး User များအတွက် မြင်ရမည့် Command များ
    user_commands = [
        BotCommand(command="start", description="Bot ကို စတင်ရန်"),
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    # (ခ) Admin သီးသန့် မြင်ရမည့် Command များ (သင့် Chat ထဲမှာပဲ ပေါ်ပါမည်)
    admin_commands = [
        BotCommand(command="start", description="Bot ကို စတင်ရန်"),
        BotCommand(command="newseries", description="ဇာတ်ကား/Series အသစ် ဖန်တီးရန်"),
        BotCommand(command="addep", description="အပိုင်း (Episode) အသစ် ထပ်ထည့်ရန်"),
        BotCommand(command="sortep", description="အပိုင်းများကို အထက်အောက် အလွယ်တကူရွှေ့ရန်"), # ယခုအသစ် ထပ်တိုးသည့်လိုင်း
        BotCommand(command="addvip", description="User ကို Lifetime VIP ပေးရန်"),
        BotCommand(command="addseries", description="ကားတစ်ကားချင်း ကြည့်ခွင့်ပေးရန်"),
        BotCommand(command="check", description="User ၏ အချက်အလက်ကို စစ်ဆေးရန်"),
        BotCommand(command="remove", description="User ၏ ကြည့်ခွင့်များကို ရုပ်သိမ်းရန်"),
    ]
    # ADMIN_ID ကို သုံးပြီး Admin ရဲ့ Chat မှာပဲ ဒီ Command တွေပေါ်အောင် သတ်မှတ်ခြင်း
    await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))

# ==========================================
# ၈။ Bot ကို စတင် Run မည့် အပိုင်း (Cloud 24/7 အတွက်)
# ==========================================
async def health_check(request):
    return web.Response(text="Bot is running 24/7 on Cloud!")

async def main():
    print("🚀 Cloud Version Bot is starting...")
    await setup_bot_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Render အတွက် Web Server အသေးလေး ဖန်တီးခြင်း
    app = web.Application()
    app.router.add_get('/', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Web server is running on port {port}")

    # Bot စတင်ခြင်း
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
