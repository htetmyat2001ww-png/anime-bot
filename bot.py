import telebot
import json
import os
import random
import time
import threading
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask  # Web server အတွက် ထည့်သွင်းထားသည်

# --- KOYEB 24H KEEP ALIVE SERVER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7 perfectly!"

def run_server():
    # Koyeb က ပေးမယ့် Port သို့မဟုတ် Port 8000 မှာ Server ပတ်မည်
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

# --- BOT CONFIGURATION ---
# လုံခြုံရေးအတွက် Token ကို Environment Variable ကနေ ဖတ်ခိုင်းထားသည်
TOKEN = os.getenv('BOT_TOKEN', '8921879251:AAFxYIiLJJVzWHShGF-VxiG1_9XBaVmK05c')
ADMIN_ID = 7940553702
MAIN_GP_ID = -1002755679723  # Main Group ID for restriction check

bot = telebot.TeleBot(TOKEN)
DB_FILE = 'database.json'

# --- In-Memory State Variables ---
admin_session = {}
user_cooldowns = {}      
active_hunt_sessions = {} 
group_message_counters = {}  
active_spawns = {}           

# PvP In-Memory State & Global Cooldown
pvp_battles = {}
pvp_cooldowns = {}

# Database Thread Lock to prevent file corruption during concurrent accesses
db_lock = threading.Lock()

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

# PvP Battle Lines (5 lines randomized for immersive text simulation)
BATTLE_ACTIONS = [
    "⚔️ Both cards enter the arena! The ground is shaking violently!",
    "💥 High speed clash! Sparks fly as skills hit each other!",
    "🛡️ Counter attack activated! One blocks while the other strikes!",
    "🔮 Magical auras ignite! Pure destructive energy filled the space!",
    "⚡ The final struggle begins! Both cards put everything into their last move!"
]

# Robust DB Loading with Threading Lock
def load_db():
    default_data = {"next_id": 100, "cards": [], "inventories": {}, "favorites": {}, "pvp_wins": {}, "daily_claims": {}}
    with db_lock:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                    if "next_id" not in data: data["next_id"] = 100
                    if "favorites" not in data: data["favorites"] = {}
                    if "inventories" not in data: data["inventories"] = {}
                    if "cards" not in data: data["cards"] = []
                    if "pvp_wins" not in data: data["pvp_wins"] = {}
                    if "daily_claims" not in data: data["daily_claims"] = {}
                    return data
                except json.JSONDecodeError:
                    return default_data
        return default_data

# Robust DB Saving with Threading Lock
def save_db(data):
    with db_lock:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

def check_and_add_daily_claim(user_id):
    """Checks if a user has exceeded their daily limit of 35 claims. Returns True if allowed, False if exceeded."""
    db = load_db()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    str_user_id = str(user_id)
    
    if today not in db["daily_claims"]:
        db["daily_claims"][today] = {}
        
    current_claims = db["daily_claims"][today].get(str_user_id, 0)
    if current_claims >= 35:
        return False
        
    db["daily_claims"][today][str_user_id] = current_claims + 1
    save_db(db)
    return True

def parse_name_from_text(text):
    if text and "NAME" in text.upper():
        for line in text.split('\n'):
            if "NAME" in line.upper():
                return line.split(':', 1)[1].strip()
    return None

def clean_emoji_and_spaces(text):
    if not text:
        return ""
    cleaned = "".join([char for char in text if char.isalnum() or char.isspace()])
    return " ".join(cleaned.lower().split())

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
            "❌ Access Denied!\n\n"
            "This bot can only be used by members of our Main Group.\n"
            "You must join the Main Group first to use the bot anywhere else!"
        )
        try:
            bot.reply_to(message, restriction_text, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass
        return False
        
    if message.chat.type == 'private' and message.text.split()[0] not in ['/start', '/help', '/addminc']:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(text="👥 Go to Main Group", url=MAIN_GP_LINK))
        try:
            bot.reply_to(message, "❌ This command can only be used inside groups!", reply_markup=markup, parse_mode="Markdown")
        except Exception:
            pass
        return False
        
    return True

def send_card_media(chat_id, card, caption, reply_markup=None, reply_to_message_id=None):
    media_id = card.get("photo_id")  # Backward compatibility
    if "media_id" in card:
        media_id = card["media_id"]
    
    media_type = card.get("media_type", "photo")
    
    try:
        if media_type == "video":
            return bot.send_video(chat_id, media_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
        elif media_type == "animation":
            return bot.send_animation(chat_id, media_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
        else:
            return bot.send_photo(chat_id, media_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML", reply_to_message_id=reply_to_message_id)
    except Exception:
        # Fallback to text if media sending fails
        return bot.send_message(chat_id, caption, reply_markup=reply_markup, parse_mode="HTML", reply_to_message_id=reply_to_message_id)

def get_telegram_name(user_id, fallback_name="Hunter"):
    """Helper to fetch real Telegram Name dynamically via API to avoid raw IDs"""
    try:
        chat = bot.get_chat(int(user_id))
        if chat.first_name:
            return chat.first_name
        if chat.username:
            return chat.username
    except Exception:
        pass
    return fallback_name

def get_help_text():
    return (
        "🤖 Character Hunter Bot Command List\n\n"
        "Here are the available commands you can use↴\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎯 /hunt - Search and capture new character cards\n"
        "🧃 /hbug [name] - Claim spawned character in chat\n"
        "🗂 /hview - View your owned cards filtered by Rarity\n"
        "🕋 /collection - Browse all registered cards in the bot\n"
        "🗃 /invan - View your collection profile and inventory pages\n"
        "🔍 /hsee [Card_ID] - Check card profile and top 10 hunters\n"
        "🔍 /cs [Card_ID] - Look up any card details directly\n"
        "❤️ /hfav [Card_ID] - Set a card as your main favorite profile look\n"
        "🤝 /htrade [Your_ID] [Their_ID] - Trade cards (Reply to user)\n"
        "🎁 /hgift [Card_ID] - Gift a card to another user (Reply to user)\n"
        "⚔️ /attack [Card_ID] - Challenge a player to a PvP duel (Reply to user)\n"
        "🛡️ /trun [Card_ID] - Accept PvP challenge and fight back\n"
        "🏃‍♂️ /attleave - Decline or cancel the pending duel invitation\n"
        "🏆 /pvptop - View Top 10 PvP Winners leaderboard\n"
        "🏆 /gtop - View top 10 card owners in this group\n"
        "🏆 /tg - View top 10 card collectors in this group\n"
        "🔒 /exit - Force cancel your current active hunt session\n"
        "ℹ️ /help - Show this manual and command list\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

# --- ALL CALLBACK QUERY HANDLERS ---

@bot.callback_query_handler(func=lambda call: call.data.startswith('help_menu_'))
def handle_help_callback(call):
    owner_id = int(call.data.split('_')[2])
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "❌ This is not your menu!", show_alert=True)
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="👥 Join Main Group", url=MAIN_GP_LINK))
    try:
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=get_help_text(), reply_markup=markup, parse_mode="Markdown")
    except Exception:
        pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('set_rarity_'))
