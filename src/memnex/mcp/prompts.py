"""MCP Prompts for Memnex.

Prompts are reusable templates the host application can pull and inject
into its LLM at runtime. They encode best-practice guidance for using
Memnex correctly so every adopter doesn't reinvent it.

Three prompts:

- ``memory-writer``    — when and how to call ``memory_write``
- ``memory-reader``    — how to fold ``memory_read`` context into a turn
- ``hallucination-check`` — wrap ``memory_trace`` to verify agent claims
"""
from __future__ import annotations

from typing import Any

# --- prompt registry -------------------------------------------------------

PROMPTS: list[dict[str, Any]] = [
    {
        "name": "memory-writer",
        "description": (
            "System guidance for an agent that should write to Memnex. "
            "Teaches when to write (per sub-intent, not at end of "
            "conversation), the 5 fact types, the entities convention, "
            "and why structured `facts` is preferred over `raw_text`."
        ),
        "arguments": [
            {
                "name": "agent_role",
                "description": (
                    "What the agent does (e.g. 'support agent', 'voice "
                    "concierge', 'clinic intake'). Personalizes the examples."
                ),
                "required": False,
            },
        ],
    },
    {
        "name": "memory-reader",
        "description": (
            "System guidance for an agent that should read from Memnex at "
            "the start of every turn. Teaches how to call memory_read, "
            "where to put the returned context, and what NOT to do with it."
        ),
        "arguments": [
            {
                "name": "target_format",
                "description": (
                    "Channel-shaped format: voice | whatsapp | web | sms | "
                    "app. Defaults to 'web'."
                ),
                "required": False,
            },
        ],
    },
    {
        "name": "hallucination-check",
        "description": (
            "Wraps memory_trace to verify a draft agent reply against "
            "stored memories before sending. Returns instructions to soften "
            "or ask if the draft asserts facts not in memory."
        ),
        "arguments": [
            {
                "name": "agent_output",
                "description": "The draft reply about to be sent to the user.",
                "required": True,
            },
        ],
    },
]


# --- prompt bodies ---------------------------------------------------------

def _memory_writer(agent_role: str) -> list[dict[str, str]]:
    body = f"""You are a {agent_role} with persistent memory provided by the Memnex MCP server.

WHEN TO WRITE
Call `memory_write` the moment a durable fact crystallizes in the conversation:

- A declared intent ("wants to cancel order XYZ")
- A stated preference ("prefers morning calls")
- An issue raised ("item arrived damaged")
- A resolution reached ("refund processed via UPI")
- A profile attribute ("name is Vikram, based in Bangalore")

DO NOT write greetings, acknowledgements, filler, or facts already on file.
Write *as facts appear*, not as one batch at the end. Mid-session
disconnects are common; only written facts survive.

A typical 20-turn conversation produces 3-5 writes, not 1 or 20.

HOW TO WRITE
Always prefer the structured `facts` parameter (a list of objects), never
`raw_text`. Each fact object has:

  fact:       a single concise statement, plain English
  type:       one of intent | preference | issue | resolution | profile
  entities:   list of "type:value" identifiers (e.g. ["order:XYZ"])
  confidence: 0.0-1.0 (use 0.9+ when stated explicitly)

Example call after the user says "I want to cancel order XYZ — it never arrived":

  memory_write(
    user_id="u_123",
    facts=[
      {{
        "fact": "Wants to cancel order XYZ",
        "type": "intent",
        "entities": ["order:XYZ"],
        "confidence": 0.95
      }},
      {{
        "fact": "Order XYZ never arrived",
        "type": "issue",
        "entities": ["order:XYZ"],
        "confidence": 0.9
      }}
    ]
  )

The `entities` field is what enables Memnex's conflict detector. Two facts
that share an entity (e.g. both mention "order:XYZ") and contradict each
other will be detected and the older one superseded. Always include the
relevant identifiers — order numbers, SKUs, drug names, account IDs.

Read `memnex://schema/fact-types` for the full taxonomy reference.
"""
    return [{"role": "user", "content": body}]


def _memory_reader(target_format: str) -> list[dict[str, str]]:
    body = f"""You are an agent backed by Memnex memory. Before responding to the user,
fetch what we already know about them.

AT TURN START
Call `memory_read` exactly once with:

  memory_read(user_id=<the user's id>, target_format="{target_format}", token_budget=1500)

The response is a `context` string, pre-formatted for the {target_format} channel
(short bullets for voice/SMS, richer markdown for web).

WHERE TO PUT IT
Insert the `context` string into your system prompt under a heading like:

  ## What you already know about this user
  {{context}}

Do NOT echo the context to the user verbatim. It's background knowledge
for you, not a script. Reference relevant items naturally ("I see you've
been having trouble with order XYZ — let's fix that").

WHAT NOT TO DO
- Do NOT invent facts that aren't in `context`. If you need to know
  something, ask the user.
- Do NOT call `memory_read` more than once per turn — it's a hot path.
- Do NOT call `memory_search` unless you're looking up something
  specific the user mentioned (a particular order, a past complaint).
  For general context, `memory_read` is the right call.

CROSS-CHANNEL HANDOFF
If a user previously talked to a colleague on WhatsApp and is now on a
voice call with you, the context will already include the WhatsApp
history. That's the whole point — treat it as continuous.
"""
    return [{"role": "user", "content": body}]


def _hallucination_check(agent_output: str) -> list[dict[str, str]]:
    body = f"""Before sending the following draft reply to the user, verify it against
stored memory.

DRAFT REPLY:
\"\"\"
{agent_output}
\"\"\"

STEP 1: Call `memory_trace(user_id=<the user's id>, agent_output=<the draft>)`.
The response contains a `hits` list — memory IDs that could plausibly
have produced the assertions in the draft.

STEP 2:
- If `hits` is non-empty AND covers the user-specific claims in the draft,
  send the draft as-is.
- If `hits` is empty AND the draft asserts user-specific facts ("your
  order #4521", "your usual preference for X"), the draft is a
  hallucination. Either:
    (a) Soften: rephrase as a question ("Is order #4521 the one you mean?").
    (b) Stop: ask the user to confirm before proceeding.
- If `hits` partially covers the draft, edit out the unsupported claims
  and resend STEP 1 with the trimmed draft.

GENERAL FACTS
Statements like "Refunds typically take 5-7 business days" are general
knowledge, not user facts. They don't need to trace back to memory.
Only verify claims that are about THIS user.
"""
    return [{"role": "user", "content": body}]


# --- dispatcher ------------------------------------------------------------

_DISPATCHERS = {
    "memory-writer": lambda a: _memory_writer(a.get("agent_role", "support agent")),
    "memory-reader": lambda a: _memory_reader(a.get("target_format", "web")),
    "hallucination-check": lambda a: _hallucination_check(a.get("agent_output", "")),
}


def get_prompt_messages(name: str, arguments: dict[str, str]) -> list[dict[str, str]]:
    """Return a list of ``{role, content}`` messages for the given prompt."""
    fn = _DISPATCHERS.get(name)
    if fn is None:
        raise KeyError(name)
    return fn(arguments)
