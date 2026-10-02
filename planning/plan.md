# Σχέδιο έργου: `labhq` — self-hosted project orchestrator

Ημερομηνία: 2026-10-02 · Κατάσταση: πρόχειρο προς έγκριση · Όνομα: `labhq`

## 1. Σκοπός

Για ιδιώτες, hobbyists και developers που δουλεύουν μόνοι τους: ένας άνθρωπος, πολλά projects, μια ομάδα από AI. Χτίζεις έναν open-source, self-hosted orchestrator έργων. Ένας Orchestrator ("CEO") επιβλέπει όλα τα software repos σου. Κάθε έργο έχει Manager, κάθε Manager έχει ομάδες. Μιλάς στον CEO από όποια AI εφαρμογή χρησιμοποιείς ήδη, με τη φωνή της.

Στόχος: να αξίζει να το δοκιμάσει κάθε hobbyist και homelab developer, και να στήνεται με μία εντολή.

Τι το κάνει διαφορετικό, σε τέσσερα σημεία:

| Διαφοροποίηση | Τι σημαίνει |
|---|---|
| Call Center | Φωνή μέσω οποιασδήποτε AI εφαρμογής, χωρίς δικό μας voice code |
| Security-first εγκρίσεις | Βαριές ενέργειες χρειάζονται passkey, όχι απλό κλικ |
| Meetings | Σύσκεψη ως first-class αντικείμενο, με αποφάσεις που γίνονται tasks, ζωντανά στο Discord ή Slack του χρήστη |
| IT/Infra τμήμα | Παρακολουθεί τα μηχανήματα του homelab, βάζει δικούς του κανόνες και ανοίγει tickets |

Μη-στόχοι: δεν χτίζουμε STT/TTS και δεν ανταγωνιζόμαστε σε εύρος. Δεν απευθύνεται σε εταιρείες: ένας χρήστης, χωρίς ρόλους, οργανισμούς ή SSO.

## 2. Ιεραρχία και ρόλοι

```
Orchestrator ("CEO")            long-lived, memory, βλέπει ΟΛΑ τα projects
 └─ Manager (ένας ανά project)  long-lived, memory
     └─ Team lead               long-lived, memory
         └─ Worker              ephemeral: ένας ανά task, δικό του git worktree
```

- Ο Orchestrator αναθέτει Manager ανά project.
- Ο Manager σχηματίζει ομάδες: team leads και μέλη (developers, designers, QA, ό,τι χρειάζεται). Η δημιουργία ομάδας είναι βαριά απόφαση (§5).
- Οι workers είναι ephemeral. Κάθε task παίρνει δικό του worktree και branch, και ο worker τελειώνει μαζί με το task.
- Οι managers και οι leads κρατούν memory ανάμεσα στα runs.
- Οι συσκέψεις (standup, planning, review) είναι first-class αντικείμενα: agenda, συμμετέχοντες, transcript, αποφάσεις, action items. Κάθε action item γίνεται task.

### 2.1 Κανάλια συσκέψεων

- Οι συσκέψεις ζουν στη μηχανή: η βάση μας κρατά transcript, αποφάσεις και action items. Είναι η πηγή της αλήθειας.
- Κάθε σύσκεψη καθρεφτίζεται ζωντανά στην πλατφόρμα chat που έχει ή θέλει ο χρήστης: κανάλι ανά project, thread ανά σύσκεψη.
- Registry από adapters (dispatch as data): Discord πρώτα, Slack δεύτερο, Mattermost ή Matrix μετά το launch, ως νέες εγγραφές.
- Κάθε agent γράφει με δικό του όνομα και avatar (στο Discord με webhooks που ορίζουν όνομα και avatar ανά μήνυμα· στο Slack με `chat:write.customize`).
- Ο χρήστης μπαίνει στη σύσκεψη απαντώντας στο thread· το μήνυμά του γυρίζει στη μηχανή ως συμμετοχή.
- Το desktop UI δείχνει την ίδια σύσκεψη από τη βάση, για όποιον δεν έχει chat. Τα μακριά μηνύματα σπάνε στο όριο των 2000 χαρακτήρων του Discord· το ιστορικό 90 ημερών του δωρεάν Slack δεν μας επηρεάζει.

### 2.2 Τμήμα IT/Infra

- Ενσωματωμένο τμήμα, όχι δεμένο σε project. Επιβλέπει το μηχάνημα που τρέχει η υπηρεσία και άλλα μηχανήματα μέσω SSH.
- Μετρήσεις από κώδικα, διάγνωση από agent: ένας collector (χωρίς AI) μαζεύει ανά λίγα λεπτά CPU, μνήμη, δίσκους, θερμοκρασίες, SMART, services, containers, λάθη στο journal, λήξεις πιστοποιητικών και εκκρεμή updates. Ο agent ξυπνά μόνο σε απόκλιση και σε ένα καθημερινό standup.
- Απομακρυσμένα μηχανήματα: agentless μέσω SSH, με ξεχωριστό χρήστη μόνο για ανάγνωση.
- Κανόνες ως δεδομένα: registry τύπων κανόνων (όριο σε μέτρηση, service ενεργό, port/HTTP, λήξη πιστοποιητικού, μοτίβο στα logs, τάση). Ο agent προσθέτει και ρυθμίζει κανόνες μόνος του, με αιτιολόγηση για τον καθένα· φαίνονται στο UI και απενεργοποιούνται.
- Κανένας κανόνας δεν διορθώνει: ένας κανόνας ειδοποιεί ή ανοίγει ticket. Η διόρθωση είναι ticket με διάγνωση και προτεινόμενη λύση· η εκτέλεσή της σε μηχάνημα είναι heavy ενέργεια με biometrics.
- Οι agents του IT/Infra τρέχουν σε `strict` με εντολές μόνο για ανάγνωση: εξαίρεση από το default `bypassPermissions`, γιατί αγγίζουν το ίδιο το μηχάνημα.
- Τα incidents φτάνουν στο Call Center («είναι καλά ο server;»), στις εγκρίσεις και στο κανάλι `#infra` του Discord.
- Αργότερα: adapters ανάγνωσης από Netdata, Uptime Kuma ή Prometheus, για όσους τα έχουν ήδη.

