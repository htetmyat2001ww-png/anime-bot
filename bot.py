import telebot
import json
import os
import random
import time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# --- CONFIGURATION ---
TOKEN = '8921879251:AAHTKOkb_rxMBFYp8xa5-gUO7SWeMRPTkTE'
ADMIN_ID = 7940553702
MAIN_GP_ID = -1002755679723  # Main Group ID for restriction check

# --- MONGODB CONNECTION ---
# Railway MongoDB Connection String (Fixed: Mongodb -> mongodb)
MONGO_URI = "mongodb://mongo:KdoRDeJCYnsWLjVxiPDwrUNczZwqBIdM@hayabusa.proxy.rlwy.net:27402"
client = MongoClient(MONGO_URI)
db = client['character_hunter_db']

# Collections Setup
cards_col = db['cards']
inventories_col = db['inventories']
favorites_col = db['favorites']
system_col = db['system_settings']

bot = telebot.TeleBot(TOKEN)
admin_session = {}
user_cooldowns = {}      
active_hunt_sessions = {} 

# Spawn System State
group_message_counters = {}  # {chat_id: count}
active_spawns = {}           # {chat_id: {"card_id": id, "name": name, "message_id": id}}

MAIN_CH_LINK = "https://t.me/character_hunter_channel"
MAIN_GP_LINK = "https://t.me/character_hunter_Gp"

RARITIES = {
    "supreme": "🪞 Supreme",
    "catapharct": "✨ Catapharct",
    "crossverse": "⚡ Crossverse",
    "divine": "⚜️ Divine",
    "mystical": "💮 Mystical",
    "legendary": "🟡 Legendary",
    "rare": "🟠 Rare",
    "uncommon": "🟣 Uncommon",
    "common": "🔵 Common"
}

HUNT_ANIMATIONS = [
    "🔍 Searching the bushes carefully...",
    "👣 Following the fresh tracks left behind...",
    "🎯 Aiming carefully from the shadows...",
    "✨ Spotting a bright magical aura ahead...",
    "🎒 Preparing the special capture items...",
    "🤫 Walking quietly so they don't escape..."
]

# --- MONGODB HELPER FUNCTIONS ---
def get_next_card_id():
    counter = system_col.find_one_and_update(
        {"_id": "card_id_counter"},
        {"$inc": {"sequence_value": 1}},
        upsert=True,
        return_document=True
    )
    if "sequence_value" not in counter:
        system_col.update_one({"_id": "card_id_counter"}, {"$set": {"sequence_value": 100}})
        return 100
    return counter["sequence_value"]

# Fixed: Line 77 IndexError out of range Crash completely fixed
def parse_name_from_text(text):
    if text and "NAME" in text.upper():
        for line in text.split('\n'):
            if "NAME" in line.upper() and ":" in line:
                try:
                    return line.split(':', 1)[1].strip()
                except IndexError:
                    continue
    return None

def check_chat_restrictions(message):
    if message.from_user.id == ADMIN_ID:
        return True
        
    try:
        member = bot.get_chat_member(MAIN_GP_ID, message.from_user.id)
        if member.status in ['left', 'kicked']:
            raise Exception("Not a member")
    except Exception:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text="👥 Join Main Group", url=MAIN_GP_LINK))
        
        restriction_text = (
            "❌ **Access Denied!**\n\n"
            "This bot can only be used by members of our Main Group.\n"
            "You must join the Main Group first to use the bot anywhere else!"
        )
        bot.reply_to(message, restriction_text, reply_markup=markup, parse_mode="Markdown")
        return False
        
    if message.chat.type == 'private' and message.text.split()[0] not in ['/start', '/help']:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text="👥 Go to Main Group", url=MAIN_GP_LINK))
        bot.reply_to(message, "❌ **This command can only be used inside groups!**", reply_markup=markup, parse_mode="Markdown")
        return False
        
    return True

def get_help_text():
    return (
        "🤖 **Character Hunter Bot Command List**\n\n"
        "Here are the available commands you can use↴\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 /hunt - Search and capture new character cards\n"
        "🧃 /hbug [name] - Claim spawned character in chat\n"
        "🗂 /hview - View your owned cards filtered by Rarity\n"
        "🕋 /collection - Browse all registered cards in the bot\n"
        "🗃 /invan - View your collection profile and inventory pages\n"
        "🔍 /hsee [Card_ID] - Check card profile and top 10 hunters\n"
        "❤️ /hfav [Card_ID] - Set a card as your main favorite profile look\n"
        "🤝 /htrade - Trade cards with another user (Reply to user)\n"
        "🎁 /hgift [Card_ID] - Gift a card to another user (Reply to user)\n"
        "🏆 /gtop - View top 10 card owners in this group\n"
        "🌍 /gbtop - View global leaderboard top 10 hunters\n"
        "🔒 /exit - Force cancel your current active hunt session\n"
        "ℹ️ /help - Show this manual and command list\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

@bot.message_handler(commands=['start'])
def cmd_start(message):
    if not check_chat_restrictions(message): return
    bot_username = bot.get_me().username
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(text="📢 Join Main Channel", url=MAIN_CH_LINK),
        InlineKeyboardButton(text="👥 Join Main Group", url=MAIN_GP_LINK),
        InlineKeyboardButton(text="➕ Add Bot to Group", url=f"https://t.me/{bot_username}?startgroup=true"),
        InlineKeyboardButton(text="ℹ️ Help Manual", callback_data=f"help_menu_{message.from_user.id}")
    )
    
    welcome_text = (
        f"👋 **Welcome to Character Hunter World!**\n\n"
        f"Hello {message.from_user.first_name}! Hunt, collect, trade, and build your ultimate "
        f"character legendary inventory deck right here!\n\n"
        f"Press the buttons below to join our community or explore the commands!"
    )
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def cmd_help(message):
    if not check_chat_restrictions(message): return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="👥 Join Main Group", url=MAIN_GP_LINK))
    bot.reply_to(message, get_help_text(), reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('help_menu_'))
