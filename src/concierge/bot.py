from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)
from concierge.materials import extract_text, MaterialError, CAPABILITIES
from concierge.models import MaterialType
from concierge.stylist import PRESETS

TYPE_LABELS = {
    MaterialType.CANVAS_GUIDE: "guia de canvas",
    MaterialType.VALIDATION_GUIDE: "guia de validação",
    MaterialType.METHODOLOGY: "metodologia",
    MaterialType.CUSTOM_FRAMEWORK: "framework próprio",
    MaterialType.GENERIC: "material geral",
}

UPLOAD_HELP = (
    "Envie um arquivo (PDF, TXT, MD, DOCX) com a legenda /upload, "
    "responda a um arquivo com /upload, ou cole o texto: /upload <texto>."
)

CONSENT = (
    "👋 Olá! Sou o concierge estratégico deste projeto.\n"
    "A partir de agora vou monitorar as conversas para manter o canvas "
    "atualizado e alertar sobre incoerências estratégicas.\n"
    "Use /status para ver o canvas, /why para entender alertas, "
    "e /forget para apagar todos os dados."
)

NOT_STARTED = (
    "⚠️ Este projeto ainda não foi ativado. "
    "Rode /start primeiro para que eu possa começar a acompanhar as conversas."
)


def handle_start(orchestrator, chat_id, chat_name):
    orchestrator.storage.get_or_create_project(chat_id, chat_name)
    return CONSENT


def handle_status(orchestrator, chat_id):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    blocks = orchestrator.storage.get_blocks(pid)
    if not blocks:
        return "Canvas ainda vazio. Continue a conversa — eu cuido do resto."
    lines = [f"*{b['block_name']}*: {b['content']}" for b in blocks]
    return "📋 Canvas atual:\n" + "\n".join(lines)


def handle_why(orchestrator, chat_id):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    last = orchestrator.storage.last_intervention(pid)
    if last is None:
        return "Nenhuma intervenção ainda."
    return f"Último alerta: {last['reason']} (confiança {last['confidence']:.0%})"


def handle_forget(orchestrator, chat_id):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    if orchestrator.knowledge is not None:
        orchestrator.knowledge.delete(pid)
    orchestrator.storage.delete_project(pid)
    return "🗑️ Todos os dados deste projeto foram apagados."


def handle_sync(orchestrator, chat_id):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    added = orchestrator.run_sync(pid)
    return f"🔄 Sync concluído. {added} itens novos."


def _announce(mtype, chunks):
    return (
        f"📚 Detectei: {TYPE_LABELS[mtype]} → {CAPABILITIES[mtype]}\n"
        f"({chunks} trechos indexados)"
    )


def handle_upload_text(orchestrator, material_service, chat_id, text):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    if not text.strip():
        return UPLOAD_HELP
    mtype, chunks = material_service.add_material(pid, "colado.txt", text)
    return _announce(mtype, chunks)


def handle_upload_document(orchestrator, material_service, chat_id, filename, data):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    try:
        text = extract_text(filename, data)
    except MaterialError as e:
        return f"⚠️ {e}"
    mtype, chunks = material_service.add_material(pid, filename, text)
    return _announce(mtype, chunks)


def handle_materials(orchestrator, chat_id):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    docs = orchestrator.storage.list_knowledge_docs(pid)
    if not docs:
        return "Nenhum material ainda. " + UPLOAD_HELP
    lines = [
        f"📚 {d['filename']} — {TYPE_LABELS[MaterialType(d['material_type'])]}"
        f" → {CAPABILITIES[MaterialType(d['material_type'])]}"
        for d in docs
    ]
    return "Materiais de referência:\n" + "\n".join(lines)


PERSONALITY_HELP = (
    "Estilo atual: {current}\n\n"
    "Presets: " + ", ".join(sorted(PRESETS)) + "\n"
    "Use /personality <preset>, /personality <descrição livre> "
    "ou /personality reset para limpar."
)

MAX_PERSONALITY = 300


def handle_personality(orchestrator, stylist, chat_id, args):
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return NOT_STARTED
    text = (args or "").strip()
    if not text:
        current = orchestrator.storage.get_personality(pid) or "nenhuma definida"
        return PERSONALITY_HELP.format(current=current)
    if text.lower() == "reset":
        orchestrator.storage.set_personality(pid, "")
        return "🎭 Personalidade removida. Volto ao tom neutro."
    truncated = False
    if text.lower() in PRESETS:
        instruction = PRESETS[text.lower()]
        label = text.lower()
    else:
        instruction = text[:MAX_PERSONALITY]
        truncated = len(text) > MAX_PERSONALITY
        label = "personalizada"
    orchestrator.storage.set_personality(pid, instruction)
    reply = f"🎭 Personalidade definida ({label})! A partir de agora falo assim."
    if stylist is not None:
        reply = stylist.restyle(reply, instruction)
    if truncated:
        reply += "\n(instrução truncada em 300 caracteres)"
    return reply