## 3. Call Center

Όνομα λειτουργίας: **Call Center** (επιλογή του χρήστη).

### 3.1 Αρχιτεκτονική

Δεν γράφουμε κώδικα φωνής. Το προϊόν εκθέτει έναν MCP server (Streamable HTTP). Προσθέτεις τον server ως connector στην AI εφαρμογή που ήδη χρησιμοποιείς (ChatGPT, Claude, Grok…) και μιλάς στον CEO με το voice chat της. Η εφαρμογή έχει δική της κρίση για το τι θα ρωτήσει και πότε.

```
Εσύ ──φωνή──> AI app (ChatGPT / Claude / Grok)
                 │  MCP, Streamable HTTP
                 ▼
            labhq MCP server ──> engine ──> agents
                 │
                 └──> notifier (ntfy / Telegram) ──> εσύ
```

### 3.2 Κανόνες σχεδίασης

1. Λίγα tools. Κάθε tool έχει ένα σαφές όνομα και ένα σκοπό.
2. Γρήγορες επιστροφές. Η μακρά δουλειά είναι async με tickets: `ask_ceo` επιστρέφει ticket, το `get_reply` το εξαργυρώνει.
3. Οι απαντήσεις γράφονται για να ακουστούν: σύντομες προτάσεις, χωρίς πίνακες, χωρίς JSON.
4. Σωστά MCP annotations: `readOnlyHint` στις ερωτήσεις (περνούν χωρίς επιβεβαίωση), `destructiveHint` στις ενέργειες (ζητούν επιβεβαίωση).
5. Οι κανόνες ζουν μέσα στα tools (description, αποτελέσματα, σφάλματα). Οι clients τιμούν ανομοιόμορφα το server `instructions`, άρα δεν βασιζόμαστε σε αυτό.
6. Οι voice assistants δεν μπορούν να σου στείλουν push. Οι ειδοποιήσεις περνούν από pluggable notifier (ntfy ως default, Telegram προαιρετικά).

### 3.3 Υποψήφια tools

| Tool | Είδος | Annotation | Σκοπός |
|---|---|---|---|
| `brief` | ανάγνωση | `readOnlyHint` | Τι έγινε, τι χρειάζεται εσένα |
| `inbox` | ανάγνωση | `readOnlyHint` | Εκκρεμείς εγκρίσεις και ερωτήσεις |
| `decide` | εγγραφή | `destructiveHint` για βαριές | Εγκρίνει/απορρίπτει (οι βαριές μόνο ζητούνται, βλ. §5) |
| `order` / `assign` | εγγραφή | write | Δίνει εντολή ή αναθέτει task |
| `ask_ceo` | async | write | Ρωτά τον CEO, επιστρέφει ticket |
| `get_reply` | ανάγνωση | `readOnlyHint` | Παραλαβή απάντησης από ticket |
| `meeting_minutes` | ανάγνωση | `readOnlyHint` | Πρακτικά σύσκεψης |
| `health` | ανάγνωση | `readOnlyHint` | Κατάσταση μηχανημάτων και ανοιχτά incidents |

Η τελική λίστα κλειδώνει στη Φάση 2, μετά από δοκιμή με φωνή.

### 3.4 Τι έχει ήδη αποδειχθεί

Δουλεύει ήδη στην πράξη: ένας custom MCP server (Streamable HTTP) πίσω από tunnel χρησιμοποιείται καθημερινά με φωνή. Η βάση του Call Center είναι αποδεδειγμένη, όχι υπόθεση. Το Gemini (consumer) μένει εκτός, γιατί δεν δέχεται custom MCP.

## 4. Τεχνολογίες

Ακολουθούμε τις μηχανικές συμβάσεις (θα γραφτούν στο `CONTRIBUTING.md`): Python με PEP 8/484, ruff, pytest, pydantic, uv· migrations ως μοναδική αρχή σχήματος· χρήματα σε integer minor units· UTC instants.

### 4.1 Backend

| Θέμα | Επιλογή |
|---|---|
| Γλώσσα / εργαλεία | Python 3.12, `uv`, FastAPI, pydantic, pytest, ruff |
| Βάση | SQLite (ένας χρήστης), Alembic migrations. Ποτέ `create_all` στον κώδικα εφαρμογής |
| Χρήμα | Integer minor units (π.χ. cents), ποτέ float |
| Χρόνος | UTC timezone-aware instants |
| Workers | Claude Agent SDK για Python (`ClaudeSDKClient`) |
| Adapters | Registry (dispatch as data): Claude πρώτα, Codex και Ollama/local αργότερα |

