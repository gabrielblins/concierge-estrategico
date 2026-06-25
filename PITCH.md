# Concierge Estratégico — Pitch

> **Memória estratégica viva para startups.** Um bot de Telegram que transforma
> as conversas da equipe em um Business Model Canvas sempre atualizado — e alerta
> quando as discussões contradizem o que já foi decidido.

---

## O problema

Equipes de startup usam frameworks (Business Model Canvas, hipóteses, personas)
para planejar — mas **ninguém os mantém atualizados**. As decisões continuam
acontecendo nas conversas do dia a dia, enquanto os documentos congelam no
passado. Resultado: decisões baseadas em hipóteses já superadas, retrabalho e
perda de foco.

## A solução

Um bot de Telegram que **acompanha as conversas** e:

1. **Extrai** decisões, hipóteses, premissas, riscos e tarefas das mensagens.
2. **Atualiza** o Business Model Canvas automaticamente.
3. **Intervém** quando alguém contradiz uma decisão ou hipótese já validada.

## O diferencial

Não é "IA que resume conversas". É um **sistema de governança estratégica
contínua**: ele compara o que a equipe discute com o que já foi decidido,
atualiza os artefatos vivos e age como **guardião da coerência** do projeto.

## Como funciona (modo híbrido)

- **Passivo** — em lote, a cada N mensagens: extrai itens → atualiza o canvas.
- **Ativo** — por mensagem, mas seletivo: um pré-filtro barato descarta conversa
  trivial; só propostas/decisões chegam ao LLM; alerta apenas com confiança alta.

## Por que confiar

- **Consentimento** — só age após `/start`, e avisa que está monitorando.
- **Transparência** — `/why` explica cada alerta; `/forget` apaga tudo.
- **Sem ruído nem custo desnecessário** — pré-filtro + lote + limiar de confiança.

## Status

✅ **MVP funcional** — extração, canvas vivo, guardião, RAG, transparência.
✅ Funciona com **OpenAI ou Gemini** (troca por variável de ambiente).
✅ **61 testes** automatizados, todos passando. Construído com TDD.

## Stack

Python · python-telegram-bot · OpenAI / Google Gemini · SQLite · ChromaDB · Pydantic

---

> *"Transforma conversas de Telegram em uma base estratégica viva — canvas,
> hipóteses e decisões sempre atualizados — e alerta a equipe quando as
> discussões se afastam da estratégia definida."*
