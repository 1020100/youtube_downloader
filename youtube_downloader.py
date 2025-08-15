import os
import logging
import re
from pytubefix import YouTube
from pytubefix.exceptions import PytubeFixError
from telegram import Update, ReplyParameters, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Конфигурация ---
BOT_TOKEN = "8030116568:AAEqrB9q-T5VU-FPdlL366EUO2VuZJxpDQE"
# Лимит размера файла в байтах (50 МБ)
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024

# комментраий для Артема. моего боса
# Новый коммтарий для босса - проверка мержа
# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Вспомогательные функции ---
def get_resolution_sort_key(stream):
    """Ключ для сортировки потоков по разрешению (от большего к меньшему)."""
    if stream.resolution:
        # '720p' -> 720
        return int(stream.resolution[:-1])
    return 0 # Потоки без разрешения считаем самыми низкокачественными

# --- Функции Бота ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение по команде /start."""
    user = update.effective_user
    await update.message.reply_html(
        f"Привет, {user.mention_html()}!\n\nОтправь мне ссылку на видео с YouTube, и я попробую его скачать и прислать тебе.",
    )

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает ссылку на YouTube, скачивает и отправляет видео или ссылки на него."""
    url = update.message.text
    message = await update.message.reply_text("Получил ссылку. Начинаю обработку...", reply_parameters=ReplyParameters(message_id=update.message.message_id))
    temp_file_path = None # Инициализируем переменную

    try:
        yt = YouTube(url)

        # Фильтруем и сортируем потоки по разрешению (от лучшего к худшему)
        streams = sorted(
            yt.streams.filter(progressive=True, file_extension='mp4'),
            key=get_resolution_sort_key,
            reverse=True
        )

        # Ищем подходящий по размеру поток для отправки
        selected_stream = None
        for stream in streams:
            if stream.filesize <= TELEGRAM_FILE_LIMIT:
                selected_stream = stream
                break

        # Если нашли подходящий поток, скачиваем и отправляем его
        if selected_stream:
            await message.edit_text(f'Нашел подходящую версию ({selected_stream.resolution}). Скачиваю "{yt.title}"...')

            temp_file_path = selected_stream.download()
            logger.info(f"Видео скачано: {temp_file_path}")

            if os.path.getsize(temp_file_path) > TELEGRAM_FILE_LIMIT:
                await message.edit_text("Ошибка: после скачивания файл оказался больше лимита Telegram.")
                os.remove(temp_file_path)
                return

            await message.edit_text("Загружаю видео в Telegram...")

            with open(temp_file_path, 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=video_file,
                    caption=yt.title,
                    write_timeout=120
                )
            await message.delete()
        
        # Если все потоки слишком большие, отправляем ссылки
        else:
            keyboard = []
            for stream in streams:
                size_mb = round(stream.filesize / 1024 / 1024)
                button_text = f"{stream.resolution} ({size_mb} MB)"
                button = [InlineKeyboardButton(text=button_text, url=stream.url)]
                keyboard.append(button)

            if not keyboard:
                await message.edit_text("Не нашел доступных для скачивания версий этого видео.")
                return

            reply_markup = InlineKeyboardMarkup(keyboard)
            await message.edit_text(
                f'Видео "{yt.title}" слишком большое для отправки в Telegram.\n\n' 
                'Вы можете скачать его напрямую по ссылкам ниже:',
                reply_markup=reply_markup
            )

    except PytubeFixError as e:
        logger.error(f"Ошибка PytubeFix: {e}", exc_info=True)
        error_message = "Произошла ошибка при обработке ссылки. Возможно, видео недоступно, имеет возрастные ограничения или ссылка некорректна."
        if "age restricted" in str(e).lower():
            error_message = "Не удалось скачать видео. Похоже, на него установлено возрастное ограничение."
        elif "video unavailable" in str(e).lower():
            error_message = "Это видео недоступно."
        await message.edit_text(error_message)

    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка: {e}", exc_info=True)
        await message.edit_text("Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.")

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
            logger.info(f"Временный файл удален: {temp_file_path}")

def main() -> None:
    """Запускает бота."""
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))

    youtube_regex = r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(youtube_regex), handle_youtube_link))

    async def non_youtube_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
            return
        await update.message.reply_text("Это не похоже на ссылку YouTube. Пожалуйста, пришлите корректную ссылку.")

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, non_youtube_message))

    application.run_polling()

if __name__ == "__main__":
    main()