Γιατί Python αντί Node: όλο το stack σου είναι Python, και το `uvx` δίνει εγκατάσταση με μία εντολή, όπως το `npx`.

Τι δίνει το Agent SDK και χρησιμοποιούμε:

- Σε αυστηρό mode (`strict`, προαιρετικό): `can_use_tool` callback που περιμένει όσο χρειαστεί έναν άνθρωπο, για έγκριση ανά tool.
- `interrupt()` για διακοπή τρέχοντος agent.
- Streaming input, για να στείλεις μήνυμα σε agent που τρέχει.
- Session resume. Ένα headless session ανοίγει αργότερα σε terminal με `claude --resume <id>` (όχι ταυτόχρονα).

Ο adapter registry είναι ένας πίνακας `adapter_key -> factory`. Νέος adapter σημαίνει νέα εγγραφή, όχι αλλαγή dispatcher. Δεν εισάγουμε abstraction πέρα από το interface που ήδη θα έχουν δύο adapters.

### 4.2 Frontend

Vue 3 (Composition API, `<script setup>`), TypeScript, Pinia, vue-router, vue-i18n (el/en), Tailwind 4 + shadcn-vue. Το TS client παράγεται από το OpenAPI του FastAPI, ώστε το contract να ελέγχεται μηχανικά.

### 4.3 Δομή repo

Σκελετός (`src/labhq/`, `migrations/`, `web/`, `tests/`, `docs/adr/`, `planning/`). Όριο μεγέθους αρχείου: soft 400, hard 600 γραμμές (εξαιρούνται generated, locks, i18n, fixtures).

## 5. Εγκρίσεις και ασφάλεια

Δύο κλάσεις απόφασης:

| Κλάση | Παραδείγματα | Τι αρκεί |
|---|---|---|
| Light | Έναρξη σύσκεψης, ανάθεση task, αλλαγή priority | Φωνή ή tap |
| Heavy | Merge στο main, push, διαγραφή branch ή project, δημιουργία ομάδας, υπέρβαση budget, παρέμβαση σε μηχάνημα (restart, καθάρισμα, updates, reboot) | Ο voice agent μπορεί μόνο να ΖΗΤΗΣΕΙ. Η έγκριση απαιτεί ισχυρή επιβεβαίωση |

Τις βαριές ενέργειες τις εκτελεί η μηχανή, όχι ο agent: ο agent τις ζητά, η μηχανή τις εκτελεί μόνο μετά την έγκριση.

Ισχυρή επιβεβαίωση:

- Στην open-source έκδοση: ενσωματωμένο passkey/WebAuthn στο UI μας.
- Εξωτερικές πύλες έγκρισης (π.χ. ένα υπάρχον Face ID gate) μπαίνουν ως plugin.
- Η ειδοποίηση για heavy έγκριση ανοίγει απευθείας σελίδα έγκρισης με biometrics (passkey) στο κινητό. Άλλο UI στο κινητό δεν χρειάζεται.

Κανόνες:

1. Default: `--dangerously-skip-permissions` (`bypassPermissions`), ώστε οι agents να δουλεύουν χωρίς διακοπές μέσα στο worktree τους.
2. Εξαίρεση: οι agents του IT/Infra τρέχουν σε `strict` με εντολές μόνο για ανάγνωση (§2.2).
3. Προαιρετικό αυστηρό mode (`strict`): κάθε tool εκτός allowlist περνά από έγκριση μέσω `can_use_tool`.
4. Η έγκριση νέων agents είναι on by default.
5. Οι agents δεν κάνουν push ή merge μόνοι τους: PreToolUse hook απορρίπτει `git push`, `gh pr merge` και παρόμοια, το push URL του worktree είναι απενεργοποιημένο, και κανένα git credential δεν υπάρχει στο περιβάλλον του worker. Το αν τα hooks ισχύουν σε `bypassPermissions` επιβεβαιώνεται στη Φάση 0.
6. Προαιρετικό sandbox (bubblewrap σε Linux) ή ξεχωριστός OS user, για πραγματική απομόνωση: σε `bypassPermissions` ο agent έχει πρόσβαση σε ό,τι έχει ο χρήστης του server.
7. Ένας voice client δεν μπορεί ποτέ να εκδώσει heavy approval, ούτε αν το ζητήσει ο ίδιος ο agent.
8. Κάθε έγκριση καταγράφεται με payload, κλάση ρίσκου, αποφασίζοντα και χρόνο.

## 6. Μοντέλο δεδομένων

Ελάχιστο σύνολο. Όλα τα timestamps σε UTC, τα ποσά σε minor units.

