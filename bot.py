import logging
import re
import aiohttp
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
import time

API_TOKEN = 'Telegram Token from BotFather'

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# User sessions to track promo codes and their expiration
user_sessions = {}

# Асинхронная функция для создания сессии и получения CSRF токена
async def create_session_and_get_csrf_token():
    url = "https://t2-gifts.ru/"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                page_content = await response.text()
                csrf_token = re.search(r'name="csrf-token" content="(.*?)"', page_content)
                if csrf_token:
                    cookies = session.cookie_jar.filter_cookies(url)
                    time.sleep(0.2)
                    return csrf_token.group(1), cookies, session
                else:
                    raise Exception("CSRF токен не найден")
            else:
                raise Exception(f"Ошибка при получении токена, код ответа: {response.status}")

# Асинхронная функция для получения подарка
async def get_gift(csrf_token, cookies):
    url = "https://t2-gifts.ru/getgift"
    
    payload = {'_token': csrf_token}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=payload, headers=headers, cookies=cookies) as response:
            if response.status != 200:
                raise Exception(f"Ошибка запроса: {response.status} - {await response.text()}")
            
            try:
                gift_data = await response.json()
            except Exception as e:
                raise Exception(f"Невозможно распознать ответ сервера как JSON: {await response.text()}")

            if gift_data.get("success"):
                return {
                    "white_line": gift_data["gift"]["white_line"],
                    "blue_line": gift_data["gift"]["blue_line"],
                    "promo_hash": gift_data["promocode"]["hash"]
                }
            else:
                raise Exception(f"Не удалось получить подарок: {gift_data}")

# Асинхронная функция для отправки промокода
async def send_gift(promo_hash, phone, csrf_token, cookies):
    url = "https://t2-gifts.ru/sendgift"
    data = {
        "hash": promo_hash,
        "variant": "yes",
        "phone": phone,
        "_token": csrf_token
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data, cookies=cookies) as response:
            if response.status != 200:
                raise Exception(f"Ошибка запроса: {response.status} - {await response.text()}")
            result = await response.json()
            return result.get("success", False)

# Function to format phone number
def format_phone_number(phone):
    if len(phone) == 11 and phone.startswith('7'):
        return f'+7 {phone[1:4]} {phone[4:7]} {phone[7:]}'
    else:
        return None

# Command to start the bot
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    # Create a button to get a gift
    keyboard = InlineKeyboardMarkup(row_width=1)
    get_gift_button = InlineKeyboardButton("Получить подарок 🎁", callback_data="get_gift")
    keyboard.add(get_gift_button)

    await message.reply("Привет! Нажмите на кнопку ниже, чтобы получить подарок 🎁.", reply_markup=keyboard)

# Handle the "get_gift" button press
@dp.callback_query_handler(lambda c: c.data == "get_gift")
async def get_gift_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    try:
        csrf_token, cookies, _ = await create_session_and_get_csrf_token()
        gift = await get_gift(csrf_token, cookies)
        # Store user session
        user_sessions[user_id] = {
            "promo_hash": gift["promo_hash"],
            "csrf_token": csrf_token,
            "expires_at": asyncio.get_event_loop().time() + 30,  # 30 seconds expiration
            "cookies": cookies
        }

        # Create inline buttons for replacing gift or sending promo code
        keyboard = InlineKeyboardMarkup(row_width=2)
        replace_gift_button = InlineKeyboardButton("Заменить подарок 🔄", callback_data="replace_gift")
        enter_phone_button = InlineKeyboardButton("Отправить СМС с промо ☎️", callback_data="enter_phone")
        keyboard.add(replace_gift_button, enter_phone_button)

        await bot.send_message(user_id, f"Ваш подарок: {gift['white_line']}\nУсловия: {gift['blue_line']}", reply_markup=keyboard)

    except Exception as e:
        await bot.send_message(user_id, f"Ошибка: {e}")

# Handle the "replace_gift" button press
@dp.callback_query_handler(lambda c: c.data == "replace_gift")
async def replace_gift_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    if user_id not in user_sessions:
        await bot.send_message(user_id, "Сначала запросите подарок.")
        return

    try:
        csrf_token = user_sessions[user_id]["csrf_token"]
        cookies = user_sessions[user_id]["cookies"]
        new_gift = await get_gift(csrf_token, cookies)

        # Update the session with the new gift
        user_sessions[user_id]["promo_hash"] = new_gift["promo_hash"]
        user_sessions[user_id]["expires_at"] = asyncio.get_event_loop().time() + 30

        # Edit the existing message with a temporary text
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=callback_query.message.message_id,
            text="Обновление подарка...",
            reply_markup=callback_query.message.reply_markup  # Keep the same buttons
        )

        # Then update the message with the new gift information
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=callback_query.message.message_id,
            text=f"Новый подарок: {new_gift['white_line']}\nУсловия: {new_gift['blue_line']}",
            reply_markup=callback_query.message.reply_markup  # Keep the same buttons
        )

    except Exception as e:
        await bot.send_message(user_id, f"Ошибка: {e}")



# Handle the "enter_phone" button press
@dp.callback_query_handler(lambda c: c.data == "enter_phone")
async def enter_phone_callback(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id

    if user_id not in user_sessions:
        await bot.send_message(user_id, "Сначала запросите подарок.")
        return

    session = user_sessions[user_id]
    if asyncio.get_event_loop().time() > session["expires_at"]:
        await bot.send_message(user_id, "Промокод истек! Запросите новый.")
        del user_sessions[user_id]
        return

    # Ask the user to input their phone number
    await bot.send_message(user_id, "Введите номер телефона в формате 79999999999.")

# Handle phone number input
@dp.message_handler(lambda message: re.fullmatch(r'\d{11}', message.text))
async def handle_phone_number(message: types.Message):
    user_id = message.from_user.id

    if user_id not in user_sessions:
        await message.reply("Сначала запросите подарок.")
        return

    session = user_sessions[user_id]
    if asyncio.get_event_loop().time() > session["expires_at"]:
        await message.reply("Промокод истек! Запросите новый.")
        del user_sessions[user_id]
        return

    phone_number = format_phone_number(message.text)
    if not phone_number:
        await message.reply("Некорректный формат номера. Введите номер в формате 79999999999.")
        return

    try:
        promo_hash = session["promo_hash"]
        csrf_token = session["csrf_token"]
        cookies = session["cookies"]
        success = await send_gift(promo_hash, phone_number, csrf_token, cookies)

        if success:
            await message.reply("Промокод успешно отправлен!")
            del user_sessions[user_id]
        else:
            await message.reply("Ошибка отправки промокода. Возможно, по этому номеру уже был отправлен подарок.")

    except Exception as e:
        await message.reply(f"Ошибка: {e}")

# Handle invalid phone number input
@dp.message_handler(lambda message: not re.fullmatch(r'\d{11}', message.text))
async def invalid_input(message: types.Message):
    await message.reply("Введите номер телефона в формате 79999999999.")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
