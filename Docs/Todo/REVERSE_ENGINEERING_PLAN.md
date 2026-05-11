# FSI Agents — Reverse Engineering Plan
## Replace Anthropic Managed Agents with Groq + Django

The FSI repo has two layers:
- **Content layer** — skill markdown, agent system prompts, commands. Portable, keep as-is.
- **Infrastructure layer** — `/v1/agents`, `/v1/skills`, Cowork plugin runtime, `deploy-managed-agent.sh`. Anthropic-only. This is what we rebuild.

---

## What Each Anthropic Piece Does → What Replaces It

| Anthropic | What it does | Our replacement |
|---|---|---|
| `/v1/agents` | Stores named agents with system prompt + skills | `AgentDefinition` model in Django |
| `/v1/skills` | Uploads skill zips, returns `skill_id` | Read SKILL.md from disk at runtime |
| `agents/sessions` | Multi-turn conversation with an agent | `AgentSession` model + Groq chat history |
| `sessions.steer()` | Route to a different agent mid-session | `handoff()` in our orchestrator |
| `callable_agents` | Depth-1 subagent delegation | Subagent runner that calls Groq with leaf prompt |
| Cowork plugin | UI that fires agents | Django views wired to the same logic |
| `check.py` | Lints manifests | We keep this, it's pure Python |
| `sync-agent-skills.py` | Copies skills between folders | We keep this too |

---

## New Django App: `ai_agents/`

```
LSuite/
  ai_agents/
    __init__.py
    apps.py
    models.py          ← AgentDefinition, AgentSession, AgentMessage, SubagentCall
    registry.py        ← loads agent + skill markdown from disk into DB
    skill_loader.py    ← reads SKILL.md files, builds system prompt
    groq_client.py     ← thin wrapper: chat(), stream(), structured_output()
    orchestrator.py    ← runs an agent session, handles handoffs + subagents
    subagent.py        ← depth-1 leaf worker runner
    views.py           ← trigger endpoints for bridge/, gmail/, main/
    urls.py
    skills/            ← copied from FSI repo
      gl-reconciler/
      statement-auditor/
      month-end-closer/
    agents/            ← copied from FSI repo  
      gl-reconciler.md
      statement-auditor.md
      month-end-closer.md
```

---

## Models

```python
# ai_agents/models.py

class AgentDefinition(models.Model):
    slug = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    system_prompt = models.TextField()       # loaded from agents/<slug>.md
    skills_loaded = models.JSONField(default=list)  # list of skill names bundled
    model = models.CharField(max_length=100, default='llama-3.3-70b-versatile')
    max_tokens = models.IntegerField(default=2000)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AgentSession(models.Model):
    STATUS = [('active','Active'),('done','Done'),('failed','Failed'),('handed_off','Handed Off')]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    agent = models.ForeignKey(AgentDefinition, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS, default='active')
    context_data = models.JSONField(default=dict)   # arbitrary payload passed at start
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class AgentMessage(models.Model):
    ROLES = [('system','system'),('user','user'),('assistant','assistant')]
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class SubagentCall(models.Model):
    session = models.ForeignKey(AgentSession, on_delete=models.CASCADE, related_name='subagent_calls')
    subagent_slug = models.CharField(max_length=100)
    input_payload = models.JSONField()
    output = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## Skill Loader

Replaces `/v1/skills`. Reads markdown from disk, concatenates into the system prompt.

```python
# ai_agents/skill_loader.py
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / 'skills'
AGENTS_DIR = Path(__file__).parent / 'agents'


def load_agent_system_prompt(slug: str) -> str:
    agent_md = AGENTS_DIR / f'{slug}.md'
    if not agent_md.exists():
        raise FileNotFoundError(f'No agent prompt found for {slug}')

    # Strip YAML frontmatter
    text = agent_md.read_text()
    if text.startswith('---'):
        _, _, body = text.split('---', 2)
        text = body.strip()

    return text


def load_skills_for_agent(slug: str) -> str:
    skill_dir = SKILLS_DIR / slug
    if not skill_dir.exists():
        return ''

    parts = []
    for skill_file in sorted(skill_dir.rglob('SKILL.md')):
        parts.append(f'---\n{skill_file.read_text().strip()}\n')

    return '\n'.join(parts)


def build_system_prompt(slug: str) -> str:
    agent_prompt = load_agent_system_prompt(slug)
    skills = load_skills_for_agent(slug)
    if skills:
        return f'{agent_prompt}\n\n## Skills\n\n{skills}'
    return agent_prompt