| Πίνακας | Βασικές στήλες / ρόλος |
|---|---|
| `projects` | `id`, `name`, `repo_path`, `budget_minor`, `status` |
| `agents` | `role`, `title`, `reports_to`, `project_id`, `adapter`, `config`, `budget_minor` |
| `tasks` | `status`, `priority`, `parent_id`, `assignee`, `checkout_run_id` (atomic checkout lock) |
| `comments` | σχόλια και mentions σε tasks |
| `meetings` | `kind`, `agenda`, `status`, `channel_adapter`, `external_ref` (thread)· παιδιά: `meeting_participants`, `meeting_transcript_entries`, `meeting_decisions`, `meeting_action_items` |
| `wakeup_requests` | `source`, `reason`, `coalesced_count`, `idempotency_key` |
| `runs` | `status`, `session_id_before`, `session_id_after`, `usage`, `exit` |
| `run_events` | γεγονότα ροής ανά run |
| `cost_events` | κόστος ανά run/agent/project σε minor units |
| `approvals` | `type`, `risk_class`, `status`, `payload` |
| `agent_task_sessions` | αντιστοίχιση agent + task σε session για resume |
| `hosts` | `name`, `address`, `ssh_user`, `status` |
| `health_samples` | `host_id`, `metric`, `value`, `sampled_at` |
| `health_rules` | `type`, `params`, `action` (`notify` ή `ticket`), `reason`, `created_by`, `enabled` |
| `incidents` | `rule_id`, `host_id`, `status`, `task_id` (το ticket) |

Αναλλοίωτα:

- Το `tasks.checkout_run_id` αλλάζει με ατομικό conditional update: ένα task έχει το πολύ ένα ενεργό run.
- Το `wakeup_requests.idempotency_key` είναι unique, ώστε οι επαναλήψεις να μη διπλασιάζουν δουλειά.
- Ένα `meeting_action_items` row δημιουργεί task και κρατά αναφορά σε αυτό.

## 7. Χρονοπρογραμματιστής

Ο scheduler ξυπνά agents από πέντε πηγές: timer, ανάθεση, comment/mention, επίλυση έγκρισης, σύσκεψη.

Κανόνες:

1. Coalescing: όσο ένας agent τρέχει, νέα wakeups συγχωνεύονται σε ένα (αυξάνεται το `coalesced_count`).
2. Concurrency ανά agent με ΧΑΜΗΛΟ default (πρόταση: 1).
3. Έλεγχος budget στο enqueue και ξανά πριν την εκκίνηση.
4. Προειδοποίηση στο 80% του budget, σκληρό σταμάτημα στο 100%.
5. Stale-run reaper: runs χωρίς heartbeat μέσα σε όριο κλείνουν ως `failed`.
6. Timeouts ανά run, ρυθμιζόμενα στο `agents.config`.

Η τερματική διαδικασία (kill) κρύβεται πίσω από interface ανά πλατφόρμα (§9).

### 7.1 Οικονομία tokens

- Ύφος εξόδου ανά αποδέκτη (dispatch as data): λακωνικό από agent σε agent (σχόλια, handoffs, γύροι σύσκεψης, αναφορές), φυσικό προς τον χρήστη (Call Center, πρακτικά στο Discord). Ό,τι γράφει ένας agent το διαβάζουν άλλοι, άρα το λακωνικό ύφος γλιτώνει δύο φορές: στην έξοδο του ενός και στην είσοδο του επόμενου.
- Υλοποίηση με δική μας σύντομη οδηγία στο system prompt κάθε ρόλου, χωρίς εξάρτηση από το caveman. Τα handoffs γράφονται δομημένα, με σταθερά πεδία.
- Το ύφος περιορίζει μόνο το κείμενο, όχι τη σκέψη του μοντέλου ούτε τον κώδικα.
- `rtk` ως default PreToolUse hook στους workers: φιλτράρει την έξοδο εντολών (tests, builds, logs) πριν φτάσει στο μοντέλο.
- `graphify` index ανά project: managers και workers ρωτούν τον γράφο αντί να διαβάζουν όλο τον κώδικα.
- `headroom` ως προαιρετικό proxy (`ANTHROPIC_BASE_URL`), μόνο μετά από έλεγχο ποιότητας.
- Κάθε μέτρο μετριέται με A/B στο `cost_events`. Μένει ενεργό μόνο ό,τι αποδεικνύει όφελος χωρίς πτώση ποιότητας.

## 8. UI

Desktop UI, σύντροφος του Call Center.

### 8.1 Τέσσερις περιοχές

Πλοήγηση με στενό sidebar τεσσάρων στοιχείων.

| Περιοχή | Περιεχόμενο |
|---|---|
| Σήμερα | Τι έγινε και τι χρειάζεται εσένα |
| Projects | Κάρτα ανά project, ομάδα ως expandable tree, deliverables, budget |
| Meetings | Agenda, ζωντανή συνομιλία των agents ως chat, αποφάσεις, action items, κουμπί "join" |
| Εγκρίσεις | Tap για light, passkey για heavy |

### 8.2 Αρχές

1. Δείχνεις αποτελέσματα, όχι δραστηριότητα. Ένα UI που γράφει "agents working" ενώ τα χρήματα καίγονται χωρίς output δεν βοηθά.
2. Ένα λεξιλόγιο καταστάσεων σε όλο το UI.
3. Κανένα toast για κατάσταση που φαίνεται ήδη.
4. Οι τιμές μηχανής (ids, branches, κόστος) σε mono.

### 8.3 Στυλ

Dark-first, Oxanium + IBM Plex Mono, indigo/purple accent, glass.

### 8.4 Αποφεύγουμε

- Δεκάδες routes.
- Sidebar με 20 στοιχεία.

Ζωντανές ενημερώσεις: SSE ή WebSocket (η επιλογή γίνεται στη Φάση 4 με ADR).

