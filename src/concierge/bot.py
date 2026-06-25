from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)

CONSENT = (
    "👋 Olá! Sou o concierge estratégico deste projeto.\n"
    "A partir de agora vou monitorar as conversas para manter o canvas "
    "atualizado e alertar sobre incoerências estratégicas.\n"
    "Use /status para ver o canvas, /why para entender alertas, "
    "e /forget para apagar todos os dados."
)


def handle_start(orchestrator, chat_id, chat_name):
    orchestrator.storage.get_or_create_project(chat_id, chat_name)
    return CONSENT


def handle_status(orchestrator, chat_id):
    pid = orchestrator.storage.get_or_create_project(chat_id, str(chat_id))
    blocks = orchestrator.storage.get_blocks(pid)
    if not blocks:
        return "Canvas ainda vazio. Continue a conversa — eu cuido do resto."
    lines = [f"*{b['block_name']}*: {b['content']}" for b in blocks]
    return "📋 Canvas atual:\n" + "\n".join(lines)


def handle_why(orchestrator, chat_id):
    pid = orchestrator.storage.get_or_create_project(chat_id, str(chat_id))
    last = orchestrator.storage.last_intervention(pid)
    if last is None:
        return "Nenhuma intervenção ainda."
    return f"Último alerta: {last['reason']} (confiança {last['confidence']:.0%})"


def handle_forget(orchestrator, chat_id):
    pid = orchestrator.storage.get_or_create_project(chat_id, str(chat_id))
    orchestrator.storage.delete_project(pid)
    return "🗑️ Todos os dados deste projeto foram apagados."


def handle_sync(orchestrator, chat_id):
    pid = orchestrator.storage.get_or_create_project(chat_id, str(chat_id))
    added = orchestrator.run_sync(pid)
    return f"🔄 Sync concluído. {added} itens novos."


def build_application(orchestrator, token):
    app = Application.builder().token(token).build()

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        await update.message.reply_text(handle_start(orchestrator, chat.id, chat.title or str(chat.id)))

    async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            handle_status(orchestrator, update.effective_chat.id), parse_mode="Markdown"
        )

    async def why(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(handle_why(orchestrator, update.effective_chat.id))

    async def forget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(handle_forget(orchestrator, update.effective_chat.id))

    async def sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(handle_sync(orchestrator, update.effective_chat.id))

    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        msg = update.message
        user = msg.from_user
        author = (user.username or user.first_name) if user else "unknown"
        pid = orchestrator.ingest_message(
            chat.id, chat.title or str(chat.id), msg.message_id,
            author, msg.text, msg.date.timestamp(),
        )
        alert = orchestrator.check_coherence(pid, msg.message_id, msg.text)
        if alert:
            await msg.reply_text(alert)
        if orchestrator.should_sync(pid):
            orchestrator.run_sync(pid)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("why", why))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("sync", sync))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app