def handle_help_callback(call):
    owner_id = int(call.data.split('_')[2])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "❌ This is not your menu!", show_alert=True)
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="👥 Join Main Group", url=MAIN_GP_LINK))
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_help_text(), reply_markup=markup, parse_mode="Markdown")


# --- SPAWN CHARACTER SYSTEM (80 MESSAGES) ---
@bot.message_handler(commands=['hbug'])
def cmd_hbug(message):
    if not check_chat_restrictions(message): return
    chat_id = message.chat.id
    user_id = message.from_user.id
    username = message.from_user.username if message.from_user.username else message.from_user.first_name

    if chat_id not in active_spawns:
        bot.reply_to(message, "❌ There is no active spawned character in this chat right now!")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "⚠️ **Usage:** `/hbug [Character Name]`", parse_mode="Markdown")
        return

    user_answer = args[1].strip().lower()
    spawned_card = active_spawns[chat_id]

    if user_answer == spawned_card["name"].lower():
        target_card = cards_col.find_one({"id": spawned_card["card_id"]})
        
        if target_card:
            cards_col.update_one(
                {"id": target_card["id"]},
                {
                    "$inc": {
                        "hunt_count": 1,
                        f"hunters.{username}": 1
                    }
                }
            )
            
            collection_name = target_card.get('collection', target_card['name'] + " Collection")
            inventories_col.update_one(
                {"_id": str(user_id)},
                {
                    "$push": {
                        "cards": {
                            "id": target_card["id"], 
                            "name": target_card["name"], 
                            "rarity": target_card["rarity"], 
                            "collection": collection_name, 
                            "timestamp": time.time()
                        }
                    }
                },
                upsert=True
            )

            del active_spawns[chat_id]

            congrats_text = (
                f"🎉 **CONGRATULATIONS!** 🎉\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✨ <a href='tg://user?id={user_id}'>{message.from_user.first_name}</a> answered correctly and successfully claimed the character!\n\n"
                f"🃏 **CARD DETAILS** 🃏\n"
                f"• **Name:** {target_card['name']}\n"
                f"• **Rarity:** {target_card['rarity']}\n"
                f"• **ID:** <code>{target_card['id']}</code>\n"
                f"• **Collection:** {collection_name}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📥 The character has been saved directly to your inventory (/invan)."
            )
            bot.send_message(chat_id, congrats_text, parse_mode="HTML", reply_to_message_id=message.message_id)
        else:
            del active_spawns[chat_id]
            bot.reply_to(message, "❌ An error occurred. The character data could not be found.")
    else:
        bot.reply_to(message, "❌ Wrong name! Try checking your spelling and try again.")