## 9. Πλατφόρμες και εγκατάσταση

| Πλατφόρμα | Επίπεδο υποστήριξης |
|---|---|
| Linux | Επίσημη |
| macOS | Επίσημη |
| Windows μέσω WSL2 ή Docker Desktop | Επίσημη |
| Native Windows | Best effort, με CI matrix |

- Ο τερματισμός διεργασιών κρύβεται πίσω από interface ανά πλατφόρμα. Στα Windows δεν υπάρχουν SIGTERM ή process groups, οπότε χρησιμοποιούμε π.χ. `taskkill /T`.
- Καμία εξάρτηση από tmux.

Εγκατάσταση:

```
uvx labhq onboard
uv tool install labhq
docker compose up
```

Στα Windows το uv εγκαθίσταται με PowerShell one-liner ή `winget`.

### 9.1 Onboarding χωρίς κόπο

- Ένα `uvx labhq onboard` φτάνει σε λειτουργικό σύστημα χωρίς κανέναν λογαριασμό σε τρίτους. Κάθε λογαριασμός είναι προαιρετική αναβάθμιση.
- Το script εντοπίζει ό,τι υπάρχει ήδη (cloudflared, tailscale, Discord token), αυτοματοποιεί ό,τι γίνεται, και ό,τι θέλει κλικ το δίνει ως ένα βήμα με έτοιμο link ή QR.
- Πριν πει «έτοιμο», ελέγχει από άκρη σε άκρη: καλεί το δημόσιο URL του και στέλνει δοκιμαστική ειδοποίηση.
- Στο τέλος δείχνει QR με το URL του connector, για το Claude ή το ChatGPT στο κινητό.

| Ανάγκη | Default χωρίς λογαριασμό | Αναβάθμιση | Τι κάνει ο χρήστης |
|---|---|---|---|
| Δημόσιο URL | Cloudflare quick tunnel (`cloudflared tunnel --config /dev/null --url …`) | Tailscale Funnel (σταθερό URL) ή δικό σου domain (Cloudflare Tunnel, Pangolin, Caddy) | Quick tunnel: τίποτα, αλλά νέο URL σε κάθε restart. Funnel: ένα SSO login και μία έγκριση στον browser |
| Ειδοποιήσεις | ntfy.sh με τυχαίο topic | Telegram bot | Εγκαθιστά την εφαρμογή ntfy και κάνει subscribe από QR |
| Meetings | Meeting room στο desktop UI | Discord bot | Φτιάχνει app στο Discord Developer Portal και αντιγράφει το token, ενεργοποιεί το Message Content, πατά το έτοιμο invite link. Ο bot φτιάχνει μόνος του κανάλια, threads και webhooks ανά agent |
| Login και εγκρίσεις | Ενσωματωμένα passkeys | — | Τίποτα |
| Μοντέλα | Υπάρχον login του `claude` ή API key | — | Login ή επικόλληση key |

Δεν μπαίνουν ως default: ngrok free (σελίδα προειδοποίησης στο login και στις εγκρίσεις, 20.000 αιτήματα τον μήνα), Pinggy (λήγει στα 60 λεπτά), localhost.run και Serveo (ασταθή).

### 9.2 Δημόσιο URL και auth

- Ο server ελέγχει μόνος του ποιος μπαίνει: ενσωματωμένο OAuth 2.1 με passkeys, ή σταθερό token σε header. Δεν εξαρτάται από Cloudflare Access ή άλλο identity provider.
- Η έκθεση είναι registry από adapters: Cloudflare quick tunnel, Tailscale Funnel, Cloudflare Tunnel, Pangolin, reverse proxy (Caddy), ngrok.
- Ο MCP server απαντά με απλό JSON, όχι SSE: το Cloudflare quick tunnel δεν υποστηρίζει SSE, και τα tools μας επιστρέφουν γρήγορα έτσι κι αλλιώς (tickets).
- Για καθημερινή χρήση και πίσω από εταιρικά δίκτυα, που συχνά μπλοκάρουν domains υπηρεσιών tunnel, τα docs συστήνουν δικό σου domain.

## 10. Φάσεις

Κάθε φάση κλείνει με annotated git tag που φέρει τα στοιχεία αποδοχής στο μήνυμά του. Βάζεις το tag ΜΕΤΑ το gate, ποτέ πριν. Τα tags ακολουθούν SemVer (`v0.1.0-alpha.1`…), τα Python πακέτα PEP 440 (`0.1.0a1`). Το `CHANGELOG.md` παράγεται από το ιστορικό. Δεν δίνουμε ημερολογιακές εκτιμήσεις.

Σειρά εξαρτήσεων: Φάση 0 → 1 → 2 → 3 → 4 → 5. Οι Φάσεις 2 και 3 μπορούν να επικαλυφθούν αφού κλειδώσει το data model.

### Φάση 0 — Spike / risk retirement

Στόχος: να μετρηθούν τα ρίσκα πριν γραφτεί η μηχανή.

Βήματα:

