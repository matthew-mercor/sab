"""Convert a kimi-code agent wire.jsonl into the package trajectory format.

  python tooling/kimi_wire_to_trajectory.py <wire.jsonl> <out trajectory_steps.json>

Output: a JSON list, one entry per loop step (0-based "step"), matching
results/kimi-k3/recon-living-room/*/trajectory_steps.json:
  {"step": N, "assistant_text": str|null, "tool_calls": [{"name", "arguments"}]}
Extensions, kept separate so the base schema stays intact:
  - "assistant_thinking": the model's reasoning content, when present
  - "api_failure": for steps whose LLM request failed (turn.step.retrying events):
    {"error", "message", "failed_attempt_logged", "time_utc"} with
    assistant_text=null and tool_calls=[] — failed steps are represented, not omitted,
    and no responses are fabricated for them.

Faithfulness audit (printed, aborts on mismatch): the number of assistant messages
consumed must equal the number of steps without an API failure, and every dumped
conversation message must be consumed exactly once. Step membership is derived from
the messageCount of consecutive llm.request events (a failed step adds 0 messages).
"""
import json
import sys
import datetime


def load(path):
    return [json.loads(l) for l in open(path)]


def main_legacy(wire_path, out_path):
    """Legacy-schema wires (2026-10-15 era): llm.request records carry kind="loop"
    (and mid-loop context compactions log extra llm.request records with
    kind="compaction" and no turnStep), and each step's content is recorded
    directly in context.append_loop_event records (step.begin / content.part /
    tool.call / tool.result / step.end, all carrying an explicit 1-based step).

    Step membership therefore comes from the loop events themselves — immune to
    the messageCount rebase that context.apply_compaction causes — and is
    cross-checked against the session's end-of-turn agent.message.appended dump
    (a compaction-agnostic append log: 1 leading user + one assistant per
    productive step + one tool message per call)."""
    events = load(wire_path)

    loop_reqs = [e for e in events if e.get("type") == "llm.request" and e.get("kind") == "loop"]
    comp_reqs = [e for e in events if e.get("type") == "llm.request" and e.get("kind") == "compaction"]
    applies = [e for e in events if e.get("type") == "context.apply_compaction"]
    unknown = [e for e in events if e.get("type") == "llm.request"
               and e.get("kind") not in ("loop", "compaction")]
    if unknown:
        raise SystemExit(f"audit failed: {len(unknown)} llm.request records with unexpected kind")
    if len(comp_reqs) != len(applies):
        raise SystemExit(f"audit failed: {len(comp_reqs)} compaction requests but "
                         f"{len(applies)} applied compactions")
    steps = [int(e["turnStep"].split(".")[1]) for e in loop_reqs]
    n_steps = steps[-1] if steps else 0
    if steps != list(range(1, n_steps + 1)):
        raise SystemExit("audit failed: request steps not 1..N")

    retries = [e for e in events if e.get("type") == "turn.step.retrying"]
    if retries:
        raise SystemExit("audit failed: legacy mode does not handle turn.step.retrying yet")

    begins, ends = {}, {}
    parts, calls = {}, {}
    n_tool_results = 0
    for e in events:
        if e.get("type") != "context.append_loop_event":
            continue
        ev = e["event"]
        t = ev.get("type")
        if t == "tool.result":
            # tool.result records carry parentUuid/toolCallId, not step
            n_tool_results += 1
            continue
        s = ev.get("step")
        if not isinstance(s, int) or not 1 <= s <= n_steps:
            raise SystemExit(f"audit failed: loop event with out-of-range step {s!r}")
        if t == "step.begin":
            begins[s] = begins.get(s, 0) + 1
        elif t == "step.end":
            ends[s] = ends.get(s, 0) + 1
        elif t == "content.part":
            parts.setdefault(s, []).append(ev["part"])
        elif t == "tool.call":
            calls.setdefault(s, []).append(ev)
        else:
            raise SystemExit(f"audit failed: unknown loop event type {t!r}")
    if sorted(begins) != list(range(1, n_steps + 1)) or sorted(ends) != list(range(1, n_steps + 1)) \
            or any(v != 1 for v in begins.values()) or any(v != 1 for v in ends.values()):
        raise SystemExit("audit failed: step.begin/step.end not exactly once per step 1..N")
    n_tool_calls = sum(len(v) for v in calls.values())
    if n_tool_calls != n_tool_results:
        raise SystemExit(f"audit failed: {n_tool_calls} tool.call vs {n_tool_results} tool.result")

    # Mid-loop injected user messages (e.g. compaction handoff): context.append_message
    # records after the first loop request. Attach to the step after whose request they
    # appear (same convention as the main mode).
    first_req_pos = next(i for i, e in enumerate(events)
                         if e.get("type") == "llm.request" and e.get("kind") == "loop")
    req_pos = [i for i, e in enumerate(events)
               if e.get("type") == "llm.request" and e.get("kind") == "loop"]
    injected = {}  # step (1-based) -> list of message dicts
    for i, e in enumerate(events):
        if e.get("type") != "context.append_message" or i < first_req_pos:
            continue
        after = max(s for p, s in zip(req_pos, steps) if p < i)
        m = e.get("message", {})
        injected.setdefault(after, []).append(m["message"] if "message" in m else m)

    # End-of-turn session dump cross-check (compaction-agnostic append log).
    dump = [e["message"]["message"] for e in events if e.get("type") == "agent.message.appended"]
    di = 0
    while di < len(dump) and dump[di].get("role") != "assistant":
        di += 1
    out = []
    for s in range(1, n_steps + 1):
        text = "\n".join(p.get("text", "") for p in parts.get(s, []) if p.get("type") == "text")
        think = "\n".join(p.get("think", "") for p in parts.get(s, []) if p.get("type") == "think")
        step_calls = [{"name": c.get("name"), "arguments": c.get("args") or {}}
                      for c in calls.get(s, [])]
        if not text and not step_calls:
            raise SystemExit(f"audit failed: step {s} produced no content")
        if di >= len(dump) or dump[di].get("role") != "assistant":
            raise SystemExit(f"audit failed: dump has no assistant message for step {s}")
        d = dump[di]
        di += 1
        d_text = "\n".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")
        d_calls = d.get("toolCalls") or []
        if len(d_calls) != len(step_calls):
            raise SystemExit(f"audit failed: step {s} has {len(step_calls)} loop-event tool calls "
                             f"but {len(d_calls)} in the dump")
        for dc, lc in zip(d_calls, step_calls):
            if dc.get("name") != lc["name"]:
                raise SystemExit(f"audit failed: step {s} tool name mismatch "
                                 f"({dc.get('name')} vs {lc['name']})")
            try:
                d_args = json.loads(dc.get("arguments") or "{}")
            except json.JSONDecodeError:
                d_args = {"_raw": dc.get("arguments")}
            if d_args != lc["arguments"]:
                raise SystemExit(f"audit failed: step {s} tool arguments mismatch for {lc['name']}")
        if d_text.strip() != text.strip():
            raise SystemExit(f"audit failed: step {s} assistant text mismatch between "
                             f"loop events and dump")
        while di < len(dump) and dump[di].get("role") == "tool":
            di += 1
        entry = {"step": s - 1, "assistant_text": text or "", "tool_calls": step_calls}
        if think.strip():
            entry["assistant_thinking"] = think
        if s in injected:
            entry["injected_user_messages"] = [
                "\n".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
                for m in injected[s]]
        out.append(entry)
    if di != len(dump):
        raise SystemExit(f"audit failed: {len(dump) - di} dumped messages left unconsumed")

    print(f"steps={n_steps} productive={len(out)} api_failures=0 "
          f"assistant_consumed={len(out)} messages_consumed={di}/{len(dump)} "
          f"compactions={len(comp_reqs)} injected_mid_loop={sum(len(v) for v in injected.values())}")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"wrote {out_path}")