# --- TOP LEADERBOARDS ---
@bot.message_handler(commands=['gtop'])
def cmd_gtop(message):
    if not check_chat_restrictions(message): return
    if message.chat.type == 'private':
        bot.reply_to(message, "❌ This command can only be used inside groups.")
        return
        
    status_msg = bot.reply_to(message, "📊 Scanning group leaderboard... Please wait.")
    group_members_cards = []
    
    all_inventories = inventories_col.find()
    
    for user_doc in all_inventories:
        user_id = user_doc["_id"]
        cards = user_doc.get("cards", [])
        try:
            member = bot.get_chat_member(message.chat.id, int(user_id))
            if member and member.status not in ['left', 'kicked']:
                name = member.user.username if member.user.username else member.user.first_name
                group_members_cards.append((name, len(cards)))
        except:
            continue
            
    group_members_cards.sort(key=lambda x: x[1], reverse=True)
    top_10 = group_members_cards[:10]
    
    leaderboard_text = "🏆 **Group Top 10 Card Owners** 🏆\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (name, count) in enumerate(top_10, 1):
        leaderboard_text += f"{i}. 🎐 {name} — ({count} Cards)\n"
        
    for i in range(len(top_10) + 1, 11):
        leaderboard_text += f"{i}. 🎐 Empty Slot\n"
        
    leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━"
    bot.edit_message_text(leaderboard_text, chat_id=status_msg.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")

@bot.message_handler(commands=['gbtop'])
def cmd_gbtop(message):
    if not check_chat_restrictions(message): return
    
    global_list = []
    caller_id = str(message.from_user.id)
    caller_name = message.from_user.username if message.from_user.username else message.from_user.first_name
    
    all_inventories = inventories_col.find()
    for user_doc in all_inventories:
        global_list.append((user_doc["_id"], len(user_doc.get("cards", []))))
        
    global_list.sort(key=lambda x: x[1], reverse=True)
    
    caller_rank = "Unranked"
    for idx, (uid, _) in enumerate(global_list, 1):
        if uid == caller_id:
            caller_rank = f"#{idx}"
            break
            
    leaderboard_text = "🌍 **Global Top Hunter's** 🏆\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    for i in range(10):
        if i < len(global_list):
            uid, count = global_list[i]
            try:
                user_info = bot.get_chat(int(uid))
                name = user_info.username if user_info.username else user_info.first_name
            except:
                name = f"User {uid}"
            leaderboard_text += f"🎐 {name} — ({count} Cards)\n"
        else:
            leaderboard_text += "🎐 Empty Slot\n"
            
    leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━\n"
    leaderboard_text += f"👤 Profile: {caller_name} | Global Rank: ({caller_rank})"
    
    bot.reply_to(message, leaderboard_text, parse_mode="Markdown")


# --- TRADING & GIFT SYSTEMS ---
@bot.message_handler(commands=['htrade'])
def cmd_htrade(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    
    if len(args) < 2 or not message.reply_to_message:
        usage_text = (
            "🤝 **How to use /htrade command**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "To trade cards with another user, follow these steps:\n\n"
            "1. Reply to the user's message you want to trade with.\n"
            "2. Type: `/htrade [Your_Card_ID] [Their_Card_ID]`\n\n"
            "💡 *Example:* `/htrade 102 105`"
        )
        bot.reply_to(message, usage_text, parse_mode="Markdown")
        return
        
    bot.reply_to(message, "⚙️ Trading system processing...")

@bot.message_handler(commands=['hgift'])
def cmd_hgift(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    
    if len(args) < 2 or not message.reply_to_message:
        usage_text = (
            "🎁 **How to use /hgift command**\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "To send a card as a gift to another user:\n\n"
            "1. Reply to that user's message.\n"
            "2. Type: `/hgift [Your_Card_ID]`\n\n"
            "💡 *Example:* `/hgift 102`"
        )
        bot.reply_to(message, usage_text, parse_mode="Markdown")
        return

    bot.reply_to(message, "⚙️ Gifting system processing...")


# --- ADMIN CONTROLS ---
@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if message.from_user.id != ADMIN_ID: return
    total_users = inventories_col.count_documents({})
    total_cards = cards_col.count_documents({})
    
    stats_text = (
        "📊 **Bot Global Statistics (Admin Only)**\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Active Users: `{total_users}`\n"
        f"🃏 Total Registered Cards: `{total_cards}`\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, stats_text, parse_mode="Markdown")

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ **Usage:** Please reply to the Message/Photo/Video you want to broadcast with `/broadcast`", parse_mode="Markdown")
        return
        
    user_ids = [doc["_id"] for doc in inventories_col.find({}, {"_id": 1})]
    
    if not user_ids:
        bot.reply_to(message, "❌ No users found in the database to broadcast.")
        return

    sent_count = 0
    fail_count = 0
    status_msg = bot.reply_to(message, f"📢 Smart Broadcast started to {len(user_ids)} users... Please wait.")
    
    replied_msg = message.reply_to_message
    for uid in user_ids:
        try:
            bot.copy_message(chat_id=int(uid), from_chat_id=replied_msg.chat.id, message_id=replied_msg.message_id)
            sent_count += 1
            time.sleep(0.1)
        except:
            fail_count += 1

    bot.edit_message_text(f"✅ **Broadcast Completed!**\n\n🟢 Successfully Sent: `{sent_count}`\n🔴 Failed/Blocked: `{fail_count}`", chat_id=status_msg.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")


# --- ADMIN INSTANT SPAWN SYSTEM ---
@bot.message_handler(commands=['spawn'])
def cmd_spawn(message):
    if message.from_user.id != ADMIN_ID: return
    chat_id = message.chat.id
    
    total_cards = cards_col.count_documents({})
    if total_cards == 0:
        bot.reply_to(message, "❌ No cards available in the database.")
        return
        
    args = message.text.split()
    target_card = None
    
    if len(args) > 1:
        try:
            search_id = int(args[1])
            target_card = cards_col.find_one({"id": search_id})
            if not target_card:
                bot.reply_to(message, f"❌ Card ID {search_id} not found.")
                return
        except ValueError:
            bot.reply_to(message, "⚠️ Invalid ID format. Use `/spawn [id]`")
            return
    else:
        all_cards = list(cards_col.find())
        target_card = random.choice(all_cards)
        
    spawn_text = (
        "🍭 ᴀ ᴄʜᴀʀᴀᴄ提ᴇʀ ʜᴀs sᴘᴀᴡɴᴇᴅ ɪɴ ᴛʜᴇ ᴄʜᴀᴛ! 🎇\n"
        "ᴀ提ᴅ ᴛʜɪs ᴄʜါရပ္တရာ ကို တူ ရ သွင် 🧃 /hbug  name"
    )
    
    try:
        sent_spawn = bot.send_photo(chat_id, target_card["photo_id"], caption=spawn_text)
        active_spawns[chat_id] = {
            "card_id": target_card["id"],
            "name": target_card["name"],
            "message_id": sent_spawn.message_id
        }
    except Exception as e:
        bot.reply_to(message, f"❌ Failed to spawn: {e}")


# --- ADMIN CARD ADDING LOGIC ---
@bot.message_handler(func=lambda msg: msg.from_user.id == ADMIN_ID and (msg.forward_date is not None or msg.forward_from is not None or msg.forward_from_chat is not None), content_types=['photo', 'text'])
def handle_forwarded_messages(message):
    user_id = message.from_user.id
    if user_id not in admin_session:
        admin_session[user_id] = {"photo_id": None, "name": None, "button_shown": False}
        
    has_new_data = False
    if message.content_type == 'photo':
        admin_session[user_id]["photo_id"] = message.photo[-1].file_id
        has_new_data = True
        if message.caption:
            card_name = parse_name_from_text(message.caption)
            if card_name:
                admin_session[user_id]["name"] = card_name
    elif message.content_type == 'text':
        card_name = parse_name_from_text(message.text)
        if card_name:
            admin_session[user_id]["name"] = card_name
            has_new_data = True
        else:
            return

    session = admin_session[user_id]
    if session["photo_id"] and session["name"]:
        if not session["button_shown"]:
            session["button_shown"] = True
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = [InlineKeyboardButton(text=v, callback_data=f"set_rarity_{k}") for k, v in RARITIES.items()]
            markup.add(*buttons)
            bot.send_message(user_id, f"📊 **Card data received.**\n📛 *NAME:* {session['name']}\n\nPlease choose Rarity:", reply_markup=markup, parse_mode="Markdown", reply_to_message_id=message.message_id)
    else:
        if has_new_data:
            if not session["photo_id"]:
                bot.send_message(user_id, "⚠️ Please forward the card *IMAGE*.", parse_mode="Markdown")
            elif not session["name"]:
                bot.send_message(user_id, "⚠️ Please forward the text containing *NAME :*.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rarity_'))
def save_card_to_db(call):
    user_id = call.from_user.id
    rarity_key = call.data.split('_')[2]
    rarity_name = RARITIES[rarity_key]
    
    if user_id not in admin_session or not admin_session[user_id]["name"]:
        bot.answer_callback_query(call.id, "❌ Session expired.")
        return
        
    current_id = get_next_card_id()
    new_card = {
        "id": current_id,
        "name": admin_session[user_id]["name"],
        "rarity": rarity_name,
        "collection": admin_session[user_id]["name"] + " Collection",
        "photo_id": admin_session[user_id]["photo_id"],
        "hunt_count": 0,
        "hunters": {}
    }
    cards_col.insert_one(new_card)
    
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    bot.send_message(user_id, f"✅ **Successfully Added!**\n🆔 ID: {current_id}\n📛 Name: {new_card['name']}\n💎 Rarity: {rarity_name}")
    del admin_session[user_id]
    bot.answer_callback_query(call.id, "Saved!")


# --- CARD VIEWING LOGIC (/hsee) ---
def get_card_profile_text(card):
    collection_name = card.get('collection', card['name'] + " Collection")
    return (
        f"🍄 ━  𝗖𝗛𝗔𝗥𝗔𝗖𝗧𝗘𝗥 𝗣𝗥𝗢𝗙𝗜𝗟𝗘  ━ 🍄\n"
        f"───────────────────────\n"
        f"👤 <b><b>𝗡𝗮𝗺𝗲 ::</b></b>  {card['name']}\n\n"
        f"✨ <b><b>𝗥𝗮𝗿𝗶𝘁𝘆 ::</b></b>  {card['rarity']}\n\n"
        f"🏷️ <b><b>𝗜𝗗 ::</b></b>  {card['id']}\n\n"
        f"🕋 <b><b>𝗖𝗼𝗹𝗹𝗲𝗰𝘁𝗶𝗼𝗻 ::</b></b>  {collection_name}\n"
        f"───────────────────────\n"
        f"<b><b>𝗚𝗹𝗼𝗯𝗮𝗹 𝗛𝘂𝗻𝘁  𝗧𝗶𝗺𝗲𝘀 [ {card.get('hunt_count', 0)} ]</b></b>\n"
        f"───────────────────────"
    )

def get_top_hunters_text(card):
    hunters = card.get("hunters", {})
    sorted_hunters = sorted(hunters.items(), key=lambda x: x[1], reverse=True)[:10]
    hunter_lines = [f"🐙 : <b>{user}</b> - ({count}x)" if i < len(sorted_hunters) else "🐙 :" for i, (user, count) in enumerate(sorted_hunters + [("", 0)] * 10)][:10]
    return f"𝐓𝐎𝐏 10 𝐇𝐔𝐍𝐓𝐄𝐑𝐒 𝐎𝐅\n        𝐓𝐇𝐈𝐒 𝐂𝐇𝐀𝐑𝐀𝐂𝐓𝐄𝐑 \n───────────────────────\n{card['name']}\n---------------------------------------------------------\n" + "\n".join(hunter_lines) + "\n───────────────────────"

@bot.message_handler(commands=['hsee'])
def cmd_hsee(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Usage: /hsee [card_id]")
        return
    try: search_id = int(args[1])
    except ValueError: return
    
    target_card = cards_col.find_one({"id": search_id})
    if not target_card: return
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="🎯 Top 10 Hunters", callback_data=f"hsee_top_{search_id}_{message.from_user.id}"))
    bot.send_photo(message.chat.id, target_card["photo_id"], caption=get_card_profile_text(target_card), reply_markup=markup, parse_mode="HTML", reply_to_message_id=message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('hsee_'))
def handle_hsee_buttons(call):
    action, card_id, owner_id = call.data.split('_')[1:4]
    card_id, owner_id = int(card_id), int(owner_id)
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "❌ This menu belongs to someone else!", show_alert=True)
        return
        
    target_card = cards_col.find_one({"id": card_id})
    if not target_card: return
    
    markup = InlineKeyboardMarkup()
    if action == "top":
        new_caption = get_top_hunters_text(target_card)
        markup.add(InlineKeyboardButton(text="🔙 Close Top 10", callback_data=f"hsee_profile_{card_id}_{owner_id}"))
    else:
        new_caption = get_card_profile_text(target_card)
        markup.add(InlineKeyboardButton(text="🎯 Top 10 Hunters", callback_data=f"hsee_top_{card_id}_{owner_id}"))
    bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=new_caption, reply_markup=markup, parse_mode="HTML")


# --- ENGINE HUNT PROCESS ---
def execute_hunt_process(message, target_card, is_test=False):
    user_id = message.from_user.id
    collection_name = target_card.get('collection', target_card['name'] + " Collection")
    hunt_text = (
        f"🍄 𝗖𝗵𝗮𝗿𝗮𝗰𝘁𝗲𝗿 𝗛𝗮𝘀 𝗦𝗽𝗮𝘄𝗻 𝗛𝗲𝗿𝗲 🍄\n\n"
        f"<b>𝐋𝐞𝐭's 𝐇𝐮𝐧𝐭 𝐂𝐡𝐚𝐫𝐚𝐜𝐭𝐞ရ 𝐍𝐨𝐰  ◆◆◆</b>\n"
        f"───────────────────────\n"
        f"👤 <b><b>𝗡𝗮𝗺𝗲 ::</b></b>  {target_card['name']}\n"
        f"------------------------------------------\n"
        f"✨ <b><b>👑<b>𝗥𝗮𝗿𝗶𝘁𝘆 ::</b></b></b>  {target_card['rarity']}\n"
        f"------------------------------------------\n"
        f"🏷️ <b><b><b>𝗜display::</b></b></b>  {target_card['id']}\n"
        f"------------------------------------------\n"
        f"🕋 <b><b><b><b>𝗖𝗼𝗹𝗹𝗲𝗰𝘁𝗶𝗼𝗻::</b></b></b></b>  {collection_name}\n"
        f"───────────────────────"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="𝗛𝗨𝗡𝗧 ➽", callback_data=f"player_hunt_{target_card['id']}_{user_id}_{'1' if is_test else '0'}"),
               InlineKeyboardButton(text="𝗦𝗞𝗜評 ⟱", callback_data=f"player_skip_{target_card['id']}_{user_id}_{'1' if is_test else '0'}"))
    
    sent_msg = bot.send_photo(message.chat.id, target_card["photo_id"], caption=hunt_text, reply_markup=markup, parse_mode="HTML", reply_to_message_id=message.message_id)
    active_hunt_sessions[user_id] = {"chat_id": message.chat.id, "message_id": sent_msg.message_id, "hunting": False}

@bot.message_handler(commands=['hunt'])
def cmd_hunt(message):
    if not check_chat_restrictions(message): return
    user_id = message.from_user.id
    current_time = time.time()
    
    session = active_hunt_sessions.get(user_id)
    if session:
        if session.get("hunting") is True:
            bot.reply_to(message, "⚠️ **Hunting in progress!** Please wait until the process finishes.")
        else:
            bot.reply_to(message, "❌ **Your previous hunt session is not finished!**\nPlease choose HUNT or SKIP.\n\nUse /exit to cancel.", parse_mode="Markdown")
        return
        
    if user_id in user_cooldowns and current_time < user_cooldowns[user_id]:
        bot.reply_to(message, f"⏳ You are exhausted! Please wait {int(user_cooldowns[user_id] - current_time)}s before hunting again.")
        return
        
    all_cards = list(cards_col.find())
    if not all_cards: return
    execute_hunt_process(message, random.choice(all_cards), is_test=False)


# --- FORCE EXIT CURRENT HUNT SESSION ---
@bot.message_handler(commands=['exit'])
def cmd_exit_hunt(message):
    if not check_chat_restrictions(message): return
    user_id = message.from_user.id
    if active_hunt_sessions.get(user_id):
        session = active_hunt_sessions[user_id]
        try:
            bot.edit_message_reply_markup(chat_id=session["chat_id"], message_id=session["message_id"], reply_markup=None)
            bot.edit_message_caption(chat_id=session["chat_id"], message_id=session["message_id"], caption="🔒 <b>This hunt session has been locked and abandoned!</b>", parse_mode="HTML")
        except: pass
        
        del active_hunt_sessions[user_id]
        user_cooldowns[user_id] = time.time() + 30
        bot.reply_to(message, "🔒 **Session locked!**\n30 seconds cooldown started. You can /hunt after it expires.", parse_mode="Markdown")
    else:
        bot.reply_to(message, "ℹ️ You do not have an active hunt session right now.")


# --- CALLBACK HANDLER HUNT ACTIONS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('player_'))
def handle_hunt_actions(call):
    user_id = call.from_user.id
    username = call.from_user.username if call.from_user.username else call.from_user.first_name
    action, card_id, owner_id, is_test = call.data.split('_')[1:5]
    card_id, owner_id, is_test = int(card_id), int(owner_id), is_test == '1'
    
    if user_id != owner_id:
        bot.answer_callback_query(call.id, "❌ This menu belongs to someone else!", show_alert=True)
        return
        
    current_time = time.time()
    if not is_test and user_id in user_cooldowns and current_time < user_cooldowns[user_id]:
        bot.answer_callback_query(call.id, "⏳ Cooldown running!", show_alert=True)
        return

    target_card = cards_col.find_one({"id": card_id})
    if not target_card:
        if user_id in active_hunt_sessions: del active_hunt_sessions[user_id]
        return

    if action == "skip":
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        if user_id in active_hunt_sessions: del active_hunt_sessions[user_id]
        if not is_test: user_cooldowns[user_id] = current_time + 30
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"💨 <b>{username}</b> decided to skip <b>{target_card['name']}</b>!", parse_mode="HTML")
        return

    if action == "hunt":
        if user_id in active_hunt_sessions:
            active_hunt_sessions[user_id]["hunting"] = True
            
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        
        chosen_animations = random.sample(HUNT_ANIMATIONS, 3)
        for step in chosen_animations:
            try: bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"🏹 <b>{username} is hunting...</b>\n\n{step}", parse_mode="HTML")
            except: pass
            time.sleep(2)

        is_caught = True if is_test else (random.random() < 0.40)
        if not is_test: user_cooldowns[user_id] = time.time() + 30

        if user_id in active_hunt_sessions: del active_hunt_sessions[user_id]

        if is_caught:
            cards_col.update_one(
                {"id": card_id},
                {
                    "$inc": {
                        "hunt_count": 1,
                        f"hunters.{username}": 1
                    }
                }
            )
            
            collection_name = target_card.get('collection', target_card['name'] + " Collection")
            inventories_col.update_one(
                {"_id": str(user_id)},
                {
                    "$push": {
                        "cards": {
                            "id": target_card["id"], 
                            "name": target_card["name"], 
                            "rarity": target_card["rarity"], 
                            "collection": collection_name, 
                            "timestamp": time.time()
                        }
                    }
                },
                upsert=True
            )
            
            bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"🏆 <b>{username}</b> successfully caught a character!", parse_mode="HTML")
            
            congrats_message = (
                f"🎉 **CONGRATULATIONS!** 🎉\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✨ <a href='tg://user?id={user_id}'>{username}</a> successfully caught the character!\n\n"
                f"🃏 **CARD DETAILS** 🃏\n"
                f"• **Name:** {target_card['name']}\n"
                f"• **Rarity:** {target_card['rarity']}\n"
                f"• **ID:** <code>{target_card['id']}</code>\n"
                f"• **Collection:** {collection_name}\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            bot.send_message(call.message.chat.id, congrats_message, parse_mode="HTML", reply_to_message_id=call.message.message_id)
        else:
            bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"❌ <b>HUNT FAILED!</b> ❌\n\n<b>{target_card['name']}</b> escaped into the deep forest!", parse_mode="HTML")