1. `git init` και `.gitignore` πριν το πρώτο commit.
2. Agent SDK spike: σε `bypassPermissions` ένα PreToolUse hook μπλοκάρει `git push`· `interrupt()`· resume· και `can_use_tool` σε αναμονή για το strict mode.
3. Έκθεση και auth χωρίς Cloudflare Access: δοκιμαστικός MCP με ακίνδυνο tool και ενσωματωμένο auth (πρώτα token, μετά OAuth 2.1 με DCR), πίσω από Cloudflare quick tunnel και μετά Tailscale Funnel· σύνδεση στο Claude και κλήση με φωνή.
4. Απόφαση billing: συνδρομή ή API key (βλ. §12).

Κριτήρια αποδοχής:

- Script spike δείχνει: σε `bypassPermissions` ένα PreToolUse hook μπλοκάρει `git push`· ένα `interrupt()` σταματά run· ένα resume κρατά context· σε strict mode ένα `can_use_tool` μένει σε αναμονή >60 s και συνεχίζει μετά την απάντηση.
- Ο δοκιμαστικός MCP απαντά σε κλήση με φωνή από το Claude, πίσω από quick tunnel και πίσω από Funnel, με token και με OAuth· ή ADR με ό,τι δεν δούλεψε.
- ADR για billing στο `docs/adr/`.
- Το repo έχει `.gitignore` πριν το πρώτο commit, και tag `v0.0.1-spike` με τα αποτελέσματα.

### Φάση 1 — Engine

Περιεχόμενο: data model + migrations, scheduler, runs, Claude adapter, worktrees, budgets, approvals, CLI, collector υγείας για το τοπικό μηχάνημα και rule engine, ύφος εξόδου ανά αποδέκτη, `rtk` hook.

Demo: ένα project, ένας manager, ένας worker. Task → worktree branch με commit → κόστος καταγραμμένο → push απαιτεί έγκριση.

Κριτήρια αποδοχής:

- `uv run alembic upgrade head` χτίζει το πλήρες σχήμα από μηδέν· CI ελέγχει ισοδυναμία migrations και μοντέλων.
- Το demo τρέχει από CLI και παράγει: branch με ≥1 commit, γραμμή στο `cost_events`, `approvals` row σε `pending` για το push.
- Το push ΔΕΝ εκτελείται πριν την έγκριση· μετά την έγκριση εκτελείται (test).
- Δύο ταυτόχρονα checkouts του ίδιου task: το ένα αποτυγχάνει (test).
- Budget στο 100% σταματά νέο run· στο 80% καταγράφεται προειδοποίηση (test).
- Ένας worker δεν μπορεί να κάνει push: η απόπειρα `git push` από agent αποτυγχάνει (test).
- Ένα σκοτωμένο run κλείνει από τον reaper (test).
- Ο collector γράφει μετρήσεις του τοπικού μηχανήματος· ένας κανόνας ορίου που παραβιάζεται ανοίγει incident (test).
- Το ύφος εξόδου ορίζεται ανά αποδέκτη στο config· ένα handoff ανάμεσα σε agents είναι λακωνικό και δομημένο (test).
- Με τον `rtk` hook ενεργό, ένα test run καταγράφει στο `cost_events` λιγότερα input tokens από το ίδιο run χωρίς αυτόν (A/B).
- CI σε κάθε push ελέγχει ότι δεν μπαίνουν μυστικά ή προσωπικά στοιχεία (`gitleaks` και λίστα απαγορευμένων όρων) (guard).
- ruff, τύποι και έλεγχος μεγέθους αρχείων περνούν στο CI. Tag `v0.1.0-alpha.1`.

### Φάση 2 — Call Center (MCP)

Περιεχόμενο: τα tools, annotations, async tickets, δοκιμή με φωνή σε Claude και ChatGPT.

Κριτήρια αποδοχής:

- Ο MCP server περνά έλεγχο με MCP inspector· κάθε tool έχει σωστά `readOnlyHint`/`destructiveHint` (test που τα διαβάζει).
- `ask_ceo` επιστρέφει ticket σε <2 s ανεξάρτητα από τη διάρκεια της δουλειάς· το `get_reply` το εξαργυρώνει.
- Καμία απάντηση tool δεν περιέχει πίνακα markdown ή JSON σε πεδίο φωνής (test).
- Ένα `decide` για heavy ενέργεια επιστρέφει "ζητήθηκε έγκριση" και δημιουργεί `approvals` row· δεν εκτελεί.
- Live δοκιμή με φωνή: τουλάχιστον μία εφαρμογή (Claude ή ChatGPT) ολοκληρώνει το σενάριο brief → ask_ceo → get_reply. Καταγράφεται βίντεο.
- Ο notifier στέλνει μήνυμα (ntfy ή Telegram) όταν δημιουργείται έγκριση.
- Το `health` απαντά με προφορικό κείμενο για την κατάσταση των μηχανημάτων (test).
- Ο MCP server απαντά με JSON χωρίς SSE και δουλεύει πίσω από Cloudflare quick tunnel (test).
- Tag `v0.2.0-alpha.1`.

### Φάση 3 — Hierarchy & meetings

Περιεχόμενο: CEO → managers → leads → workers, δημιουργία ομάδας με έγκριση, standup/planning/review με πρακτικά → tasks, Discord adapter για τις συσκέψεις, τμήμα IT/Infra (κανόνες από agent, tickets, SSH), `graphify` index ανά project.

Κριτήρια αποδοχής:

