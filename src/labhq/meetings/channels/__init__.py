"""Meeting channels: meetings mirrored live to chat threads, owner replies read back.

The bridge between meetings and chat adapters. Posts go through the `chat_outbox` table and a
loop of the always-on program, so a chat outage never stops a meeting (plan §2.1, §12).

Kept free of imports: `labhq.db.models` imports `models` from here, and the meeting engine
imports the database models, so a re-export would make the import order circular.
"""
