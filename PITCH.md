# Concierge Estratégico — Pitch

> **Um membro a mais no time da startup.** Um bot de Telegram que transforma as
> conversas da equipe em uma base estratégica viva — mantém o Business Model
> Canvas atualizado, alerta quando a discussão contradiz o que foi validado,
> participa da conversa como um colega e mostra tudo num canvas visual dentro
> do próprio Telegram.

---

## O problema

Equipes de startup usam frameworks (Business Model Canvas, hipóteses, personas)
para planejar — mas **ninguém os mantém atualizados**. As decisões continuam
acontecendo nas conversas do dia a dia, enquanto os documentos congelam.
Resultado: decisões sobre hipóteses superadas, retrabalho e perda de foco.

## A solução

Um bot que **vive no grupo da equipe** e fecha o ciclo completo:

1. **Registra** — extrai decisões, hipóteses, premissas e riscos das mensagens,
   e gerencia o ciclo de vida (validada → superada → descartada).
2. **Atualiza** — o Business Model Canvas se reconstrói sozinho, sempre a
   partir do que vale *agora*.
3. **Protege** — o guardião alerta quando alguém contradiz uma decisão
   validada: *"isso bate de frente com a hipótese que validamos com 5 clientes"*.
4. **Participa** — mencione o bot e ele responde como um sócio experiente;
   de vez em quando (com critério rígido de relevância) ele mesmo conecta
   ideias, traz o que dizem os manuais da equipe, faz a pergunta incômoda
   ou sintetiza a discussão.
5. **Mostra** — `/canvas` abre um Mini App dentro do Telegram com a grade
   visual do BMC, no celular e no desktop.

## O diferencial

Não é "IA que resume conversas". É **governança estratégica contínua com
personalidade**:

- **Aprende o método da equipe** — suba o manual de validação e o guardião
  passa a cobrar experimentos; suba o framework da casa e ele vira lente de
  todas as análises. Cada material destrava uma capacidade.
- **Fala na voz que a equipe escolher** — mentor direto, coach, conselheiro
  zen, consultor formal, ou qualquer personalidade descrita em uma frase.
- **Uma voz por mensagem, zero ruído** — pré-filtros sem custo, limiares de
  confiança e cooldown: conversa trivial nunca gasta uma chamada de API nem
  gera spam.

## Por que confiar

- **Consentimento** — só age após `/start`, avisando que monitora.
- **Transparência** — `/why` explica cada alerta; `/forget` apaga tudo
  (banco e vetores).
- **Nunca quebra a conversa** — falha de IA vira silêncio, não erro no grupo.

## Status

✅ **Produto completo e rodando**: extração + canvas vivo + guardião +
materiais tipados (RAG) + personalidade + participante + Mini App visual
(validado em mobile e desktop).
✅ **OpenAI ou Gemini** por variável de ambiente.
✅ **133 testes** automatizados, TDD, ~1.800 linhas em 25 módulos focados.

## Stack

Python · python-telegram-bot · OpenAI / Gemini · SQLite (WAL) · ChromaDB ·
FastAPI · Telegram Mini Apps

---

> *"As ferramentas de estratégia morrem porque vivem longe da conversa.
> Nós colocamos a estratégia dentro da conversa — com memória, critério
> e uma voz própria."*
