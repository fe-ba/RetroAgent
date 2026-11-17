"""The context builder: system context, skills, tool sets, state message and context budget
(spec/context-loading.md, ADR-0021, ADR-0028).

Every function here receives what it needs and returns text, messages, definitions or numbers. None of them calls a
model, starts a server or prints.
"""