def save_card_to_db_callback(call):
    parts = call.data.split('_')
    rarity_key = parts[2]
    user_id = int(parts[3])
    
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Only the initiating admin can click this!", show_alert=True)
        return
        
    rarity_name = RARITIES.get(rarity_key, "Unknown")
    
    if user_id not in admin_session or not admin_session[user_id].get("name"):
        bot.answer_callback_query(call.id, "❌ Session expired or incomplete data.", show_alert=True)
        return
        
    db = load_db()
    current_id = db["next_id"]
    new_card = {
        "id": current_id,
        "name": admin_session[user_id]["name"],
        "rarity": rarity_name,
        "collection": admin_session[user_id]["name"] + " Collection",
        "media_id": admin_session[user_id]["media_id"],
        "media_type": admin_session[user_id]["media_type"],
        "photo_id": admin_session[user_id]["media_id"], # Compatibility fallback
        "hunt_count": 0,
        "hunters": {}
    }
    db["cards"].append(new_card)
    db["next_id"] += 1
    save_db(db)
    
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        bot.send_message(user_id, f"✅ Successfully Added!\n🆔 ID: {current_id}\n📛 Name: {new_card['name']}\n💎 Rarity: {rarity_name}")
    except Exception:
        pass
    
    del admin_session[user_id]
    bot.answer_callback_query(call.id, "✅ Saved Setup!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('hsee_'))
def handle_hsee_buttons(call):
    parts = call.data.split('_')
    action = parts[1]
    card_id = int(parts[2])
    owner_id = int(parts[3])
    
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "❌ This menu belongs to someone else!", show_alert=True)
        return
        
    db = load_db()
    target_card = next((card for card in db["cards"] if card["id"] == card_id), None)
    if not target_card:
        bot.answer_callback_query(call.id, "❌ Card not found!", show_alert=True)
        return
    
    markup = InlineKeyboardMarkup()
    if action == "top":
        new_caption = get_top_hunters_text(target_card, db)
        markup.add(InlineKeyboardButton(text="🔙 Close Top 10", callback_data=f"hsee_profile_{card_id}_{owner_id}"))
    else:
        new_caption = get_card_profile_text(target_card, db)
        markup.add(InlineKeyboardButton(text="🎯 Top 10 Hunters", callback_data=f"hsee_top_{card_id}_{owner_id}"))
        
    try:
        bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=new_caption, reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('player_'))
def handle_hunt_actions(call):
    user_id = call.from_user.id
    real_name = call.from_user.first_name if call.from_user.first_name else "Hunter"
    
    parts = call.data.split('_')
    action = parts[1]
    card_id = int(parts[2])
    owner_id = int(parts[3])
    is_test = parts[4] == '1'
    
    if user_id != owner_id:
        bot.answer_callback_query(call.id, "❌ This menu belongs to someone else!", show_alert=True)
        return
        
    current_time = time.time()
    if not is_test and user_id != ADMIN_ID and user_id in user_cooldowns and current_time < user_cooldowns[user_id]:
        bot.answer_callback_query(call.id, "⏳ Cooldown running!", show_alert=True)
        return

    db = load_db()
    target_card = next((card for card in db["cards"] if card["id"] == card_id), None)
    
    if not target_card:
        if user_id in active_hunt_sessions: del active_hunt_sessions[user_id]
        bot.answer_callback_query(call.id, "❌ Error loading card data.", show_alert=True)
        return

    if action == "skip":
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"💨 <b>{real_name}</b> decided to skip <b>{target_card['name']}</b>!", parse_mode="HTML")
        except Exception: pass
        
        if user_id in active_hunt_sessions: del active_hunt_sessions[user_id]
        if not is_test and user_id != ADMIN_ID: user_cooldowns[user_id] = current_time + 180
        bot.answer_callback_query(call.id)
        return

    if action == "hunt":
        if not check_and_add_daily_claim(user_id):
            bot.answer_callback_query(call.id, "⚠️ Daily claim limit reached!", show_alert=True)
            try:
                bot.send_message(call.message.chat.id, f"⚠️ Daily Claim Limit Reached!\n\nHi <a href='tg://user?id={user_id}'>{real_name}</a>, you have already claimed 35 cards today. Please try again tomorrow.", parse_mode="HTML", reply_to_message_id=call.message.message_id)
            except Exception: pass
            if user_id in active_hunt_sessions: del active_hunt_sessions[user_id]
            return

        if user_id in active_hunt_sessions:
            active_hunt_sessions[user_id]["hunting"] = True
            
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception: pass
        
        chosen_animations = random.sample(HUNT_ANIMATIONS, 3)
        for step in chosen_animations:
            try: 
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"🏹 <b>{real_name} is hunting...</b>\n\n{step}", parse_mode="HTML")
            except Exception: pass
            time.sleep(2)

        is_caught = True if is_test else (random.random() < 0.40)
        if not is_test and user_id != ADMIN_ID: user_cooldowns[user_id] = time.time() + 180
        if user_id in active_hunt_sessions: del active_hunt_sessions[user_id]

        if is_caught:
            for card in db["cards"]:
                if card["id"] == card_id:
                    card["hunt_count"] = card.get("hunt_count", 0) + 1
                    if "hunters" not in card: card["hunters"] = {}
                    card["hunters"][real_name] = card["hunters"].get(real_name, 0) + 1
                    break
            
            str_user_id = str(user_id)
            if str_user_id not in db["inventories"]: db["inventories"][str_user_id] = []
            
            collection_name = target_card.get('collection', target_card['name'] + " Collection")
            db["inventories"][str_user_id].append({
                "id": target_card["id"], 
                "name": target_card["name"], 
                "rarity": target_card["rarity"], 
                "collection": collection_name, 
                "collector_name": real_name,
                "timestamp": time.time()
            })
            save_db(db)
            
            try:
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"🏆 <b>{real_name}</b> successfully caught a character!", parse_mode="HTML")
                congrats_message = (
                    f"🎉 CONGRATULATIONS! 🎉\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"✨ <a href='tg://user?id={user_id}'>{real_name}</a> successfully caught the character!\n\n"
                    f"🃏 CARD DETAILS 🃏\n"
                    f"• Name: {target_card['name']}\n"
                    f"• Rarity: {target_card['rarity']}\n"
                    f"• ID: <code>{target_card['id']}</code>\n"
                    f"• Collection: {collection_name}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━"
                )
                bot.send_message(call.message.chat.id, congrats_message, parse_mode="HTML", reply_to_message_id=call.message.message_id)
            except Exception: pass
        else:
            try:
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"❌ HUNT FAILED! ❌\n\n<b>{target_card['name']}</b> escaped into the deep forest!", parse_mode="HTML")
            except Exception: pass
            
        bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('hview_rarity_'))
def handle_hview_callback(call):
    data_parts = call.data.split('_')
    rarity_key, owner_id, page = data_parts[2], int(data_parts[3]), int(data_parts[4])
    if call.from_user.id != owner_id: 
        bot.answer_callback_query(call.id, "❌ Not your inventory!", show_alert=True)
        return
    
    db = load_db()
    user_inventory = db.get("inventories", {}).get(str(owner_id), [])
    rarity_full_name = RARITIES.get(rarity_key, "Unknown")
    filtered_cards = [c for c in user_inventory if c["rarity"] == rarity_full_name]

    if not filtered_cards:
        bot.answer_callback_query(call.id, f"❌ You don't own any cards in {rarity_full_name} rarity.", show_alert=True)
        return

    counted = {}
    for c in filtered_cards:
        counted[c["id"]] = counted.get(c["id"], {"name": c["name"], "qty": 0})
        counted[c["id"]]["qty"] += 1

    lines = [f"🪁 <b>ID: {cid}</b> | {info['name']} (x{info['qty']})" for cid, info in counted.items()]
    
    per_page = 20  # Optimized for handling thousands of cards
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

    try:
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception: pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('hview_main_'))
def handle_hview_main(call):
    owner_id = int(call.data.split('_')[2])
    if call.from_user.id != owner_id: 
        bot.answer_callback_query(call.id, "❌ This is not your menu!", show_alert=True)
        return
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(text=v, callback_data=f"hview_rarity_{k}_{owner_id}_1") for k, v in RARITIES.items()]
    markup.add(*buttons)
    try: bot.edit_message_text("🗂 Choose a Rarity to view your inventory:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception: pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('gcol_rarity_'))
def handle_global_collection_callback(call):
    parts = call.data.split('_')
    rarity_key, owner_id, page = parts[2], int(parts[3]), int(parts[4])
    if call.from_user.id != owner_id: 
        bot.answer_callback_query(call.id, "❌ Not your menu!", show_alert=True)
        return
    
    db = load_db()
    rarity_full_name = RARITIES.get(rarity_key, "Unknown")
    filtered_cards = [c for c in db.get("cards", []) if c["rarity"] == rarity_full_name]

    if not filtered_cards:
        bot.answer_callback_query(call.id, f"❌ No cards registered in {rarity_full_name} rarity yet.", show_alert=True)
        return

    lines = [f"🆔 <code>{c['id']}</code> | <b>{c['name']}</b>" for c in filtered_cards]
    per_page = 20  # Scaled up for thousands of cards
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

    try: bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception: pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('gcol_main_'))
