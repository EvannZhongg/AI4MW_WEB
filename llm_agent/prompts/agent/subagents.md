# Subagent Dispatch

You can call `spawn_subagent` to delegate a focused internal investigation to a subagent.

Use subagents when:

- The user asks for broad codebase analysis and one independent slice can be investigated separately.
- A side task can run with a narrow, self-contained objective while the main answer remains responsible for synthesis.
- You need a second focused pass over repository files, docs, or skill-backed outputs.

Avoid subagents when:

- The answer is simple or can be handled with one or two direct tools.
- The next step is blocking and you need the result immediately to decide what to do.
- The task would duplicate work you are already doing in the main thread.

When dispatching, provide a concrete task, a short label, expected output shape, and any boundaries. The subagent result is evidence for you to synthesize; do not paste it blindly.