# --- PERSONAL INVENTORY VIEW BY RARITY ---
@bot.message_handler(commands=['hview'])
def cmd_hview(message):
    if not check_chat_restrictions(message): return
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(text=v, callback_data=f"hview_rarity_{k}_{message.from_user.id}_1") for k, v in RARITIES.items()]
    markup.add(*buttons)
    bot.reply_to(message, "🗂 **Choose a Rarity to view your inventory:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('hview_rarity_'))
def handle_hview_callback(call):
    data_parts = call.data.split('_')
    rarity_key, owner_id, page = data_parts[2], int(data_parts[3]), int(data_parts[4])
    if call.from_user.id != owner_id: return
    
    user_doc = inventories_col.find_one({"_id": str(owner_id)})
    user_inventory = user_doc.get("cards", []) if user_doc else []
    rarity_full_name = RARITIES[rarity_key]
    filtered_cards = [c for c in user_inventory if c["rarity"] == rarity_full_name]

    if not filtered_cards:
        bot.answer_callback_query(call.id, f"❌ You don't own any cards in {rarity_full_name} rarity.", show_alert=True)
        return

    counted = {}
    for c in filtered_cards:
        counted[c["id"]] = counted.get(c["id"], {"name": c["name"], "qty": 0})
        counted[c["id"]]["qty"] += 1

    lines = [f"🪁 <b>ID: {cid}</b> | {info['name']} (x{info['qty']})" for cid, info in counted.items()]
    
    per_page = 10
    total_pages = (len(lines) + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    
    content = "\n".join(lines[(page-1)*per_page : page*per_page])
    text = f"🗃 <b>{rarity_full_name} Inventory</b> (Page: {page}/{total_pages})\n⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋\n{content}"

    markup = InlineKeyboardMarkup()
    nav_buttons = []
    if page > 1: nav_buttons.append(InlineKeyboardButton(text="⬅️ Back", callback_data=f"hview_rarity_{rarity_key}_{owner_id}_{page-1}"))
    if page < total_pages: nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"hview_rarity_{rarity_key}_{owner_id}_{page+1}"))
    if nav_buttons: markup.add(*nav_buttons)
    markup.add(InlineKeyboardButton(text="🔙 Back to Main Categories", callback_data=f"hview_main_{owner_id}"))

    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="HTML")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == 'hview_main' or call.data.startswith('hview_main_'))