def handle_gcol_main(call):
    owner_id = int(call.data.split('_')[2])
    if call.from_user.id != owner_id: 
        bot.answer_callback_query(call.id, "❌ Not your menu!", show_alert=True)
        return
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(text=v, callback_data=f"gcol_rarity_{k}_{owner_id}_1") for k, v in RARITIES.items()]
    markup.add(*buttons)
    try: bot.edit_message_text("🕋 Explore all Registered Characters by Rarity:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception: pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('fav_set_'))
def handle_favorite_callback(call):
    parts = call.data.split('_')
    action, card_id, owner_id = parts[2], int(parts[3]), parts[4]
    
    if str(call.from_user.id) != owner_id:
        bot.answer_callback_query(call.id, "❌ This menu belongs to someone else!", show_alert=True)
        return
        
    db = load_db()
    if action == "yes":
        db["favorites"][owner_id] = card_id
        bot.answer_callback_query(call.id, "❤️ Successfully set as favorite profile!", show_alert=True)
    else:
        if owner_id in db["favorites"]:
            del db["favorites"][owner_id]
        bot.answer_callback_query(call.id, "🖤 Removed from favorites.", show_alert=True)
        
    save_db(db)
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('invan_page_'))
def handle_invan_pagination(call):
    parts = call.data.split('_')
    target_page = int(parts[2])
    owner_id = int(parts[3])
    if call.from_user.id != owner_id: 
        bot.answer_callback_query(call.id, "❌ Not your inventory!", show_alert=True)
        return
    
    real_name = call.from_user.first_name if call.from_user.first_name else "Hunter"
    page_content, total_pages, _ = build_inventory_page(owner_id, page=target_page)
    caption_text = f"<b> 👤 {real_name}'s Recent Character - </b>\n<b>PAGE:</b> {target_page}/{total_pages}\n\n{page_content}"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="BACK 🧁", callback_data=f"invan_page_{target_page - 1 if target_page > 1 else total_pages}_{owner_id}"),
               InlineKeyboardButton(text="NEXT 🧃", callback_data=f"invan_page_{target_page + 1 if target_page < total_pages else 1}_{owner_id}"))

    try: bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=caption_text, reply_markup=markup, parse_mode="HTML")
    except Exception: pass
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def handle_admin_panel_callbacks(call):
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "❌ Unauthorized!", show_alert=True)
        return
        
    action = call.data.split('_')[1]
    
    if action == "spawn":
        bot.answer_callback_query(call.id)
        msg = call.message
        msg.from_user.id = ADMIN_ID
        msg.text = "/spawn"
        cmd_spawn(msg)
        
    elif action == "stats":
        bot.answer_callback_query(call.id)
        msg = call.message
        msg.from_user.id = ADMIN_ID
        cmd_stats(msg)
        
    elif action == "close":
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception: pass


# --- COMMAND HANDLERS & BOT COMMAND LOGICS ---

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
        f"👋 Welcome to Character Hunter World!\n\n"
        f"Hello {message.from_user.first_name}! Hunt, collect, trade, and build your ultimate "
        f"character legendary inventory deck right here!\n\n"
        f"Press the buttons below to join our community or explore the commands!"
    )
    try: bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")
    except Exception: pass

@bot.message_handler(commands=['help'])
def cmd_help(message):
    if not check_chat_restrictions(message): return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="👥 Join Main Group", url=MAIN_GP_LINK))
    try: bot.reply_to(message, get_help_text(), reply_markup=markup, parse_mode="Markdown")
    except Exception: pass

@bot.message_handler(commands=['hbug'])
def cmd_hbug(message):
    if not check_chat_restrictions(message): return
    chat_id = message.chat.id
    user_id = message.from_user.id
    real_name = message.from_user.first_name if message.from_user.first_name else "Hunter"

    if chat_id not in active_spawns:
        try: bot.reply_to(message, "Sorry, someone already claimed this card! Try again next time.")
        except Exception: pass
        return

    if not check_and_add_daily_claim(user_id):
        try: bot.reply_to(message, f"⚠️ Daily Claim Limit Reached!\n\nHi <a href='tg://user?id={user_id}'>{real_name}</a>, you have already claimed 35 cards today. Please try again tomorrow.", parse_mode="HTML")
        except Exception: pass
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        try: bot.reply_to(message, "⚠️ Usage: /hbug [Character Name]", parse_mode="Markdown")
        except Exception: pass
        return

    user_answer = clean_emoji_and_spaces(args[1])
    spawned_card = active_spawns[chat_id]
    correct_answer = clean_emoji_and_spaces(spawned_card["name"])

    if user_answer == correct_answer:
        db = load_db()
        target_card = next((c for c in db["cards"] if c["id"] == spawned_card["card_id"]), None)
        
        if target_card:
            target_card["hunt_count"] = target_card.get("hunt_count", 0) + 1
            if "hunters" not in target_card: target_card["hunters"] = {}
            target_card["hunters"][real_name] = target_card["hunters"].get(real_name, 0) + 1
            
            str_user_id = str(user_id)
            if str_user_id not in db["inventories"]: 
                db["inventories"][str_user_id] = []
                
            collection_name = target_card.get('collection', target_card['name'] + " Collection")
            db["inventories"][str_user_id].append({
                "id": target_card["id"], 
                "name": target_card["name"], 
                "rarity": target_card["rarity"], 
                "collection": collection_name, 
                "collector_name": real_name,
                "timestamp": time.time()
            })
            save_db(db)
            del active_spawns[chat_id]

            congrats_text = (
                f"🎉 CONGRATULATIONS! 🎉\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✨ <a href='tg://user?id={user_id}'>{real_name}</a> answered correctly and successfully claimed the character!\n\n"
                f"🃏 CARD DETAILS 🃏\n"
                f"• Name: {target_card['name']}\n"
                f"• Rarity: {target_card['rarity']}\n"
                f"• ID: <code>{target_card['id']}</code>\n"
                f"• Collection: {collection_name}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📥 The character has been saved directly to your inventory (/invan)."
            )
            try: bot.send_message(chat_id, congrats_text, parse_mode="HTML", reply_to_message_id=message.message_id)
            except Exception: pass
        else:
            del active_spawns[chat_id]
            try: bot.reply_to(message, "❌ An error occurred. The character data could not be found.")
            except Exception: pass
    else:
        try: bot.reply_to(message, "❌ Wrong name! Try checking your spelling and try again.")
        except Exception: pass

@bot.message_handler(commands=['gtop'])
def cmd_gtop(message):
    if not check_chat_restrictions(message): return
    if message.chat.type == 'private':
        try: bot.reply_to(message, "❌ This command can only be used inside groups.")
        except Exception: pass
        return
        
    db = load_db()
    inventories = db.get("inventories", {})
    
    user_counts = []
    for uid, cards in inventories.items():
        if cards:
            fallback = cards[-1].get("collector_name", f"Hunter_{uid}")
            real_name = get_telegram_name(uid, fallback)
            user_counts.append((real_name, len(cards)))
            
    user_counts.sort(key=lambda x: x[1], reverse=True)
    top_10 = user_counts[:10]
    
    leaderboard_text = "🏆 Group Top 10 Card Owners 🏆\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (name, count) in enumerate(top_10, 1):
        leaderboard_text += f"{i}. 🎐 {name} — ({count} Cards)\n"
        
    for i in range(len(top_10) + 1, 11):
        leaderboard_text += f"{i}. 🎐 Empty Slot\n"
        
    leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━"
    try: bot.reply_to(message, leaderboard_text, parse_mode="HTML")
    except Exception: pass