def _is_mention(text, bot_username, reply_to_is_bot):
    if reply_to_is_bot:
        return True
    if not bot_username:
        return False
    return f"@{bot_username.lower()}" in (text or "").lower()


def _styled(orchestrator, stylist, chat_id, text):
    if stylist is None:
        return text
    pid = orchestrator.storage.get_project(chat_id)
    if pid is None:
        return text
    personality = orchestrator.storage.get_personality(pid)
    if not personality:
        return text
    return stylist.restyle(text, personality)


def build_application(orchestrator, token, material_service=None, stylist=None):
    app = Application.builder().token(token).build()

    async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        reply = handle_start(orchestrator, chat.id, chat.title or str(chat.id))
        await update.message.reply_text(_styled(orchestrator, stylist, chat.id, reply))

    async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        reply = handle_status(orchestrator, chat_id)
        await update.message.reply_text(
            _styled(orchestrator, stylist, chat_id, reply), parse_mode="Markdown"
        )

    async def why(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        reply = handle_why(orchestrator, chat_id)
        await update.message.reply_text(_styled(orchestrator, stylist, chat_id, reply))

    async def forget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(handle_forget(orchestrator, update.effective_chat.id))

    async def sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        reply = handle_sync(orchestrator, chat_id)
        await update.message.reply_text(_styled(orchestrator, stylist, chat_id, reply))

    async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        msg = update.message
        user = msg.from_user
        author = (user.username or user.first_name) if user else "unknown"
        pid = orchestrator.ingest_message(
            chat.id, chat.title or str(chat.id), msg.message_id,
            author, msg.text, msg.date.timestamp(),
        )
        reply_to_is_bot = bool(
            msg.reply_to_message
            and msg.reply_to_message.from_user
            and msg.reply_to_message.from_user.id == ctx.bot.id
        )
        if _is_mention(msg.text, ctx.bot.username, reply_to_is_bot):
            reply = orchestrator.respond_mention(pid, msg.message_id, msg.text)
            if reply:
                await msg.reply_text(reply)
        else:
            alert = orchestrator.check_coherence(pid, msg.message_id, msg.text)
            if alert:
                await msg.reply_text(alert)
            else:
                contribution = orchestrator.participate(pid, msg.message_id, msg.text)
                if contribution:
                    await msg.reply_text(contribution)
        if orchestrator.should_sync(pid):
            orchestrator.run_sync(pid)

    MAX_UPLOAD = 20 * 1024 * 1024

    async def upload(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if material_service is None:
            await update.message.reply_text("Upload não está configurado.")
            return
        doc = None
        if update.message.reply_to_message and update.message.reply_to_message.document:
            doc = update.message.reply_to_message.document
        if doc is not None:
            if doc.file_size and doc.file_size > MAX_UPLOAD:
                await update.message.reply_text("⚠️ Arquivo acima do limite de 20 MB.")
                return
            tg_file = await ctx.bot.get_file(doc.file_id)
            data = bytes(await tg_file.download_as_bytearray())
            reply = handle_upload_document(
                orchestrator, material_service, chat_id, doc.file_name or "arquivo", data
            )
        else:
            text = " ".join(ctx.args) if ctx.args else ""
            reply = handle_upload_text(orchestrator, material_service, chat_id, text)
        await update.message.reply_text(reply)

    async def upload_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        # document sent WITH caption starting with /upload
        if material_service is None:
            return
        doc = update.message.document
        if doc.file_size and doc.file_size > MAX_UPLOAD:
            await update.message.reply_text("⚠️ Arquivo acima do limite de 20 MB.")
            return
        tg_file = await ctx.bot.get_file(doc.file_id)
        data = bytes(await tg_file.download_as_bytearray())
        reply = handle_upload_document(
            orchestrator, material_service, update.effective_chat.id,
            doc.file_name or "arquivo", data,
        )
        await update.message.reply_text(reply)

    async def materials(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            handle_materials(orchestrator, update.effective_chat.id)
        )

    async def personality(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        args = " ".join(ctx.args) if ctx.args else ""
        await update.message.reply_text(
            handle_personality(orchestrator, stylist, update.effective_chat.id, args)
        )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("why", why))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("sync", sync))
    app.add_handler(CommandHandler("upload", upload))
    app.add_handler(CommandHandler("materials", materials))
    app.add_handler(CommandHandler("personality", personality))
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.CaptionRegex(r"^/upload"), upload_document
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app
