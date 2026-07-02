from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)
from concierge.materials import extract_text, MaterialError, CAPABILITIES
from concierge.models import MaterialType

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


def build_application(orchestrator, token, material_service=None):
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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("why", why))
    app.add_handler(CommandHandler("forget", forget))
    app.add_handler(CommandHandler("sync", sync))
    app.add_handler(CommandHandler("upload", upload))
    app.add_handler(CommandHandler("materials", materials))
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.CaptionRegex(r"^/upload"), upload_document
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app