- Ο CEO αναθέτει Manager σε νέο project· ο Manager προτείνει ομάδα και η δημιουργία μένει `pending` ως heavy approval.
- Το team-size cap από το config αποτρέπει υπέρβαση (test).
- Ένα standup παράγει `meetings` row με συμμετέχοντες, transcript, ≥1 decision και ≥1 action item· κάθε action item γίνεται task (test).
- Το `meeting_minutes` διαβάζει τα πρακτικά με φωνή σε μορφή προφορικού κειμένου.
- Managers και leads διατηρούν memory ανάμεσα σε δύο runs (test: δεύτερο run βλέπει το περιεχόμενο του πρώτου).
- Το συνολικό κόστος σύσκεψης προσμετράται στο budget του project (test).
- Ένα standup εμφανίζεται ως thread στο κανάλι Discord του project, με κάθε agent να γράφει με δικό του όνομα (demo).
- Μια απάντηση του χρήστη στο thread καταγράφεται στο transcript ως συμμετοχή· με το Discord αποσυνδεδεμένο η σύσκεψη διαβάζεται κανονικά από UI και MCP (test).
- Ο agent του IT προσθέτει κανόνα με αιτιολόγηση· ο κανόνας φαίνεται και απενεργοποιείται από το UI (test).
- Ένας κανόνας που παραβιάζεται ανοίγει ticket με διάγνωση· η εκτέλεση της διόρθωσης απαιτεί biometrics (test).
- Ένα απομακρυσμένο μηχάνημα στέλνει μετρήσεις μέσω SSH με χρήστη μόνο για ανάγνωση (demo).
- Οι agents του IT δεν μπορούν να εκτελέσουν εντολή εγγραφής στο μηχάνημα (test).
- Ο manager ενός project απαντά από το `graphify` index αντί να διαβάζει αρχεία, με μετρημένη διαφορά tokens (A/B στο `cost_events`).
- Tag `v0.3.0-alpha.1`.

### Φάση 4 — UI

Περιεχόμενο: οι τέσσερις περιοχές, live updates (SSE ή WebSocket), passkey εγκρίσεις.

Κριτήρια αποδοχής:

- Και οι τέσσερις περιοχές λειτουργούν σε παράθυρο από 1280×800 και πάνω, χωρίς οριζόντιο scroll.
- Μια light έγκριση λύνεται με tap· μια heavy ΔΕΝ λύνεται χωρίς επιτυχή passkey (e2e test).
- Η σελίδα έγκρισης που ανοίγει από την ειδοποίηση δουλεύει σε κινητό με passkey (e2e test).
- Νέα έγκριση εμφανίζεται στο UI <3 s χωρίς refresh.
- Το UI είναι διαθέσιμο σε el και en (έλεγχος ότι δεν λείπουν κλειδιά i18n).
- Το TS client παράγεται από το OpenAPI στο CI· αλλαγή στο API χωρίς αναγέννηση αποτυγχάνει.
- Η Σήμερα δείχνει deliverables και εκκρεμείς εγκρίσεις, όχι λίστα "agents working" (έλεγχος σε screenshot test).
- Lighthouse desktop: performance και accessibility ≥ 90.
- Tag `v0.4.0-alpha.1`.

### Φάση 5 — Open-source launch

Περιεχόμενο: docker compose, uvx onboarding, docs, README με demo GIF, 3λεπτο demo script, Windows CI, επιπλέον adapters (Codex, Ollama· Slack για συσκέψεις), ανάρτηση σε r/selfhosted και r/homelab.

Κριτήρια αποδοχής:

- Σε καθαρό μηχάνημα Linux, macOS και WSL2, το `uvx labhq onboard` φτάνει σε λειτουργικό σύστημα χωρίς λογαριασμό σε τρίτους: δημόσιο URL (quick tunnel), ειδοποίηση ntfy, QR για τον connector, έλεγχος από άκρη σε άκρη (CI ή καταγεγραμμένη εκτέλεση).
- Το onboarding του Discord bot ζητά από τον χρήστη μόνο τα τρία χειροκίνητα βήματα (demo).
- `docker compose up` ανεβάζει το σύστημα και το healthcheck περνά.
- CI matrix με Windows τρέχει το test suite· οι αποτυχίες native Windows καταγράφονται ως γνωστοί περιορισμοί.
- Οι adapters Codex και Ollama περνούν το ίδιο contract test με τον Claude adapter.
- Ο Slack adapter συσκέψεων περνά το ίδιο contract test με τον Discord adapter.
- Το README έχει demo GIF, εντολή εγκατάστασης και ενότητα ασφάλειας.
- Το 3λεπτο demo (§11) ηχογραφείται χωρίς κοπές στο κρίσιμο σημείο.
- Υπάρχουν `LICENSE`, `SECURITY.md`, `CHANGELOG.md` (παραγόμενο).
- Tag `v0.5.0-beta.1`.

## 11. Demo σε 3 λεπτά

Στόχος: η στιγμή του Call Center.

