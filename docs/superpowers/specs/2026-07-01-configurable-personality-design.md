# Feature C: Configurable Personality — Design

**Data:** 2026-07-01
**Contexto:** O bot hoje responde com templates fixos e alertas em tom neutro. Esta feature permite que cada grupo defina a "voz" do bot — presets prontos ou descrição livre — tornando a interação mais humana sem tocar nos dados estratégicos.

---

## 1. Proposta

- **`/personality`** (sem argumentos) → mostra o estilo atual e os presets disponíveis.
- **`/personality <preset>`** → aplica um preset.
- **`/personality <texto livre>`** → o texto vira a instrução de estilo (ex: "fale como um sócio experiente e levemente sarcástico").
- A personalidade se aplica **somente às interações conversacionais** (alertas do guardião e respostas de comandos). O conteúdo do canvas e dos itens estratégicos permanece neutro — são dados de referência, não conversa.

## 2. Presets

`PRESETS: dict[str, str]` em `stylist.py`:

| Nome | Instrução de estilo |
|---|---|
| `mentor` | "Fale como um mentor direto e experiente: sem rodeios, aponte o risco e sugira o próximo passo concreto." |
| `coach` | "Fale como um coach motivacional: energético, celebre o progresso antes de apontar desvios." |
| `zen` | "Fale como um conselheiro zen: calmo, socrático — prefira perguntas que levem a equipe a enxergar o problema." |
| `formal` | "Fale como um consultor formal: analítico, impessoal, tom de relatório executivo." |

Texto que não casa com um preset (case-insensitive) é tratado como instrução livre.

## 3. Persistência

- `projects` ganha coluna `personality TEXT NOT NULL DEFAULT ''` (vazio = sem personalidade; comportamento atual).
- `storage.py`: `set_personality(project_id, text)` e `get_personality(project_id) -> str`.

## 4. Aplicação do estilo — duas vias

### 4.1 Alertas do guardião (injeção de prompt, custo zero)

`Guardian.check(...)` ganha parâmetro `style: str = ""`. Quando não-vazio, o SYSTEM prompt recebe um adendo: *"Write the 'reason' field in this voice: <style>"*. O alerta já nasce na voz escolhida — nenhuma chamada extra de LLM. O `Orchestrator.check_coherence` lê `get_personality(project_id)` e repassa.

### 4.2 Respostas de comandos (Stylist, 1 chamada leve e opcional)

Novo módulo `src/concierge/stylist.py`:

```python
class Stylist:
    def __init__(self, llm): ...
    def restyle(self, text: str, personality: str) -> str:
        # personality vazio -> retorna text imediatamente (sem LLM)
        # LLM falhou/JSON inválido -> retorna text original (nunca quebra comando)
        # senão -> texto reescrito na voz, mesmo conteúdo factual
```

Usa `call_validated` com schema `StyledText(text: str)`. O SYSTEM instrui: reescreva mantendo TODO o conteúdo factual (números, nomes de blocos, comandos citados), mudando apenas o tom.

Aplicado em `bot.py` nas respostas de `/status`, `/sync`, `/why` e no aviso de consentimento do `/start`. Não aplicado em `/forget` (confirmação de apagamento deve ser inequívoca) nem nas mensagens de erro/gate (`NOT_STARTED`).

## 5. Comando `/personality`

Handler puro `handle_personality(orchestrator, chat_id, args) -> str`:

- Sem args → estilo atual (ou "nenhum definido") + lista de presets + exemplo de texto livre.
- `reset` → limpa (`set_personality(pid, "")`).
- Nome de preset → aplica a instrução do preset e confirma na nova voz (via Stylist).
- Qualquer outro texto → vira instrução livre (limite 300 caracteres, truncado com aviso).
- Exige `/start` (portão de consentimento existente).

## 6. Tratamento de erros

- LLM indisponível no `restyle` → devolve o texto original (silencioso).
- Personalidade nunca afeta: conteúdo de `strategic_items`, blocos do canvas, decisões do guardião (o *julgamento* de contradição e a confiança são independentes do estilo — só a redação do `reason` muda).

## 7. Testes

- `Stylist`: personality vazio → sem chamada de LLM; LLM fake válido → texto reescrito; LLM erro → texto original.
- `Guardian.check` com `style` → instrução presente no SYSTEM prompt enviado (inspeção de `llm.calls`); sem style → prompt inalterado.
- `handle_personality`: listar, aplicar preset, texto livre, reset, gate de `/start`, truncamento.
- Persistência: set/get em banco em memória; default `''`.

## 8. Dependências novas

Nenhuma.

## 9. Fora do escopo

- Personalidade por usuário (é por projeto/grupo).
- Estilo no conteúdo do canvas/itens (decisão explícita de mantê-los neutros).
- Vozes por idioma — a instrução herda o idioma em que for escrita.
