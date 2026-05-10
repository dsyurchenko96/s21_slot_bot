from telegram import CallbackQuery, InlineKeyboardMarkup, Update

from s21_slot_bot.app.models import CustomContext


async def render_message(
    update: Update | CallbackQuery,
    context: CustomContext,
    text: str,
    kb: InlineKeyboardMarkup = InlineKeyboardMarkup([]),
) -> None:
    chat_id = update.message.chat_id
    msg_id = await ensure_wizard_message(chat_id, context)

    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=text,
        reply_markup=kb,
    )


async def ensure_wizard_message(chat_id: int, context: CustomContext) -> int:
    msg_id = context.chat_data.wizard_msg_id
    if msg_id:
        return msg_id

    m = await context.bot.send_message(chat_id, "...", reply_markup=InlineKeyboardMarkup([]))
    context.chat_data.wizard_msg_id = m.message_id
    return m.message_id