def handle_hview_main(call):
    owner_id = int(call.data.split('_')[2]) if '_' in call.data else call.from_user.id
    if call.from_user.id != owner_id: return
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(text=v, callback_data=f"hview_rarity_{k}_{owner_id}_1") for k, v in RARITIES.items()]
    markup.add(*buttons)
    bot.edit_message_text("🗂 **Choose a Rarity to view your inventory:**", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")


# --- GLOBAL COLLECTION DICTIONARY ENGINE ---
@bot.message_handler(commands=['collection'])
def cmd_collection(message):
    if not check_chat_restrictions(message): return
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(text=v, callback_data=f"gcol_rarity_{k}_{message.from_user.id}_1") for k, v in RARITIES.items()]
    markup.add(*buttons)
    bot.reply_to(message, "🕋 **Explore all Registered Characters by Rarity:**", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('gcol_rarity_'))
def handle_global_collection_callback(call):
    parts = call.data.split('_')
    rarity_key, owner_id, page = parts[2], int(parts[3]), int(parts[4])
    if call.from_user.id != owner_id: return
    
    rarity_full_name = RARITIES[rarity_key]
    filtered_cards = list(cards_col.find({"rarity": rarity_full_name}))

    if not filtered_cards:
        bot.answer_callback_query(call.id, f"❌ No cards registered in {rarity_full_name} rarity yet.", show_alert=True)
        return

    lines = [f"🆔 <code>{c['id']}</code> | <b>{c['name']}</b>" for c in filtered_cards]
    per_page = 10
    total_pages = (len(lines) + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    
    content = "\n".join(lines[(page-1)*per_page : page*per_page])
    text = f"📚 <b>Global Book: {rarity_full_name}</b> (Page: {page}/{total_pages})\n-----------------------------------------\n{content}"

    markup = InlineKeyboardMarkup()
    nav_buttons = []
    if page > 1: nav_buttons.append(InlineKeyboardButton(text="⬅️ Back", callback_data=f"gcol_rarity_{rarity_key}_{owner_id}_{page-1}"))
    if page < total_pages: nav_buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"gcol_rarity_{rarity_key}_{owner_id}_{page+1}"))
    if nav_buttons: markup.add(*nav_buttons)
    markup.add(InlineKeyboardButton(text="🔙 Back to Main Categories", callback_data=f"gcol_main_{owner_id}"))

    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="HTML")
    bot.answer_callback_query(call.id)