def main():
    wire_path, out_path = sys.argv[1], sys.argv[2]
    events = load(wire_path)
    if any(e.get("type") == "llm.request" and "turnStep" not in e for e in events):
        main_legacy(wire_path, out_path)
        return

    reqs = []  # (step:int, messageCount, time)
    retries = {}  # step -> list of failure dicts
    msgs = []  # conversation messages in append order (each event is authoritative;
    # identical repeated messages are real history and must all be consumed)
    injected = []  # (step after whose request the message appears, message)
    for e in events:
        t = e.get("type")
        if t == "llm.request":
            reqs.append((int(e["turnStep"].split(".")[1]), e["messageCount"], e.get("time")))
        elif t == "turn.step.retrying":
            retries.setdefault(e["step"], []).append({
                "error": e.get("errorName"),
                "message": e.get("errorMessage"),
                "failed_attempt_logged": e.get("failedAttempt"),
                "time_utc": datetime.datetime.fromtimestamp(e["time"] / 1000, datetime.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ") if e.get("time") else None,
            })
        elif t == "agent.message.appended":
            msgs.append(e["message"]["message"])
        elif t == "context.append_message" and reqs:
            # Mid-loop injected message (e.g. a user-role system reminder). It counts
            # toward messageCount but is NOT part of the end-of-turn agent.message
            # dump, so it must be re-inserted at its conversation position: it sits
            # between request N and N+1, after step N's messages, i.e. at conversation
            # index messageCount(N+1) - 1. Pre-loop context messages (initial prompt
            # reminders) are also absent from the dump; they form a constant prefix
            # offset = messageCount(1) - (leading non-assistant dump messages).
            m = e.get("message", {})
            injected.append((reqs[-1][0], m["message"] if "message" in m else m))

    n_steps = reqs[-1][0]
    assert [s for s, _, _ in reqs] == list(range(1, n_steps + 1)), "request steps not 1..N"

    if injected:
        # re-insert mid-loop injected messages at their conversation positions
        n_leading = 0
        while n_leading < len(msgs) and msgs[n_leading].get("role") != "assistant":
            n_leading += 1
        prefix_offset = reqs[0][1] - n_leading  # undumped pre-loop context messages
        mc_by_step = {s: mc for s, mc, _ in reqs}
        inserts = []  # (conversation index, message)
        for step_after, m in injected:
            if step_after + 1 in mc_by_step:
                conv_idx = mc_by_step[step_after + 1] - 1
            else:
                conv_idx = None  # injected after the final request: append at end
            inserts.append((conv_idx, m))
        for conv_idx, m in sorted(inserts, key=lambda x: (x[0] is None, x[0])):
            if conv_idx is None:
                msgs.append(m)
            else:
                # conv_idx counts every conversation message, earlier injected ones
                # included; inserting in ascending order, each prior insert sits at
                # its own omitted position, so the two corrections cancel and the
                # dump position is simply conv_idx - prefix_offset (no shift term —
                # the old +shift skipped one slot per prior injected message and
                # failed the audit on wires with two or more mid-loop reminders).
                msgs.insert(conv_idx - prefix_offset, m)

    out = []
    mi = 0
    # skip leading non-assistant messages (user prompt etc.)
    while mi < len(msgs) and msgs[mi].get("role") != "assistant":
        mi += 1

    for i, (step, mc, _t) in enumerate(reqs):
        nxt = reqs[i + 1][1] if i + 1 < len(reqs) else None
        failed = step in retries and (nxt is None or nxt == mc)
        if failed:
            for f in retries[step]:
                out.append({"step": step - 1, "assistant_text": None, "tool_calls": [],
                            "api_failure": f})
            continue
        if mi >= len(msgs) or msgs[mi].get("role") != "assistant":
            raise SystemExit(f"audit failed: no assistant message for step {step}")
        m = msgs[mi]
        mi += 1
        text = "\n".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
        think = "\n".join(c.get("think", "") for c in m.get("content", []) if c.get("type") == "think")
        calls = []
        for tc in m.get("toolCalls") or []:
            try:
                args = json.loads(tc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.get("arguments")}
            calls.append({"name": tc.get("name"), "arguments": args})
        n_tool_msgs = 0
        while mi < len(msgs) and msgs[mi].get("role") == "tool":
            mi += 1
            n_tool_msgs += 1
        injected = []
        while mi < len(msgs) and msgs[mi].get("role") == "user":
            injected.append("\n".join(c.get("text", "") for c in msgs[mi].get("content", [])
                                      if c.get("type") == "text"))
            mi += 1
        entry = {"step": step - 1, "assistant_text": text or "", "tool_calls": calls}
        if think.strip():
            entry["assistant_thinking"] = think
        if injected:
            entry["injected_user_messages"] = injected
        out.append(entry)
        if nxt is not None and mc + 1 + n_tool_msgs + len(injected) != nxt:
            raise SystemExit(f"audit failed: step {step} consumed {1 + n_tool_msgs + len(injected)} messages "
                             f"but messageCount says {nxt - mc}")

    if mi != len(msgs):
        raise SystemExit(f"audit failed: {len(msgs) - mi} dumped messages left unconsumed")
    n_fail = sum(1 for o in out if o.get("api_failure"))
    n_ok = n_steps - n_fail
    print(f"steps={n_steps} productive={n_ok} api_failures={n_fail} "
          f"assistant_consumed={n_ok} messages_consumed={mi}/{len(msgs)}")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