```

---

## Groq Client

```python
# ai_agents/groq_client.py
import json
import os
from groq import Groq

client = Groq(api_key=os.environ['GROQ_API_KEY'])
DEFAULT_MODEL = os.environ.get('AGENT_MODEL', 'llama-3.3-70b-versatile')


def chat(messages: list[dict], model: str = DEFAULT_MODEL, max_tokens: int = 2000) -> str:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content


def structured_output(messages: list[dict], model: str = DEFAULT_MODEL, max_tokens: int = 2000) -> dict:
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        response_format={'type': 'json_object'},
    )
    raw = resp.choices[0].message.content
    return json.loads(raw)
```

---

## Orchestrator

Replaces `agents/sessions` + `sessions.steer()`. Runs a full agent turn, persists history, handles handoffs.

```python
# ai_agents/orchestrator.py
import json
import re
from .models import AgentDefinition, AgentSession, AgentMessage
from .skill_loader import build_system_prompt
from .groq_client import chat, structured_output
from .subagent import run_subagent

HANDOFF_RE = re.compile(r'\{"type":\s*"handoff_request".*?\}', re.DOTALL)


def start_session(user, slug: str, context_data: dict) -> AgentSession:
    agent = AgentDefinition.objects.get(slug=slug, is_active=True)
    session = AgentSession.objects.create(user=user, agent=agent, context_data=context_data)
    system_prompt = build_system_prompt(slug)
    AgentMessage.objects.create(session=session, role='system', content=system_prompt)
    return session


def run(session: AgentSession, user_message: str) -> str:
    AgentMessage.objects.create(session=session, role='user', content=user_message)

    history = list(
        session.messages.order_by('created_at').values('role', 'content')
    )

    try:
        reply = chat(history, model=session.agent.model, max_tokens=session.agent.max_tokens)
    except Exception as e:
        session.status = 'failed'
        session.error = str(e)
        session.save()
        raise

    AgentMessage.objects.create(session=session, role='assistant', content=reply)

    # Check for subagent delegation request
    reply = _handle_subagents(session, reply)

    # Check for handoff request
    handoff = _extract_handoff(reply)
    if handoff:
        return _hand_off(session, handoff)

    return reply


def _handle_subagents(session: AgentSession, reply: str) -> str:
    # Agents signal subagent calls as JSON blocks: {"type":"subagent_call","agent":"<slug>","input":{...}}
    pattern = re.compile(r'\{"type":\s*"subagent_call".*?\}', re.DOTALL)
    for match in pattern.finditer(reply):
        try:
            call = json.loads(match.group(0))
            result = run_subagent(session, call['agent'], call['input'])
            reply = reply.replace(match.group(0), json.dumps(result))
        except Exception:
            continue
    return reply


def _extract_handoff(text: str) -> dict | None:
    m = HANDOFF_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        if obj.get('target_agent') and obj.get('payload'):
            return obj
    except json.JSONDecodeError:
        pass
    return None


def _hand_off(session: AgentSession, handoff: dict) -> str:
    session.status = 'handed_off'
    session.save()
    target_slug = handoff['target_agent']
    new_session = start_session(session.user, target_slug, handoff['payload'])
    return run(new_session, handoff['payload'].get('event', ''))
```

---

## Subagent Runner

Replaces `callable_agents` depth-1 delegation.

```python
# ai_agents/subagent.py
from .models import AgentSession, SubagentCall
from .skill_loader import build_system_prompt
from .groq_client import structured_output
import json


def run_subagent(parent_session: AgentSession, slug: str, input_payload: dict) -> dict:
    call = SubagentCall.objects.create(
        session=parent_session,
        subagent_slug=slug,
        input_payload=input_payload,
    )
    try:
        system_prompt = build_system_prompt(slug)
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f'Input:\n{json.dumps(input_payload, indent=2)}'},
        ]
        result = structured_output(messages)
        call.output = result
        call.save()
        return result
    except Exception as e:
        call.error = str(e)
        call.save()
        raise
```

---

## Registry — Replaces `deploy-managed-agent.sh`

Loads all agent definitions from disk into the DB. Run once after adding/updating agents.

```python
# ai_agents/registry.py
from pathlib import Path
from .models import AgentDefinition
from .skill_loader import build_system_prompt, AGENTS_DIR