# --- FAVORITE SETTING MANAGEMENT SYSTEM ---
@bot.message_handler(commands=['hfav'])
def cmd_hfav(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "❌ Usage: /hfav [card_id]")
        return
    try: search_id = int(args[1])
    except ValueError: return
    
    user_id = message.from_user.id
    user_doc = inventories_col.find_one({"_id": str(user_id)})
    user_inventory = user_doc.get("cards", []) if user_doc else []
    
    owns_card = any(c["id"] == search_id for c in user_inventory)
    if not owns_card:
        bot.reply_to(message, "❌ You do not own this card ID! Catch it first.")
        return
        
    target_card = cards_col.find_one({"id": search_id})
    if not target_card: return

    fav_doc = favorites_col.find_one({"_id": str(user_id)})
    is_already_fav = fav_doc and fav_doc.get("card_id") == search_id
    
    markup = InlineKeyboardMarkup()
    fav_btn = InlineKeyboardButton(text="❤️ Favorite [ON]" if is_already_fav else "🤍 Favorite", callback_data=f"fav_set_yes_{search_id}_{user_id}")
    unfav_btn = InlineKeyboardButton(text="💔 Unfavorite" if is_already_fav else "🖤 Unfavorite [OFF]", callback_data=f"fav_set_no_{search_id}_{user_id}")
    markup.add(fav_btn, unfav_btn)

    bot.send_photo(message.chat.id, target_card["photo_id"], caption=f"✨ Do you want to set <b>{target_card['name']}</b> as your Main Favorite profile?", reply_markup=markup, parse_mode="HTML", reply_to_message_id=message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('fav_set_'))
