"""The in-product assistant: "Ask Churnary".

Three modules, with the safety properties deliberately separated:

* ``tools.py`` — the only things the assistant can do. Every tool scopes its
  query by ``business_id`` in SQL. The tenant boundary is never a prompt
  instruction, because a prompt instruction is a suggestion and a WHERE clause
  is not.
* ``intents.py`` — a pure, deterministic responder. No I/O, no LLM. It answers
  the handful of questions owners actually ask most, and it is what runs when
  the model is unreachable, so the assistant degrades to "less fluent" rather
  than "broken". Same role ``social/inbox_rules.py`` plays for the inbox.
* ``agent.py`` — the loop that lets the model choose tools, with the parse
  discipline used everywhere else in this codebase (strict JSON, defensive
  parse, bounded steps, fall back).

Two rules hold across all three:

**The assistant never sends anything.** Its one write tool drafts a campaign
into the existing pending-approval queue. Approve-to-send is the product
default, and a chat box that could text 400 customers on a misread sentence
would be the single most dangerous surface in the product.

**Company-brain retrieval goes through ``brain.list_public()``.** Never
``list_all()``. A chat reply is owner-facing, but copy drafted from it is not,
and the gate is only load-bearing if nothing routes around it.
"""
