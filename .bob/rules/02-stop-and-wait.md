# Stop-and-wait rule

**Do not start the next step until Alami explicitly approves.**

After every step report:
- Stop.
- Wait for a reply.
- "keep going", "looks good", or similar = approval to proceed.
- Feedback = address it before moving on.
- Direction change = revise the plan before implementing.

**Do not batch multiple steps in one session.** One step per conversation.
Each step gets its own context window, its own commit, its own report.

This is not optional. A polluted context window is the fastest way to burn
the 40-Bobcoin budget. Step isolation is the mitigation.