def handle_fav_setting_callback(call):
    action, card_id, owner_id = call.data.split('_')[2:5]
    card_id, owner_id = int(card_id), int(owner_id)
    if call.from_user.id != owner_id: return
    
    if action == "yes":
        favorites_col.update_one({"_id": str(owner_id)}, {"$set": {"card_id": card_id}}, upsert=True)
        bot.answer_callback_query(call.id, "❤️ Set as Favorite successfully!", show_alert=True)
    else:
        favorites_col.delete_one({"_id": str(owner_id)})
        bot.answer_callback_query(call.id, "💔 Removed from Favorites!", show_alert=True)
        
    bot.delete_message(call.message.chat.id, call.message.message_id)


# --- DYNAMIC INVENTORY INTEGRATION WITH COEXISTING FAVORITES ---
def build_inventory_page(user_id, page=1):
    str_user_id = str(user_id)
    user_doc = inventories_col.find_one({"_id": str_user_id})
    user_cards = user_doc.get("cards", []) if user_doc else []
    if not user_cards: return None, None, None

    collections = {}
    for uc in user_cards:
        col_name = uc.get("collection", uc["name"] + " Collection")
        if col_name not in collections: collections[col_name] = []
        collections[col_name].append(uc)

    formatted_lines = []
    for col_name, items in collections.items():
        formatted_lines.append(f"🕋 <b>{col_name} ({len(items)})</b>")
        formatted_lines.append("║⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋⚋")
        counted_items = {}
        for item in items:
            counted_items[item["id"]] = counted_items.get(item["id"], {"obj": item, "qty": 0})
            counted_items[item["id"]]["qty"] += 1
        for cid, info in counted_items.items():
            formatted_lines.append(f"🪁 {cid} | {info['obj']['rarity']} | {info['obj']['name']} (x{info['qty']})")
        formatted_lines.append("")

    items_per_page = 15
    total_pages = (len(formatted_lines) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * items_per_page
    page_content = "\n".join(formatted_lines[start_idx : start_idx + items_per_page])

    photo_id = None
    fav_doc = favorites_col.find_one({"_id": str_user_id})
    
    if fav_doc:
        fav_card_obj = cards_col.find_one({"id": int(fav_doc["card_id"])})
        if fav_card_obj: photo_id = fav_card_obj["photo_id"]

    if not photo_id and user_cards:
        last_card_id = user_cards[-1]["id"]
        last_card_obj = cards_col.find_one({"id": last_card_id})
        if last_card_obj: photo_id = last_card_obj["photo_id"]

    return page_content, total_pages, photo_id

@bot.message_handler(commands=['invan'])
def cmd_invan(message):
    if not check_chat_restrictions(message): return
    user_id = message.from_user.id
    user_name = message.from_user.username if message.from_user.username else message.from_user.first_name
    page_content, total_pages, photo_id = build_inventory_page(user_id, page=1)
    
    if not page_content:
        bot.reply_to(message, "📭 Your inventory is entirely empty! Go catch some characters first.")
        return

    caption_text = f"<b> 👤 {user_name}'s Recent Character - </b>\nPAGE: 1/{total_pages}\n\n{page_content}"
    markup = InlineKeyboardMarkup()
    if total_pages > 1:
        markup.add(InlineKeyboardButton(text="BACK 🧁", callback_data=f"invan_page_1_{user_id}"),
                   InlineKeyboardButton(text="NEXT 🧃", callback_data=f"invan_page_2_{user_id}"))

    if photo_id: bot.send_photo(message.chat.id, photo_id, caption=caption_text, reply_markup=markup, parse_mode="HTML", reply_to_message_id=message.message_id)
    else: bot.send_message(message.chat.id, caption_text, reply_markup=markup, parse_mode="HTML", reply_to_message_id=message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('invan_page_'))
def handle_invan_pagination(call):
    target_page, owner_id = call.data.split('_')[2:4]
    target_page, owner_id = int(target_page), int(owner_id)
    if call.from_user.id != owner_id: return
    
    user_name = call.from_user.username if call.from_user.username else call.from_user.first_name
    page_content, total_pages, photo_id = build_inventory_page(owner_id, page=target_page)
    caption_text = f"<b> 👤 {user_name}'s Recent Character - </b>\n<b><b>PAGE:</b></b> {target_page}/{total_pages}\n\n{page_content}"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="BACK 🧁", callback_data=f"invan_page_{target_page - 1 if target_page > 1 else total_pages}_{owner_id}"),
               InlineKeyboardButton(text="NEXT 🧃", callback_data=f"invan_page_{target_page + 1 if target_page < total_pages else 1}_{owner_id}"))

    try: bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=caption_text, reply_markup=markup, parse_mode="HTML")
    except: pass
    bot.answer_callback_query(call.id)