@bot.message_handler(commands=['tg'])
def cmd_tg(message):
    if not check_chat_restrictions(message): return
    if message.chat.type == 'private':
        try: bot.reply_to(message, "❌ This command can only be used inside groups.")
        except Exception: pass
        return
        
    db = load_db()
    inventories = db.get("inventories", {})
    
    group_collectors = []
    for user_id, cards in inventories.items():
        if cards:
            fallback = cards[-1].get("collector_name", f"Hunter_{user_id}")
            real_name = get_telegram_name(user_id, fallback)
            group_collectors.append((real_name, len(cards)))
            
    group_collectors.sort(key=lambda x: x[1], reverse=True)
    top_10 = group_collectors[:10]
    
    leaderboard_text = "🏆 **Group Top 10 Card Collectors** 🏆\n━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, (name, count) in enumerate(top_10, 1):
        leaderboard_text += f"{i}. 🎐 {name} — ({count} Cards Owned)\n"
        
    for i in range(len(top_10) + 1, 11):
        leaderboard_text += f"{i}. 🎐 Empty Slot\n"
        
    leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━"
    try: bot.reply_to(message, leaderboard_text, parse_mode="Markdown")
    except Exception: pass


# --- NEW /del COMMAND FOR ADMIN TO REMOVE UNWANTED CARDS ---
@bot.message_handler(commands=['del'])
def cmd_delete_card(message):
    if message.from_user.id != ADMIN_ID:
        return
        
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: /del [Card_ID]")
        return
        
    try:
        target_id = int(args[1])
    except ValueError:
        bot.reply_to(message, "❌ Card ID must be numeric.")
        return
        
    db = load_db()
    
    # Check if the card exists in database base record
    card_index = next((i for i, card in enumerate(db["cards"]) if card["id"] == target_id), None)
    
    if card_index is None:
        bot.reply_to(message, f"❌ Card ID {target_id} not found in the database system.")
        return
        
    # Remove from base cards record
    removed_card = db["cards"].pop(card_index)
    
    # Clean up from everyone's inventory
    for user_id in list(db["inventories"].keys()):
        db["inventories"][user_id] = [c for c in db["inventories"][user_id] if c["id"] != target_id]
        
    # Clean up favorites
    for user_id, fav_id in list(db["favorites"].items()):
        if fav_id == target_id:
            del db["favorites"][user_id]
            
    save_db(db)
    
    success_text = (
        "🧹 **CARD DELETION SUCCESSFUL** 🧹\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Successfully deleted Card from the entire bot engine system.\n\n"
        f"• **Name:** {removed_card['name']}\n"
        f"• **ID:** `{target_id}`\n"
        f"• **Rarity:** {removed_card['rarity']}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ This card has been wiped from all user inventories and collections automatically."
    )
    bot.reply_to(message, success_text, parse_mode="Markdown")


