# LSuite × Claude Financial Services — Integration Plan

Yes, it's possible. LSuite already does the data work (parse, store, categorise); the financial services agents add AI reasoning on top of that data. The fit is direct — three agents map straight onto existing LSuite workflows.

---

## What Maps

| FSI Agent | LSuite Hook | What it adds |
|---|---|---|
| **GL Reconciler** | `bridge/` — bulk ops, categorisation | Finds uncategorised breaks, traces root cause, suggests ERPNext account |
| **Statement Auditor** | `gmail/` — parsed statements | Reviews a parsed statement for anomalies before you sync |
| **Month-End Closer** | `main/` — dashboard | Variance commentary, accrual prompts from transaction data |

The other agents (Pitch, KYC, LBO) have no hook here — skip them.

---

## Architecture

Two integration modes. Pick one or both:

### Mode A — Inline (simpler, no new infrastructure)
Add a `claude_agents` Django app. Views call the Anthropic `/v1/messages` API directly, passing the relevant skill prompt + transaction data as context. No managed agent deployment needed.

```
LSuite Django
  └── claude_agents/
        ├── skills/         ← copied from FSI repo: gl-reconciler, statement-auditor, month-end-closer
        ├── services.py     ← Anthropic SDK calls
        ├── views.py        ← endpoints triggered from bridge/gmail/main
        └── urls.py
```

### Mode B — Managed Agents (full deployment)
Deploy the three agents via `deploy-managed-agent.sh`, store their `agent_id`s in env vars, call `/v1/agents/sessions` from Django. More powerful (subagent delegation, steering events), more infrastructure.

**Recommend Mode A first** — gets value in one sprint, Mode B is an upgrade path.

---

## Phased Plan

### Phase 1 — GL Reconciler in `bridge/`
**Goal:** On the bulk operations page, a button runs the GL Reconciler over all uncategorised transactions and suggests categories + ERPNext accounts.

- New app: `claude_agents/`
- Copy skill: `plugins/agent-plugins/gl-reconciler/skills/` → `claude_agents/skills/gl-reconciler/`
- `services.py` — `GLReconcilerService.suggest(transactions: QuerySet)` — batches up to 50 transactions, sends to Claude with the skill prompt, returns `[{transaction_id, suggested_category, erpnext_account, confidence, reason}]`
- New view: `POST /claude-agents/gl-reconcile/` — calls service, stages suggestions (does not auto-apply)
- UI: table of suggestions with Accept / Reject per row, bulk Accept All
- Suggestions stored in a new `CategorySuggestion` model so you can review before committing

**New model:**
```python
class CategorySuggestion(models.Model):
    transaction = models.ForeignKey(BankTransaction, on_delete=models.CASCADE)
    suggested_category_name = models.CharField(max_length=100)
    suggested_erpnext_account = models.CharField(max_length=200, blank=True)
    confidence = models.CharField(max_length=20)  # high / medium / low
    reason = models.TextField()
    accepted = models.BooleanField(null=True)      # None = pending
    created_at = models.DateTimeField(auto_now_add=True)
```

---

### Phase 2 — Statement Auditor in `gmail/`
**Goal:** After a PDF is parsed, a button runs the Statement Auditor and flags anomalies (duplicates, gaps, unusual amounts) before ERPNext sync.

- Copy skill: `plugins/agent-plugins/statement-auditor/skills/`
- `services.py` — `StatementAuditorService.audit(statement: EmailStatement)` — sends all transactions for the statement + bank name, gets back a structured audit report
- New view: `POST /claude-agents/audit-statement/<pk>/`
- Audit report stored against the statement (new `StatementAuditReport` model or a JSON field on `EmailStatement`)
- UI: audit badge on statement detail page, expandable findings list

---

### Phase 3 — Month-End Closer in `main/`
**Goal:** Dashboard widget that generates variance commentary and flags missing accruals for the current month.

- Copy skill: `plugins/agent-plugins/month-end-closer/skills/`
- `services.py` — `MonthEndCloserService.run(user, month, year)` — aggregates category totals vs prior month, sends to Claude, returns commentary + accrual checklist
- Cached result stored in a `MonthEndReport` model (regenerate on demand)
- UI: collapsible card on `main/index.html`

---

## New Files Summary

```
LSuite/
  claude_agents/
    __init__.py
    apps.py
    models.py           ← CategorySuggestion, StatementAuditReport, MonthEndReport
    services.py         ← GLReconcilerService, StatementAuditorService, MonthEndCloserService
    views.py
    urls.py
    skills/
      gl-reconciler/    ← copied from FSI repo
      statement-auditor/
      month-end-closer/
  LSuite/
    settings.py         ← add 'claude_agents' to INSTALLED_APPS, ANTHROPIC_API_KEY env var
    urls.py             ← path('claude-agents/', include('claude_agents.urls'))
```

One migration for the three new models.

---

## Environment Variables to Add

```
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_MAX_TOKENS=2000
GL_RECONCILER_BATCH_SIZE=50    # transactions per API call
```

---

## What It Does Not Touch

- Existing categorisation logic in `bridge/services.py` — AI suggestions are staged separately, not a replacement
- ERPNext sync — unchanged, suggestions only apply after you accept them
- Gmail OAuth / PDF parsing — Statement Auditor runs after parsing, doesn't change the parse pipeline

---

## Dependencies to Add

```
anthropic>=0.40.0
```

That's the only new dependency. The FSI skill files are markdown — no extra packages.