import yaml


def sync_agents():
    registered, updated = 0, 0
    for agent_md in sorted(AGENTS_DIR.glob('*.md')):
        slug = agent_md.stem
        text = agent_md.read_text()

        # parse frontmatter for name/description
        name = slug
        if text.startswith('---'):
            try:
                _, fm, _ = text.split('---', 2)
                meta = yaml.safe_load(fm)
                name = meta.get('name', slug)
            except Exception:
                pass

        system_prompt = build_system_prompt(slug)
        obj, created = AgentDefinition.objects.update_or_create(
            slug=slug,
            defaults={'name': name, 'system_prompt': system_prompt},
        )
        if created:
            registered += 1
        else:
            updated += 1

    return registered, updated
```

Add a management command to call it:

```python
# ai_agents/management/commands/sync_agents.py
from django.core.management.base import BaseCommand
from ai_agents.registry import sync_agents

class Command(BaseCommand):
    help = 'Sync agent definitions from disk into DB'

    def handle(self, *args, **kwargs):
        r, u = sync_agents()
        self.stdout.write(f'Registered: {r}  Updated: {u}')
```

```bash
python manage.py sync_agents
```

---

## Views (LSuite trigger points)

```python
# ai_agents/views.py
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json

from main.models import BankTransaction, EmailStatement
from .orchestrator import start_session, run


@login_required
@require_POST
def gl_reconcile(request):
    txn_ids = json.loads(request.body).get('transaction_ids', [])
    txns = BankTransaction.objects.filter(user=request.user, id__in=txn_ids, category__isnull=True)
    payload = [
        {'id': t.id, 'date': str(t.date), 'description': t.description,
         'amount': str(t.amount), 'type': t.transaction_type}
        for t in txns
    ]
    session = start_session(request.user, 'gl-reconciler', {'transactions': payload})
    result = run(session, f'Analyse these {len(payload)} uncategorised transactions and suggest categories.')
    return JsonResponse({'session_id': session.id, 'result': result})


@login_required
@require_POST
def audit_statement(request, pk):
    stmt = EmailStatement.objects.get(pk=pk, user=request.user)
    txns = list(stmt.bank_transactions.values('date', 'description', 'amount', 'transaction_type'))
    session = start_session(request.user, 'statement-auditor', {'statement': stmt.subject, 'transactions': txns})
    result = run(session, 'Audit this statement for anomalies, duplicates, and gaps.')
    return JsonResponse({'session_id': session.id, 'result': result})


@login_required
@require_POST  
def month_end(request):
    import json
    from main.models import BankTransaction
    from django.db.models import Sum
    from datetime import date
    body = json.loads(request.body)
    month, year = body.get('month', date.today().month), body.get('year', date.today().year)
    totals = (BankTransaction.objects
              .filter(user=request.user, date__month=month, date__year=year)
              .values('category__name')
              .annotate(total=Sum('amount')))
    session = start_session(request.user, 'month-end-closer', {'month': month, 'year': year, 'totals': list(totals)})
    result = run(session, 'Generate month-end variance commentary and flag any missing accruals.')
    return JsonResponse({'session_id': session.id, 'result': result})
```

---

## Environment Variables

```
GROQ_API_KEY=gsk_...
AGENT_MODEL=llama-3.3-70b-versatile   # or mixtral-8x7b-32768 for longer context
```

---

## Implementation Order

1. `ai_agents/` app scaffold + models + migration
2. `skill_loader.py` + copy skill/agent markdown from FSI repo
3. `groq_client.py`
4. `registry.py` + management command → `python manage.py sync_agents`
5. `orchestrator.py` (no subagents yet, just single-turn)
6. Wire up GL Reconciler view, test against real transactions
7. Add `subagent.py` + handoff logic
8. Statement Auditor + Month-End Closer views
9. Add session history UI (optional — sessions are in DB already)

---

## What We Keep from the FSI Repo

- All `skills/*/SKILL.md` files — copy verbatim
- All `agents/<slug>.md` system prompts — copy verbatim
- `scripts/check.py` — still useful for linting skill drift
- `scripts/sync-agent-skills.py` — still useful for keeping skill copies in sync

## What We Discard

- `deploy-managed-agent.sh` — replaced by `sync_agents` management command
- `orchestrate.py` — replaced by `orchestrator.py`
- All `.claude-plugin/` directories — Cowork-only
- `marketplace.json` — Cowork-only