@bot.message_handler(commands=['htrade'])
def cmd_htrade(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    
    if len(args) < 3 or not message.reply_to_message:
        usage_text = (
            "🤝 <b>How to use /htrade command</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "To trade cards with another user, follow these steps:\n\n"
            "1. Reply to the user's message you want to trade with.\n"
            "2. Type: <code>/htrade [Your_Card_ID] [Their_Card_ID]</code>\n\n"
            "💡 Example: <code>/htrade 102 105</code>"
        )
        try: bot.reply_to(message, usage_text, parse_mode="HTML")
        except Exception: pass
        return
        
    sender_id = str(message.from_user.id)
    receiver_id = str(message.reply_to_message.from_user.id)
    sender_name = message.from_user.first_name if message.from_user.first_name else "Hunter"
    receiver_name = message.reply_to_message.from_user.first_name if message.reply_to_message.from_user.first_name else "Hunter"
    
    if sender_id == receiver_id:
        bot.reply_to(message, "❌ You cannot trade cards with yourself!")
        return

    try:
        your_card_id = int(args[1])
        their_card_id = int(args[2])
    except ValueError:
        bot.reply_to(message, "❌ Card IDs must be numeric format.")
        return

    db = load_db()
    sender_inv = db.get("inventories", {}).get(sender_id, [])
    receiver_inv = db.get("inventories", {}).get(receiver_id, [])

    your_card = next((c for c in sender_inv if c["id"] == your_card_id), None)
    their_card = next((c for c in receiver_inv if c["id"] == their_card_id), None)

    if not your_card:
        bot.reply_to(message, f"❌ You do not own Card ID: {your_card_id} in your inventory.")
        return
    if not their_card:
        bot.reply_to(message, f"❌ The opponent does not own Card ID: {their_card_id}.")
        return

    sender_inv.remove(your_card)
    receiver_inv.remove(their_card)
    
    # Update ownership name tracking
    your_card["collector_name"] = receiver_name
    their_card["collector_name"] = sender_name
    
    sender_inv.append(their_card)
    receiver_inv.append(your_card)
    
    db["inventories"][sender_id] = sender_inv
    db["inventories"][receiver_id] = receiver_inv
    save_db(db)

    trade_success = (
        "🤝 <b>TRADE SUCCESSFUL!</b> 🤝\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 <a href='tg://user?id={sender_id}'>{sender_name}</a> swapped their card with "
        f"<a href='tg://user?id={receiver_id}'>{receiver_name}</a>!\n\n"
        f"📤 <b>Sent:</b> {your_card['name']} (ID: {your_card_id})\n"
        f"📥 <b>Received:</b> {their_card['name']} (ID: {their_card_id})\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, trade_success, parse_mode="HTML")

@bot.message_handler(commands=['hgift'])
def cmd_hgift(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    
    if len(args) < 2 or not message.reply_to_message:
        usage_text = (
            "🎁 <b>How to use /hgift command</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "To send a card as a gift to another user:\n\n"
            "1. Reply to that user's message.\n"
            "2. Type: <code>/hgift [Your_Card_ID]</code>\n\n"
            "💡 Example: <code>/hgift 102</code>"
        )
        try: bot.reply_to(message, usage_text, parse_mode="HTML")
        except Exception: pass
        return
        
    sender_id = str(message.from_user.id)
    receiver_id = str(message.reply_to_message.from_user.id)
    sender_name = message.from_user.first_name if message.from_user.first_name else "Hunter"
    receiver_name = message.reply_to_message.from_user.first_name if message.reply_to_message.from_user.first_name else "Hunter"
    
    if sender_id == receiver_id:
        bot.reply_to(message, "❌ You cannot gift cards to yourself!")
        return
        
    if message.reply_to_message.from_user.is_bot:
        bot.reply_to(message, "❌ You cannot send gifts to a bot!")
        return

    try:
        gift_card_id = int(args[1])
    except ValueError:
        bot.reply_to(message, "❌ Card ID must be numeric.")
        return

    db = load_db()
    sender_inv = db.get("inventories", {}).get(sender_id, [])
    
    gift_card = next((c for c in sender_inv if c["id"] == gift_card_id), None)
    if not gift_card:
        bot.reply_to(message, f"❌ You do not own Card ID: {gift_card_id} in your inventory.")
        return

    sender_inv.remove(gift_card)
    gift_card["collector_name"] = receiver_name
    
    if receiver_id not in db["inventories"]:
        db["inventories"][receiver_id] = []
    db["inventories"][receiver_id].append(gift_card)
    db["inventories"][sender_id] = sender_inv
    save_db(db)

    gift_success = (
        "🎁 <b>GIFT TRANSMISSION SUCCESS!</b> 🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ <a href='tg://user?id={sender_id}'>{sender_name}</a> sent a character card as a special gift to "
        f"<a href='tg://user?id={receiver_id}'>{receiver_name}</a>!\n\n"
        f"🃏 <b>Gifted Card:</b> {gift_card['name']}\n"
        f"🆔 <b>Card ID:</b> <code>{gift_card_id}</code>\n"
        f"💎 <b>Rarity:</b> {gift_card['rarity']}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, gift_success, parse_mode="HTML")

@bot.message_handler(commands=['addminc'])
def cmd_addminc(message):
    if message.from_user.id != ADMIN_ID: 
        return
        
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(text="🃏 Instant Spawn", callback_data="admin_spawn"),
        InlineKeyboardButton(text="📊 Global Stats", callback_data="admin_stats"),
        InlineKeyboardButton(text="❌ Close Menu", callback_data="admin_close")
    )
    
    panel_text = (
        "⚡️ **WELCOME BACK OWNER/ADMIN** ⚡️\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Here is your real-time controller layout menu. You can easily manage bot operations "
        "or broadcast metrics using standard slash commands or directly via interactive dashboard buttons below.\n\n"
        "🔧 **Available Actions:**\n"
        "• `/spawn` or Button - Summon a card instantly\n"
        "• `/stats` or Button - View database profile stats\n"
        "• `/del [id]` - Safely wipe and delete a specific card\n"
        "• `/broadcast` - Forward any replied message to all users"
    )
    try: bot.reply_to(message, panel_text, reply_markup=markup, parse_mode="Markdown")
    except Exception: pass

@bot.message_handler(commands=['cs'])
def cmd_cs(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    if len(args) < 2:
        try: bot.reply_to(message, "❌ Usage: /cs [Card_ID]", parse_mode="Markdown")
        except Exception: pass
        return
        
    try: search_id = int(args[1])
    except ValueError:
        try: bot.reply_to(message, "❌ Invalid Card ID format. It must be numeric.")
        except Exception: pass
        return
        
    db = load_db()
    target_card = next((card for card in db["cards"] if card["id"] == search_id), None)
    if not target_card:
        try: bot.reply_to(message, f"❌ Card ID `{search_id}` does not exist in our database record.", parse_mode="Markdown")
        except Exception: pass
        return
        
    collection_name = target_card.get('collection', target_card['name'] + " Collection")
    card_info_text = (
        f"🃏 <b>CARD DATA LOOKUP SUCCESS</b> 🃏\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Card ID ::</b> <code>{target_card['id']}</code>\n"
        f"👤 <b>Name ::</b> {target_card['name']}\n"
        f"💎 <b>Rarity ::</b> {target_card['rarity']}\n"
        f"🕋 <b>Collection Book ::</b> {collection_name}\n"
        f"📈 <b>Global Captured Total ::</b> {target_card.get('hunt_count', 0)} times\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    send_card_media(message.chat.id, target_card, card_info_text, reply_to_message_id=message.message_id)

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if message.from_user.id != ADMIN_ID: return
    db = load_db()
    total_users = len(db.get("inventories", {}))
    total_cards = len(db.get("cards", []))
    
    stats_text = (
        "📊 Bot Global Statistics (Admin Only)\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Active Users: {total_users}\n"
        f"🃏 Total Registered Cards: {total_cards}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )
    try: bot.reply_to(message, stats_text, parse_mode="Markdown")
    except Exception: pass

@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if message.from_user.id != ADMIN_ID: return
    if not message.reply_to_message:
        try: bot.reply_to(message, "⚠️ Usage: Please reply to the Message/Photo/Video you want to broadcast with /broadcast", parse_mode="Markdown")
        except Exception: pass
        return
        
    db = load_db()
    user_ids = list(db.get("inventories", {}).keys())
    
    if not user_ids:
        try: bot.reply_to(message, "❌ No users found in the database to broadcast.")
        except Exception: pass
        return

    sent_count = 0
    fail_count = 0
    try: status_msg = bot.reply_to(message, f"📢 Smart Broadcast started to {len(user_ids)} users... Please wait.")
    except Exception: return
    
    replied_msg = message.reply_to_message
    for uid in user_ids:
        try:
            bot.copy_message(chat_id=int(uid), from_chat_id=replied_msg.chat.id, message_id=replied_msg.message_id)
            sent_count += 1
            time.sleep(0.1)
        except Exception:
            fail_count += 1

    try: bot.edit_message_text(f"✅ Broadcast Completed!\n\n🟢 Successfully Sent: {sent_count}\n🔴 Failed/Blocked: {fail_count}", chat_id=status_msg.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
    except Exception: pass

@bot.message_handler(commands=['spawn'])
def cmd_spawn(message):
    if message.from_user.id != ADMIN_ID: return
    chat_id = message.chat.id
    db = load_db()
    
    if not db.get("cards", []):
        try: bot.reply_to(message, "❌ No cards available in the database.")
        except Exception: pass
        return
        
    args = message.text.split()
    target_card = None
    
    if len(args) > 1:
        try:
            search_id = int(args[1])
            target_card = next((c for c in db["cards"] if c["id"] == search_id), None)
            if not target_card:
                bot.reply_to(message, f"❌ Card ID {search_id} not found.")
                return
        except ValueError:
            try: bot.reply_to(message, "⚠️ Invalid ID format. Use /spawn [id]")
            except Exception: pass
            return
    else:
        target_card = random.choice(db["cards"])
        
    spawn_text = (
        "🍭 A character has spawned in the chat! 🎇\n"
        "Add this character to your harem using 🧃 /hbug name"
    )
    
    try:
        sent_spawn = send_card_media(chat_id, target_card, spawn_text)
        active_spawns[chat_id] = {
            "card_id": target_card["id"],
            "name": target_card["name"],
            "message_id": sent_spawn.message_id
        }
    except Exception as e:
        try: bot.reply_to(message, f"❌ Failed to spawn: {e}")
        except Exception: pass

@bot.message_handler(commands=['hsee'])
def cmd_hsee(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    if len(args) < 2:
        try: bot.reply_to(message, "❌ Usage: /hsee [card_id]")
        except Exception: pass
        return
    try: search_id = int(args[1])
    except ValueError: return
    db = load_db()
    target_card = next((card for card in db["cards"] if card["id"] == search_id), None)
    if not target_card: return
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="🎯 Top 10 Hunters", callback_data=f"hsee_top_{search_id}_{message.from_user.id}"))
    try: 
        send_card_media(message.chat.id, target_card, get_card_profile_text(target_card, db), reply_markup=markup, reply_to_message_id=message.message_id)
    except Exception: pass

@bot.message_handler(commands=['hunt'])
def cmd_hunt(message):
    if not check_chat_restrictions(message): return
    user_id = message.from_user.id
    current_time = time.time()
    
    session = active_hunt_sessions.get(user_id)
    if session:
        try:
            if session.get("hunting") is True:
                bot.reply_to(message, "⚠️ Tracking in progress! Please wait until the process finishes.")
            else:
                bot.reply_to(message, "❌ Your previous hunt session is not finished!\nPlease choose HUNT or SKIP.\n\nUse /exit to cancel.", parse_mode="Markdown")
        except Exception: pass
        return
        
    if user_id != ADMIN_ID and user_id in user_cooldowns and current_time < user_cooldowns[user_id]:
        try: bot.reply_to(message, f"⏳ You are exhausted! Please wait {int(user_cooldowns[user_id] - current_time)}s before hunting again.")
        except Exception: pass
        return
    
    db = load_db()
    if not db.get("cards", []): return
    execute_hunt_process(message, random.choice(db["cards"]), is_test=False)

@bot.message_handler(commands=['exit'])
def cmd_exit_hunt(message):
    if not check_chat_restrictions(message): return
    user_id = message.from_user.id
    if active_hunt_sessions.get(user_id):
        session = active_hunt_sessions[user_id]
        try:
            bot.edit_message_reply_markup(chat_id=session["chat_id"], message_id=session["message_id"], reply_markup=None)
            bot.edit_message_caption(chat_id=session["chat_id"], message_id=session["message_id"], caption="🔒 <b>This hunt session has been locked and abandoned!</b>", parse_mode="HTML")
        except Exception: pass
        
        del active_hunt_sessions[user_id]
        if user_id != ADMIN_ID: user_cooldowns[user_id] = time.time() + 180
        try: bot.reply_to(message, "🔒 Session locked!\n3 minutes cooldown started. You can /hunt after it expires.", parse_mode="Markdown")
        except Exception: pass
    else:
        try: bot.reply_to(message, "ℹ️ You do not have an active hunt session right now.")
        except Exception: pass

@bot.message_handler(commands=['hview'])
def cmd_hview(message):
    if not check_chat_restrictions(message): return
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(text=v, callback_data=f"hview_rarity_{k}_{message.from_user.id}_1") for k, v in RARITIES.items()]
    markup.add(*buttons)
    try: bot.reply_to(message, "🗂 Choose a Rarity to view your inventory:", reply_markup=markup, parse_mode="Markdown")
    except Exception: pass

@bot.message_handler(commands=['collection'])
def cmd_collection(message):
    if not check_chat_restrictions(message): return
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(text=v, callback_data=f"gcol_rarity_{k}_{message.from_user.id}_1") for k, v in RARITIES.items()]
    markup.add(*buttons)
    try: bot.reply_to(message, "🕋 Explore all Registered Characters by Rarity:", reply_markup=markup, parse_mode="Markdown")
    except Exception: pass

@bot.message_handler(commands=['hfav'])
def cmd_hfav(message):
    if not check_chat_restrictions(message): return
    args = message.text.split()
    if len(args) < 2:
        try: bot.reply_to(message, "❌ Usage: /hfav [card_id]")
        except Exception: pass
        return
    try: search_id = int(args[1])
    except ValueError: return
    
    user_id = message.from_user.id
    db = load_db()
    
    user_inventory = db.get("inventories", {}).get(str(user_id), [])
    owns_card = any(c["id"] == search_id for c in user_inventory)
    if not owns_card:
        try: bot.reply_to(message, "❌ You do not own this card ID! Catch it first.")
        except Exception: pass
        return
        
    target_card = next((c for c in db["cards"] if c["id"] == search_id), None)
    if not target_card: return

    is_already_fav = db.get("favorites", {}).get(str(user_id)) == str(search_id)
    
    markup = InlineKeyboardMarkup()
    fav_btn = InlineKeyboardButton(text="❤️ Favorite [ON]" if is_already_fav else "🤍 Favorite", callback_data=f"fav_set_yes_{search_id}_{user_id}")
    unfav_btn = InlineKeyboardButton(text="💔 Unfavorite" if is_already_fav else "🖤 Unfavorite [OFF]", callback_data=f"fav_set_no_{search_id}_{user_id}")
    markup.add(fav_btn, unfav_btn)

    try: 
        send_card_media(message.chat.id, target_card, f"✨ Do you want to set <b>{target_card['name']}</b> as your Main Favorite profile?", reply_markup=markup, reply_to_message_id=message.message_id)
    except Exception: pass

@bot.message_handler(commands=['invan'])
def cmd_invan(message):
    if not check_chat_restrictions(message): return
    user_id = message.from_user.id
    real_name = message.from_user.first_name if message.from_user.first_name else "Hunter"
    page_content, total_pages, card_obj = build_inventory_page(user_id, page=1)
    
    if not page_content:
        try: bot.reply_to(message, "📭 Your inventory is entirely empty! Go catch some characters first.")
        except Exception: pass
        return

    caption_text = f"<b> 👤 {real_name}'s Recent Character - </b>\nPAGE: 1/{total_pages}\n\n{page_content}"
    markup = InlineKeyboardMarkup()
    if total_pages > 1:
        markup.add(InlineKeyboardButton(text="BACK 🧁", callback_data=f"invan_page_1_{user_id}"),
                   InlineKeyboardButton(text="NEXT 🧃", callback_data=f"invan_page_2_{user_id}"))

    try:
        if card_obj: 
            send_card_media(message.chat.id, card_obj, caption_text, reply_markup=markup, reply_to_message_id=message.message_id)
        else: 
            bot.send_message(message.chat.id, caption_text, reply_markup=markup, parse_mode="HTML", reply_to_message_id=message.message_id)
    except Exception: pass


# --- ADDITIONAL CUSTOM FEATURES ---

@bot.message_handler(commands=['cards'])
def cmd_cards_count(message):
    if message.from_user.id != ADMIN_ID:
        return
        
    db = load_db()
    all_registered_cards = db.get("cards", [])
    total_count = len(all_registered_cards)
    
    rarity_counts = {v: 0 for v in RARITIES.values()}
    for card in all_registered_cards:
        card_rarity = card.get("rarity")
        if card_rarity in rarity_counts:
            rarity_counts[card_rarity] += 1
            
    response_lines = [
        "🃏 <b>SYSTEM TOTAL REGISTERED CARDS</b> 🃏",
        f"<b>Total Base Cards Loaded:</b> {total_count}",
        "━━━━━━━━━━━━━━━━━━━━━"
    ]
    for rarity_display, count in rarity_counts.items():
        response_lines.append(f"• {rarity_display}: {count} cards")
    response_lines.append("━━━━━━━━━━━━━━━━━━━━━")
    
    try:
        bot.reply_to(message, "\n".join(response_lines), parse_mode="HTML")
    except Exception:
        pass

@bot.message_handler(commands=['pvptop'])
def cmd_pvptop(message):
    if not check_chat_restrictions(message): return
    db = load_db()
    pvp_wins = db.get("pvp_wins", {})
    
    sorted_winners = sorted(pvp_wins.items(), key=lambda x: x[1], reverse=True)
    top_10 = sorted_winners[:10]
    
    leaderboard_text = "⚔️ <b>TOP 10 PvP DUEL WINNERS</b> ⚔️\n"
    leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    for i in range(10):
        if i < len(top_10):
            uid, wins = top_10[i]
            user_inv = db.get("inventories", {}).get(uid, [])
            fallback = user_inv[-1].get("collector_name", f"Hunter_{uid}") if user_inv else f"Hunter_{uid}"
            real_name = get_telegram_name(uid, fallback)
            leaderboard_text += f"{i+1}. 👑 <b>{real_name}</b> — <code>{wins} Wins</code>\n"
        else:
            leaderboard_text += f"{i+1}. 🎐 Empty Slot\n"
            
    leaderboard_text += "━━━━━━━━━━━━━━━━━━━━━━━\n"
    leaderboard_text += "Challenge opponents using /attack to claim the top spot!"
    
    try:
        bot.reply_to(message, leaderboard_text, parse_mode="HTML")
    except Exception:
        pass

@bot.message_handler(commands=['attack'])
def cmd_attack_duel(message):
    if not check_chat_restrictions(message): 
        return
        
    if not message.reply_to_message:
        bot.reply_to(message, "❌ You must reply to the user you want to attack!")
        return
        
    challenger_id = message.from_user.id
    target_id = message.reply_to_message.from_user.id
    chat_id = message.chat.id
    
    if challenger_id == target_id:
        bot.reply_to(message, "❌ You cannot attack yourself!")
        return
        
    if message.reply_to_message.from_user.is_bot:
        bot.reply_to(message, "❌ You cannot challenge a bot!")
        return

    current_time = time.time()
    if challenger_id in pvp_cooldowns and current_time < pvp_cooldowns[challenger_id]:
        rem = int(pvp_cooldowns[challenger_id] - current_time)
        bot.reply_to(message, f"⏳ You must wait {rem} seconds before entering another PvP battle!")
        return
    if target_id in pvp_cooldowns and current_time < pvp_cooldowns[target_id]:
        rem = int(pvp_cooldowns[target_id] - current_time)
        bot.reply_to(message, f"⏳ The opponent is exhausted! Wait {rem} seconds before attacking them.")
        return

    if chat_id in pvp_battles:
        bot.reply_to(message, "❌ There is already an active dynamic duel ongoing or pending in this room!")
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: /attack [Your_Card_ID] (Reply to opponent's message)")
        return
        
    try:
        challenger_card_id = int(args[1])
    except ValueError:
        bot.reply_to(message, "❌ Card ID must be numeric format.")
        return

    db = load_db()
    challenger_inventory = db.get("inventories", {}).get(str(challenger_id), [])
    if not any(c["id"] == challenger_card_id for c in challenger_inventory):
        bot.reply_to(message, f"❌ You don't own any card with ID: {challenger_card_id}")
        return

    pvp_battles[chat_id] = {
        "status": "pending",
        "challenger_id": challenger_id,
        "challenger_card_id": challenger_card_id,
        "target_id": target_id,
        "timestamp": current_time
    }
    
    challenger_name = message.from_user.first_name
    target_name = message.reply_to_message.from_user.first_name if message.reply_to_message.from_user.first_name else "Hunter"
    
    challenge_msg = (
        f"⚔️ <b>BATTLE FIELD OPENED</b> ⚔️\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Challenger: {challenger_name} (Card ID: {challenger_card_id})\n"
        f"🎯 Target Opponent: {target_name}\n\n"
        f"👉 {target_name}, type <code>/trun [Your_Card_ID]</code> to accept the duel and strike back!\n"
        f"👉 Or type <code>/attleave</code> to decline the battle safely."
    )
    try:
        bot.reply_to(message, challenge_msg, parse_mode="HTML")
    except Exception:
        pass

@bot.message_handler(commands=['trun'])
def cmd_trun_response(message):
    if not check_chat_restrictions(message): 
        return
        
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in pvp_battles or pvp_battles[chat_id]["status"] != "pending":
        bot.reply_to(message, "❌ There are no pending duel challenges waiting for you here.")
        return
        
    battle_session = pvp_battles[chat_id]
    if battle_session["target_id"] != user_id:
        bot.reply_to(message, "❌ This challenge invitation was not meant for you! You cannot join.")
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: /trun [Your_Card_ID]")
        return
        
    try:
        target_card_id = int(args[1])
    except ValueError:
        bot.reply_to(message, "❌ Card ID must be numeric.")
        return

    db = load_db()
    target_inventory = db.get("inventories", {}).get(str(user_id), [])
    if not any(c["id"] == target_card_id for c in target_inventory):
        bot.reply_to(message, f"❌ You don't own any card with ID: {target_card_id}")
        return

    battle_session["status"] = "fighting"
    battle_session["target_card_id"] = target_card_id
    
    cards_list = db.get("cards", [])
    c_card = next((c for c in cards_list if c["id"] == battle_session["challenger_card_id"]), None)
    t_card = next((c for c in cards_list if c["id"] == target_card_id), None)
    
    c_name = c_card["name"] if c_card else f"Card #{battle_session['challenger_card_id']}"
    t_name = t_card["name"] if t_card else f"Card #{target_card_id}"
    c_rarity = c_card["rarity"] if c_card else "Unknown"
    t_rarity = t_card["rarity"] if t_card else "Unknown"

    intro_text = (
        f"🏟️ <b>BATTLE FIELD OPENED</b> 🏟️\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 <b>Challenger Card:</b> {c_name} [{c_rarity}]\n"
        f"🔵 <b>Opponent Card:</b> {t_name} [{t_rarity}]\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <i>Initializing collision telemetry mechanics...</i>"
    )
    
    try:
        status_msg = bot.send_message(chat_id, intro_text, parse_mode="HTML")
    except Exception:
        del pvp_battles[chat_id]
        return

    threading.Thread(target=process_pvp_battle_simulation, args=(chat_id, status_msg, battle_session, c_name, t_name)).start()

def process_pvp_battle_simulation(chat_id, status_msg, session, c_name, t_name):
    selected_actions = random.sample(BATTLE_ACTIONS, 4)
    
    for action in selected_actions:
        time.sleep(1.2)
        edit_text = (
            f"⚔️ <b>DUEL IN PROGRESS...</b> ⚔️\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔺 <code>{c_name}</code>  <b>VS</b>  <code>{t_name}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 {action}"
        )
        try:
            bot.edit_message_text(edit_text, chat_id=chat_id, message_id=status_msg.message_id, parse_mode="HTML")
        except Exception:
            pass

    time.sleep(1.2)
    
    challenger_won = random.choice([True, False])
    winner_id = session["challenger_id"] if challenger_won else session["target_id"]
    winner_card_name = c_name if challenger_won else t_name
    
    if not check_and_add_daily_claim(winner_id):
        try:
            bot.send_message(chat_id, f"⚠️ Daily Claim Limit Reached! Winner cannot claim reward card today.", reply_to_message_id=status_msg.message_id)
        except Exception: pass
        if chat_id in pvp_battles: del pvp_battles[chat_id]
        return

    db = load_db()
    system_cards = db.get("cards", [])
    
    reward_card = None
    if system_cards:
        rarity_weights = {
            "🪞 Supreme": 1, "✨ Catapharct": 3, "⚡ Crossverse": 5, "⚜️ Divine": 8,
            "💮 Mystical": 12, "🟡 Legendary": 16, "🟠 Rare": 20, "🟣 Uncommon": 25, "🔵 Common": 40
        }
        
        pool_cards = system_cards.copy()
        random.shuffle(pool_cards)
        
        weighted_choices = []
        for card in pool_cards:
            w = rarity_weights.get(card.get("rarity"), 10)
            weighted_choices.append((card, w))
            
        total_w = sum(x[1] for x in weighted_choices)
        r = random.uniform(0, total_w)
        upto = 0
        for card, w in weighted_choices:
            if upto + w >= r:
                reward_card = card
                break
            upto += w
            
        if not reward_card and pool_cards:
            reward_card = random.choice(pool_cards)

    if reward_card:
        str_winner_id = str(winner_id)
        if str_winner_id not in db["inventories"]:
            db["inventories"][str_winner_id] = []
        
        col_title = reward_card.get('collection', reward_card['name'] + " Collection")
        
        # Get dynamic winner name
        winner_inventory = db["inventories"].get(str_winner_id, [])
        w_name = winner_inventory[-1].get("collector_name", "Winner") if winner_inventory else "Winner"
        
        db["inventories"][str_winner_id].append({
            "id": reward_card["id"], 
            "name": reward_card["name"], 
            "rarity": reward_card["rarity"], 
            "collection": col_title, 
            "collector_name": w_name,
            "timestamp": time.time()
        })
        
        db["pvp_wins"][str_winner_id] = db["pvp_wins"].get(str_winner_id, 0) + 1
        save_db(db)

    end_cooldown = time.time() + 60
    pvp_cooldowns[session["challenger_id"]] = end_cooldown
    pvp_cooldowns[session["target_id"]] = end_cooldown

    victory_text = (
        f"🏆 <b>DUEL COMPLETE! CONGRATULATIONS!</b> 🏆\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 <b>Winner:</b> <a href='tg://user?id={winner_id}'>Player</a> with card <code>{winner_card_name}</code>!\n\n"
        f"🎁 <b>PvP Duel Reward Item:</b>\n"
        f"• Name: {reward_card['name'] if reward_card else 'N/A'}\n"
        f"• Rarity: {reward_card['rarity'] if reward_card else 'N/A'}\n"
        f"• Card ID: <code>{reward_card['id'] if reward_card else '0'}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ <i>Both duelists are locked in a 60-second cooldown phase.</i>"
    )
    try:
        bot.send_message(chat_id, victory_text, parse_mode="HTML")
    except Exception:
        pass
        
    if chat_id in pvp_battles:
        del pvp_battles[chat_id]

@bot.message_handler(commands=['attleave'])
def cmd_attleave_cancel(message):
    if not check_chat_restrictions(message): 
        return
        
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if chat_id not in pvp_battles:
        bot.reply_to(message, "❌ There is no active or pending battle session occurring in this chat.")
        return
        
    session = pvp_battles[chat_id]
    if session["status"] != "pending":
        bot.reply_to(message, "❌ The battle has already started! You cannot run away now!")
        return
        
    if session["target_id"] == user_id:
        del pvp_battles[chat_id]
        bot.reply_to(message, "🏃‍♂️ You declined the challenge invitation. The duel request has been cancelled.")
    else:
        bot.reply_to(message, "❌ Only the challenged target player can use /attleave to decline.")


# --- ADMIN CARD ADDING LOGIC (FORWARDED MESSAGES - PHOTOS & VIDEOS & GIFS) ---

@bot.message_handler(func=lambda msg: msg.from_user.id == ADMIN_ID and (msg.forward_date is not None or msg.forward_from is not None or msg.forward_from_chat is not None), content_types=['photo', 'video', 'animation', 'text'])
def handle_forwarded_messages(message):
    user_id = message.from_user.id
    if user_id not in admin_session:
        admin_session[user_id] = {"media_id": None, "media_type": None, "name": None, "button_shown": False}
        
    has_new_data = False
    
    # Process Media Types
    if message.content_type == 'photo':
        admin_session[user_id]["media_id"] = message.photo[-1].file_id
        admin_session[user_id]["media_type"] = "photo"
        has_new_data = True
        if message.caption:
            card_name = parse_name_from_text(message.caption)
            if card_name:
                admin_session[user_id]["name"] = card_name
                
    elif message.content_type == 'video':
        admin_session[user_id]["media_id"] = message.video.file_id
        admin_session[user_id]["media_type"] = "video"
        has_new_data = True
        if message.caption:
            card_name = parse_name_from_text(message.caption)
            if card_name:
                admin_session[user_id]["name"] = card_name
                
    elif message.content_type == 'animation':
        admin_session[user_id]["media_id"] = message.animation.file_id
        admin_session[user_id]["media_type"] = "animation"
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
    if session["media_id"] and session["name"]:
        if not session["button_shown"]:
            session["button_shown"] = True
            markup = InlineKeyboardMarkup(row_width=2)
            buttons = [InlineKeyboardButton(text=v, callback_data=f"set_rarity_{k}_{user_id}") for k, v in RARITIES.items()]
            markup.add(*buttons)
            try: bot.send_message(user_id, f"📊 Card media received ({session['media_type']}).\n📛 NAME: {session['name']}\n\nPlease choose Rarity:", reply_markup=markup, parse_mode="Markdown")
            except Exception: pass
    else:
        if has_new_data:
            try:
                if not session["media_id"]:
                    bot.send_message(user_id, "⚠️ Please forward the card IMAGE, VIDEO or GIF.", parse_mode="Markdown")
                elif not session["name"]:
                    bot.send_message(user_id, "⚠️ Please forward the text containing NAME :.", parse_mode="Markdown")
            except Exception: pass


# --- GENERAL MESSAGE COUNTER FOR SPAWN SYSTEM ---

@bot.message_handler(func=lambda msg: msg.chat.type in ['group', 'supergroup'], content_types=['text', 'photo', 'video', 'animation', 'sticker'])
def count_group_messages(message):
    chat_id = message.chat.id
    try:
        if message.from_user.id != ADMIN_ID:
            member = bot.get_chat_member(MAIN_GP_ID, message.from_user.id)
            if member.status in ['left', 'kicked']:
                return
    except Exception:
        return

    if chat_id not in group_message_counters:
        group_message_counters[chat_id] = 0
        
    group_message_counters[chat_id] += 1
    
    if group_message_counters[chat_id] >= 80:
        group_message_counters[chat_id] = 0
        db = load_db()
        if not db.get("cards", []):
            return
            
        random_card = random.choice(db["cards"])
        spawn_text = (
            "🍭 A character has spawned in the chat! 🎇\n"
            "Add this character to your harem using 🧃 /hbug name"
        )
        
        try:
            sent_spawn = send_card_media(chat_id, random_card, spawn_text)
            active_spawns[chat_id] = {
                "card_id": random_card["id"],
                "name": random_card["name"],
                "message_id": sent_spawn.message_id
            }
        except Exception as e:
            pass


# --- HELPER FUNCTIONS ---

def get_card_profile_text(card, db):
    total_hunted = 0
    inventories = db.get("inventories", {})
    for user_cards in inventories.values():
        for uc in user_cards:
            if uc["id"] == card["id"]:
                total_hunted += 1

    collection_name = card.get('collection', card['name'] + " Collection")
    return (
        f"🍄 ━ CHARACTER PROFILE ━ 🍄\n"
        f"───────────────────────\n"
        f"👤 <b>Name ::</b> {card['name']}\n\n"
        f"✨ <b>Rarity ::</b> {card['rarity']}\n\n"
        f"🏷️ <b>ID ::</b> {card['id']}\n\n"
        f"🕋 <b>Collection ::</b> {collection_name}\n"
        f"───────────────────────\n"
        f"<b>Global Hunt Times [ {total_hunted} ]</b>\n"
        f"───────────────────────"
    )

def get_top_hunters_text(card, db):
    dynamic_hunters = {}
    inventories = db.get("inventories", {})
    
    for user_id, user_cards in inventories.items():
        count = sum(1 for uc in user_cards if uc["id"] == card["id"])
        if count > 0:
            fallback = user_cards[-1].get("collector_name", f"Hunter_{user_id}")
            real_name = get_telegram_name(user_id, fallback)
            dynamic_hunters[real_name] = dynamic_hunters.get(real_name, 0) + count

    sorted_hunters = sorted(dynamic_hunters.items(), key=lambda x: x[1], reverse=True)[:10]
    hunter_lines = []
    for i in range(10):
        if i < len(sorted_hunters):
            user, count = sorted_hunters[i]
            hunter_lines.append(f"🐙 : <b>{user}</b> - ({count}x)")
        else:
            hunter_lines.append("🐙 :")
            
    return f"TOP 10 HUNTERS OF\n THIS CHARACTER\n───────────────────────\n{card['name']}\n---------------------------------------------------------\n" + "\n".join(hunter_lines) + "\n───────────────────────"

def execute_hunt_process(message, target_card, is_test=False):
    user_id = message.from_user.id
    collection_name = target_card.get('collection', target_card['name'] + " Collection")
    hunt_text = (
        f"🍄 Character Has Spawned Here 🍄\n\n"
        f"<b>Let's Hunt Character Now ◆◆◆</b>\n"
        f"───────────────────────\n"
        f"👤 <b>Name ::</b> {target_card['name']}\n"
        f"------------------------------------------\n"
        f"✨ <b>Rarity ::</b> {target_card['rarity']}\n"
        f"------------------------------------------\n"
        f"🏷️ <b>ID ::</b> {target_card['id']}\n"
        f"------------------------------------------\n"
        f"🕋 <b>Collection ::</b> {collection_name}\n"
        f"───────────────────────"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="HUNT ➽", callback_data=f"player_hunt_{target_card['id']}_{user_id}_{'1' if is_test else '0'}"),
               InlineKeyboardButton(text="SKIP ⟱", callback_data=f"player_skip_{target_card['id']}_{user_id}_{'1' if is_test else '0'}"))
    
    try:
        sent_msg = send_card_media(message.chat.id, target_card, hunt_text, reply_markup=markup, reply_to_message_id=message.message_id)
        active_hunt_sessions[user_id] = {"chat_id": message.chat.id, "message_id": sent_msg.message_id, "hunting": False}
    except Exception: pass

def build_inventory_page(user_id, page=1):
    db = load_db()
    str_user_id = str(user_id)
    user_cards = db.get("inventories", {}).get(str_user_id, [])
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

    items_per_page = 25  # High-performance paging to support thousands of cards securely
    total_pages = (len(formatted_lines) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * items_per_page
    page_content = "\n".join(formatted_lines[start_idx : start_idx + items_per_page])

    card_obj = None
    fav_id = db.get("favorites", {}).get(str_user_id)
    
    if fav_id:
        card_obj = next((c for c in db["cards"] if c["id"] == int(fav_id)), None)

    if not card_obj and user_cards:
        last_card_id = user_cards[-1]["id"]
        card_obj = next((c for c in db["cards"] if c["id"] == last_card_id), None)

    return page_content, total_pages, card_obj


# --- MAIN EXECUTION WITH KEEP ALIVE ---
if __name__ == "__main__":
    print("Initializing Server Keep-Alive Telemetry...")
    keep_alive()  # Flask Web Server ကို နောက်ကွယ်မှာ အလုပ်လုပ်ခိုင်းလိုက်သည်
    
    print("Character Hunter Engine is now running perfectly...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Polling crashed: {e}. Restarting in 5 seconds...")
            time.sleep(5)