| # | Beat | Τι φαίνεται / ακούγεται |
|---|---|---|
| 1 | Ανοίγεις το voice chat της AI εφαρμογής που ήδη χρησιμοποιείς | Καμία νέα εφαρμογή, μόνο το connector `labhq` |
| 2 | Ρωτάς τον CEO τι έκαναν οι ομάδες το βράδυ | `brief` απαντά με 3-4 σύντομες προτάσεις |
| 3 | Ζητάς τα πρακτικά του πρωινού standup | `meeting_minutes` διαβάζει αποφάσεις και action items· στην οθόνη φαίνεται το ίδιο standup ως thread στο Discord |
| 4 | Ρωτάς αν είναι καλά ο server | Το τμήμα IT απαντά και αναφέρει ένα ανοιχτό ticket (π.χ. ο δίσκος γεμίζει σε 5 μέρες) |
| 5 | Δίνεις εντολή να γίνει merge στο main | Ο agent απαντά ότι χρειάζεται έγκριση, δεν εκτελεί |
| 6 | Έρχεται ειδοποίηση στο κινητό | Η ειδοποίηση ανοίγει τη σελίδα έγκρισης |
| 7 | Εγκρίνεις με biometrics (passkey) | Η έγκριση λύνεται, το merge εκτελείται |
| 8 | Η Σήμερα δείχνει το deliverable | Το αποτέλεσμα είναι ορατό, όχι "agents working" |

## 12. Ρίσκα

| Ρίσκο | Επίπτωση | Μετριασμός |
|---|---|---|
| Agents με πλήρη πρόσβαση στο μηχάνημα (`bypassPermissions`) | Ένας agent αλλάζει αρχεία έξω από το worktree ή διαρρέει credentials | Hook που απορρίπτει push/merge, κανένα credential στο περιβάλλον, προαιρετικό sandbox ή ξεχωριστός OS user, strict mode |
| Πολυπλοκότητα OAuth/DCR | Ο self-hosted server δεν προστίθεται ως connector | Spike στη Φάση 0· fallback σε σταθερό token σε header |
| Όροι συνδρομής | Παραβίαση όρων ή περιορισμοί ορίων | Απόφαση billing στη Φάση 0· API key για προϊόν πάνω στο Agent SDK |
| Έκρηξη κόστους από ιεραρχία και meetings | Απρόβλεπτος λογαριασμός | Budget ανά project, team-size caps, χαμηλό concurrency, 80%/100% όρια |
| Μεγάλα, ώριμα εργαλεία orchestration agents υπάρχουν ήδη | Αδύνατος ανταγωνισμός σε εύρος | Ανταγωνισμός στη γωνία (φωνή, ασφάλεια, meetings), όχι στο εύρος |
| Έλεγχος διεργασιών στα Windows | Ορφανές διεργασίες, ασταθή runs | Interface ανά πλατφόρμα, `taskkill /T`, WSL2/Docker ως επίσημη διαδρομή, CI matrix |
| Οι συζητήσεις περνούν από τρίτο SaaS (Discord, Slack) | Κώδικας και αποφάσεις σε servers τρίτων | Προαιρετικό κανάλι, self-hosted επιλογές (Mattermost, Matrix), η βάση μας μένει η πηγή της αλήθειας |
| Agents του IT με πρόσβαση στα μηχανήματα (τοπικά και μέσω SSH) | Λάθος εντολή ρίχνει υπηρεσία ή μηχάνημα | `strict` mode, μόνο ανάγνωση, χρήστης SSH μόνο για ανάγνωση, διορθώσεις μόνο ως ticket με biometrics |
| Εταιρικά φίλτρα μπλοκάρουν domains υπηρεσιών tunnel | Δεν ανοίγουν login, εγκρίσεις και UI από εταιρικό δίκτυο | Δικό σου domain (Cloudflare Tunnel, Pangolin, Caddy) για καθημερινή χρήση· η φωνή δεν περνά από το εταιρικό δίκτυο |
| Λακωνικό ύφος ή συμπίεση χαλάει την ποιότητα | Λάθη και κακές αποφάσεις των agents | A/B με έλεγχο ποιότητας, ύφος μόνο στο κείμενο και όχι στη σκέψη, `headroom` προαιρετικό |

### Σημείωση billing
Η τεκμηρίωση της Anthropic λέει ότι τα όρια Pro/Max προϋποθέτουν συνηθισμένη ατομική χρήση, και ότι προϊόντα πάνω στο Agent SDK πρέπει να χρησιμοποιούν API keys. Η προγραμματισμένη χρήση πολλών agents σε προσωπική συνδρομή δεν καλύπτεται ρητά: γκρίζα ζώνη. Μέχρι την απόφαση, ο σχεδιασμός υποστηρίζει API key ως default.

## 13. Ανοιχτά ερωτήματα

| # | Ερώτημα | Κατάσταση |
|---|---|---|
| 1 | Συνδρομή ή API key | Αποφασίζεται στη Φάση 0 |
| 2 | Ποιο project είναι το pilot; | Αναποφάσιστο |
| 3 | Πόση αυτονομία έχουν οι managers: σχηματίζουν ομάδες μόνοι τους; Κάνουν merge ή σταματούν σε branch; | Αναποφάσιστο (σήμερα: team creation και merge είναι heavy) |
| 4 | Συχνότητα συσκέψεων (cadence) | Αναποφάσιστο |
| 5 | Default concurrency και budget caps | Αναποφάσιστο (πρόταση concurrency: 1) |

## 14. Επόμενο βήμα

Ξεκίνα τη Φάση 0, βήμα 1: `git init` και γράψε το `.gitignore` πριν από οποιοδήποτε commit. Μετά το spike του Agent SDK (hook που μπλοκάρει `git push` σε `bypassPermissions`, `interrupt()`, resume).