# --- GENERAL MESSAGE COUNTER FOR SPONDING SYSTEM ---
@bot.message_handler(func=lambda msg: msg.chat.type in ['group', 'supergroup'], content_types=['text', 'photo', 'video', 'animation', 'sticker'])
def count_group_messages(message):
    chat_id = message.chat.id
    
    try:
        if message.from_user.id != ADMIN_ID:
            member = bot.get_chat_member(MAIN_GP_ID, message.from_user.id)
            if member.status in ['left', 'kicked']:
                return
    except:
        return

    if chat_id not in group_message_counters:
        group_message_counters[chat_id] = 0
        
    group_message_counters[chat_id] += 1
    
    if group_message_counters[chat_id] >= 80:
        group_message_counters[chat_id] = 0
        
        all_cards = list(cards_col.find())
        if not all_cards:
            return
            
        random_card = random.choice(all_cards)
        
        spawn_text = (
            "🍭 ᴀ ᴄʜᴀʀᴀᴄ提ᴇʀ ʜᴀs sᴘᴀᴡɴᴇഡ് ɪɴ ᴛʜᴇ ᴄʜᴀᴛ! 🎇\n"
            "ᴀ提ᴅ ᴛʜɪs ᴄʜါရပ္တရာ ကို တူ ရ သွင် 🧃 /hbug  name"
        )
        
        try:
            sent_spawn = bot.send_photo(chat_id, random_card["photo_id"], caption=spawn_text)
            active_spawns[chat_id] = {
                "card_id": random_card["id"],
                "name": random_card["name"],
                "message_id": sent_spawn.message_id
            }
        except Exception as e:
            print(f"Failed to spawn card in {chat_id}: {e}")


print("Character Hunter Engine with MongoDB is now running perfectly...")
bot.infinity_polling()

