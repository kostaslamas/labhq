# Σχέδιο έργου: `labhq` — self-hosted project orchestrator

Ημερομηνία: 2026-10-02 · Κατάσταση: Φάση 1 ολοκληρώθηκε, επόμενη η Φάση 2 · Όνομα: `labhq`

## 1. Σκοπός

Για ιδιώτες, hobbyists και developers που δουλεύουν μόνοι τους: ένας άνθρωπος, πολλά projects, μια ομάδα από AI. Χτίζεις έναν open-source, self-hosted orchestrator έργων. Ένας Orchestrator ("CEO") επιβλέπει όλα τα software repos σου. Κάθε έργο έχει Manager, κάθε Manager έχει ομάδες. Μιλάς στο Call Center από όποια AI εφαρμογή χρησιμοποιείς ήδη, με τη φωνή της· το Call Center διαβάζει την κατάσταση χωρίς να διακόπτει τους agents που δουλεύουν.

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
Call Center                     ένας agent ανά κλήση: διαβάζει και δρομολογεί, δεν αποφασίζει
Orchestrator ("CEO")            long-lived, memory, βλέπει ΟΛΑ τα projects
 └─ Manager (ένας ανά project)  long-lived, memory
     └─ Team lead               long-lived, memory
         └─ Worker              ephemeral: ένας ανά task, δικό του git worktree
```

- Το Call Center στέκεται δίπλα στον CEO, όχι πάνω του: απαντά για την κατάσταση, προωθεί ερωτήσεις και απαντήσεις, αλλά δεν αναθέτει, δεν αποφασίζει και δεν εγκρίνει (§3.5, ADR 0004).
- Κάθε agent κρατά ενημερωμένο το `.labhq/status.md` στο worktree του, με τα πεδία του handoff (`summary`, `done`, `next`, `blockers`, `refs`) και `questions`. Η μηχανή περνά κάθε αλλαγή στη βάση. Το labhq βάζει το `.labhq/` στο `.git/info/exclude` κάθε repo όπου δουλεύει (ένα αρχείο για όλα τα worktrees του), ώστε ένα `git add -A` να μην κάνει commit τα status και rules αρχεία (ADR 0004).
- Ο CEO αναλαμβάνει και agent που ήδη τρέχει ένα project, ως manager του (ADR 0005): στο τέλος του γύρου η αρχική διεργασία κλείνει και η συζήτηση συνεχίζει στον ιδιωτικό tmux, στον ίδιο φάκελο. Ο manager μαθαίνει τους κανόνες του labhq· η μηχανή τους ελέγχει, δεν τον εμπιστεύεται.

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

Δεν γράφουμε κώδικα φωνής. Το προϊόν εκθέτει έναν MCP server (Streamable HTTP). Προσθέτεις τον server ως connector στην AI εφαρμογή που ήδη χρησιμοποιείς (ChatGPT, Claude, Grok…) και μιλάς στο Call Center με το voice chat της. Η εφαρμογή έχει δική της κρίση για το τι θα ρωτήσει και πότε.

```
Εσύ ──φωνή──> AI app (ChatGPT / Claude / Grok)
                 │  MCP, Streamable HTTP
                 ▼
            labhq MCP server ──> engine ──> agents
                 │
                 └──> notifier (Web Push / ntfy / Telegram) ──> εσύ
```

### 3.2 Κανόνες σχεδίασης

1. Λίγα tools. Κάθε tool έχει ένα σαφές όνομα και ένα σκοπό.
2. Γρήγορες επιστροφές. Η μακρά δουλειά είναι async με tickets: `ask_ceo` επιστρέφει ticket, το `get_reply` το εξαργυρώνει.
3. Οι απαντήσεις γράφονται για να ακουστούν: σύντομες προτάσεις, χωρίς πίνακες, χωρίς JSON.
4. Σωστά MCP annotations: `readOnlyHint` στις ερωτήσεις (περνούν χωρίς επιβεβαίωση), `destructiveHint` στις ενέργειες (ζητούν επιβεβαίωση).
5. Οι κανόνες ζουν μέσα στα tools (description, αποτελέσματα, σφάλματα). Οι clients τιμούν ανομοιόμορφα το server `instructions`, άρα δεν βασιζόμαστε σε αυτό.
6. Οι voice assistants δεν μπορούν να σου στείλουν push. Οι ειδοποιήσεις περνούν από pluggable notifier: default το Web Push της web εφαρμογής του labhq, εγκατεστημένης στην αρχική οθόνη του κινητού· ntfy και Telegram προαιρετικά. Μια εξωτερική πύλη έγκρισης μπορεί να αναλάβει τις heavy εγκρίσεις (ADR 0007).

### 3.3 Υποψήφια tools

| Tool | Είδος | Annotation | Σκοπός |
|---|---|---|---|
| `brief` | ανάγνωση | `readOnlyHint` | Τι έγινε, τι χρειάζεται εσένα |
| `inbox` | ανάγνωση | `readOnlyHint` | Εκκρεμείς εγκρίσεις και ερωτήσεις |
| `decide` | εγγραφή | `destructiveHint` για βαριές | Εγκρίνει/απορρίπτει (οι βαριές μόνο ζητούνται, βλ. §5) |
| `order` / `assign` | εγγραφή | write | Δίνει εντολή ή αναθέτει task |
| `ask_ceo` | async | write | Ρωτά το Call Center (agent ανά κλήση), επιστρέφει ticket |
| `get_reply` | ανάγνωση | `readOnlyHint` | Παραλαβή απάντησης από ticket |
| `meeting_minutes` | ανάγνωση | `readOnlyHint` | Πρακτικά σύσκεψης |
| `health` | ανάγνωση | `readOnlyHint` | Κατάσταση μηχανημάτων και ανοιχτά incidents |

Η τελική λίστα κλειδώνει στη Φάση 2, μετά από δοκιμή με φωνή.

### 3.4 Τι έχει ήδη αποδειχθεί

Δουλεύει ήδη στην πράξη: ένας custom MCP server (Streamable HTTP) πίσω από tunnel χρησιμοποιείται καθημερινά με φωνή. Η βάση του Call Center είναι αποδεδειγμένη, όχι υπόθεση. Το Gemini (consumer) μένει εκτός, γιατί δεν δέχεται custom MCP.

### 3.5 Πρόγραμμα και agent ανά κλήση (ADR 0004)

- Το πρόγραμμα (μηχανή και MCP server) τρέχει πάντα. Ό,τι απαντιέται από τη βάση (projects, tasks, εγκρίσεις, κόστος, υγεία) το απαντά μόνο του, σε <2 s, χωρίς agent.
- Ό,τι θέλει ανάγνωση και κρίση πηγαίνει σε έναν Call Center agent ανά κλήση, σε tmux (ADR 0003). Κλήση είναι ένα παράθυρο χρόνου: ερωτήσεις μέσα σε 5 λεπτά (ρυθμιζόμενο) κάνουν resume το ίδιο session. Δύο ταυτόχρονες κλήσεις είναι δύο agents.
- Ο agent απαντά από το status των agents όταν είναι φρέσκο, δηλαδή νεότερο από την τελευταία δραστηριότητά τους (`run_events` ή αλλαγή οθόνης). Όταν είναι μπαγιάτικο, διαβάζει την οθόνη τους με `capture-pane`. Δεν στέλνει ποτέ πλήκτρα σε agent που δουλεύει.
- Τα εσωτερικά tools του (ανάγνωση βάσης, status, events, οθόνης· παράδοση μηνύματος· interrupt) έρχονται από stdio MCP server που ξεκινά το ίδιο το CLI. Δεν ανοίγει θύρα, δεν έχει shell, δεν γράφει αρχεία.
- Οι ερωτήσεις των agents (`questions` στο status) γίνονται γραμμές στη βάση και φτάνουν στον χρήστη αμέσως από τον notifier, χωρίς agent. Η απάντηση του χρήστη πηγαίνει στον agent που ρώτησε, βάσει id, το πολύ μία φορά.
- Παράδοση μηνύματος σε agent: στο τέλος του γύρου του, ως wakeup. Αν ο χρήστης το ζητήσει ρητά στην ίδια κλήση, interrupt και παράδοση αμέσως.
- Το κείμενο της οθόνης και των logs μπορεί να κουβαλά εντολές, και οι agents που δουλεύουν τρέχουν σε `bypassPermissions`. Γι' αυτό ένα μήνυμα που παραδίδεται είναι αυτούσια τα λόγια του χρήστη από την τρέχουσα κλήση, αποθηκευμένα με την κλήση και το id του αιτήματος, ποτέ κείμενο που συνέθεσε το μοντέλο. Παραλήπτης είναι agent με εκκρεμή ερώτηση ή agent που ονόμασε ο χρήστης. Κάθε παράδοση καταγράφεται (ADR 0004).

## 4. Τεχνολογίες

Ακολουθούμε τις μηχανικές συμβάσεις (θα γραφτούν στο `CONTRIBUTING.md`): Python με PEP 8/484, ruff, pytest, pydantic, uv· migrations ως μοναδική αρχή σχήματος· χρήματα σε integer micro-USD (ADR 0002)· UTC instants.

### 4.1 Backend

| Θέμα | Επιλογή |
|---|---|
| Γλώσσα / εργαλεία | Python 3.12, `uv`, FastAPI, pydantic, pytest, ruff |
| Βάση | SQLite (ένας χρήστης), Alembic migrations. Ποτέ `create_all` στον κώδικα εφαρμογής |
| Χρήμα | Integer micro-USD (`*_micros`, ADR 0002), ποτέ float |
| Χρόνος | UTC timezone-aware instants |
| Workers | Claude Agent SDK για Python (`ClaudeSDKClient`)· tmux adapter για οποιονδήποτε CLI agent (ADR 0003) |
| MCP server | `mcp` SDK 2.x (`MCPServer`, όχι `FastMCP`): stateless Streamable HTTP, JSON χωρίς SSE |
| Adapters | Registry (dispatch as data): Claude μέσω SDK πρώτα· `tmux` για Claude Code, Codex, Gemini CLI και Aider· Ollama/local αργότερα |

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
| Light | Έναρξη σύσκεψης, ανάθεση task, αλλαγή priority, διακοπή (interrupt) agent, ανάληψη agent που ήδη τρέχει | Φωνή ή tap |
| Heavy | Merge στο main, push, διαγραφή branch ή project, δημιουργία ομάδας, υπέρβαση budget, παρέμβαση σε μηχάνημα (restart, καθάρισμα, updates, reboot) | Ο voice agent μπορεί μόνο να ΖΗΤΗΣΕΙ. Η έγκριση απαιτεί ισχυρή επιβεβαίωση |

Τις βαριές ενέργειες τις εκτελεί η μηχανή, όχι ο agent: ο agent τις ζητά, η μηχανή τις εκτελεί μόνο μετά την έγκριση.

Ισχυρή επιβεβαίωση:

- Στην open-source έκδοση: ενσωματωμένο passkey/WebAuthn στο UI μας.
- Εξωτερικές πύλες έγκρισης (π.χ. ένα υπάρχον Face ID gate) μπαίνουν ως plugin.
- Η ειδοποίηση για heavy έγκριση ανοίγει απευθείας σελίδα έγκρισης με biometrics (passkey) στο κινητό. Άλλο UI στο κινητό δεν χρειάζεται.

Κανόνες:

1. Default: `--dangerously-skip-permissions` (`bypassPermissions`), ώστε οι agents να δουλεύουν χωρίς διακοπές μέσα στο worktree τους.
2. Εξαίρεση: οι agents του IT/Infra τρέχουν σε `strict` με εντολές μόνο για ανάγνωση (§2.2).
3. Προαιρετικό αυστηρό mode (`strict`): κάθε tool εκτός allowlist περνά από έγκριση μέσω `can_use_tool`. Το Claude Code εγκρίνει μόνο του όσες εντολές θεωρεί read-only, οπότε το strict mode συμπληρώνεται με PreToolUse hook.
4. Η έγκριση νέων agents είναι on by default.
5. Οι agents δεν κάνουν push ή merge μόνοι τους: PreToolUse hook που αναλύει την εντολή (όχι απλή αναζήτηση κειμένου, που παρακάμπτεται π.χ. με `git -c x=y push`) απορρίπτει `git push`, `gh pr merge` και παρόμοια, το push URL του worktree είναι απενεργοποιημένο, και κανένα git credential δεν υπάρχει στο περιβάλλον του worker. Η Φάση 0 επιβεβαίωσε ότι το hook ισχύει και σε `bypassPermissions`.
6. Sandbox με rootless Podman, default όταν το Podman υπάρχει στο μηχάνημα (ADR 0008), ή ξεχωριστός OS user, για πραγματική απομόνωση: σε `bypassPermissions` ο agent έχει πρόσβαση σε ό,τι έχει ο χρήστης του server. Συνιστάται για κάθε agent που αναλήφθηκε ενώ έτρεχε (ADR 0005): στο main checkout του χρήστη τα επίπεδα του κανόνα 5 αποθαρρύνουν το push αλλά δεν το εγγυώνται (π.χ. `env -u GIT_CONFIG_COUNT git push`, κλειδί SSH από τον δίσκο, script που παρακάμπτει το hook).
7. Ένας voice client δεν μπορεί ποτέ να εκδώσει heavy approval, ούτε αν το ζητήσει ο ίδιος ο agent.
8. Κάθε έγκριση καταγράφεται με payload, κλάση ρίσκου, αποφασίζοντα και χρόνο.

## 6. Μοντέλο δεδομένων

Ελάχιστο σύνολο. Όλα τα timestamps σε UTC, τα ποσά σε integer micro-USD (ADR 0002).

| Πίνακας | Βασικές στήλες / ρόλος |
|---|---|
| `projects` | `id`, `name`, `repo_path`, `budget_micros`, `status` |
| `agents` | `role`, `title`, `reports_to`, `project_id`, `adapter`, `config`, `budget_micros` |
| `tasks` | `status`, `priority`, `parent_id`, `assignee`, `checkout_run_id` (atomic checkout lock) |
| `comments` | σχόλια και mentions σε tasks |
| `meetings` | `kind`, `agenda`, `status`, `channel_adapter`, `external_ref` (thread)· παιδιά: `meeting_participants`, `meeting_transcript_entries`, `meeting_decisions`, `meeting_action_items` |
| `wakeup_requests` | `source`, `reason`, `coalesced_count`, `idempotency_key` |
| `runs` | `status`, `session_id_before`, `session_id_after`, `usage`, `exit` |
| `run_events` | γεγονότα ροής ανά run |
| `cost_events` | κόστος ανά run/agent/project σε micro-USD (`cost_micros`) |
| `approvals` | `type`, `risk_class`, `status`, `payload` |
| `agent_task_sessions` | αντιστοίχιση agent + task σε session για resume |
| `hosts` | `name`, `address`, `ssh_user`, `status` |
| `health_samples` | `host_id`, `metric`, `value`, `sampled_at` |
| `health_rules` | `type`, `params`, `action` (`notify` ή `ticket`), `reason`, `created_by`, `enabled` |
| `incidents` | `rule_id`, `host_id`, `status`, `task_id` (το ticket) |
| `usage_readings` | μετρήσεις usage σε μονάδες εκτός USD, από το statusline JSON του Claude Code ή από την οθόνη: `agent_id`, `run_id`, `unit`, `window`, `value`, `resets_at` (ADR 0003) |
| `status_updates` | το `.labhq/status.md` κάθε agent ανά αλλαγή, με χρόνο (ADR 0004) |
| `agent_questions` | ερωτήσεις agents προς τον χρήστη: `agent_id`, `task_id`, `status`, `answer` (ADR 0004) |
| `calls` | κλήσεις του Call Center: `session_id`, `last_activity_at`, `status` (ADR 0004) |
| `call_requests` | κάθε `ask_ceo` μιας κλήσης: `call_id`, `request_id`, `text` (ADR 0004) |
| `deliveries` | κάθε μήνυμα του Call Center προς agent: `call_id`, `request_id`, `recipient`, `text`, `interrupted`, χρόνος (ADR 0004) |

Αναλλοίωτα:

- Το `tasks.checkout_run_id` αλλάζει με ατομικό conditional update: ένα task έχει το πολύ ένα ενεργό run.
- Το `wakeup_requests.idempotency_key` είναι unique, ώστε οι επαναλήψεις να μη διπλασιάζουν δουλειά.
- Ένα `meeting_action_items` row δημιουργεί task και κρατά αναφορά σε αυτό.
- Ένα `agent_questions` row απαντιέται το πολύ μία φορά, με ατομικό conditional update.

## 7. Χρονοπρογραμματιστής

Ο scheduler ξυπνά agents από πέντε πηγές: timer, ανάθεση, comment/mention, επίλυση έγκρισης, σύσκεψη.

Κανόνες:

1. Coalescing: όσο ένας agent τρέχει, νέα wakeups συγχωνεύονται σε ένα (αυξάνεται το `coalesced_count`).
2. Concurrency ανά agent με ΧΑΜΗΛΟ default (πρόταση: 1).
3. Έλεγχος budget στο enqueue και ξανά πριν την εκκίνηση.
4. Προειδοποίηση στο 80% του budget, σκληρό σταμάτημα στο 100%.
5. Stale-run reaper: runs χωρίς heartbeat μέσα σε όριο κλείνουν ως `failed`.
6. Timeouts ανά run, ρυθμιζόμενα στο `agents.config`.
7. Σε συνδρομή, οι agents του labhq χρησιμοποιούν μέρος κάθε παραθύρου του plan (ADR 0003): για κάθε παράθυρο που αναφέρουν οι μετρήσεις (πεντάωρο και εβδομαδιαίο), προειδοποίηση στο 50% και κανένα νέο run γι' αυτό το είδος agent από το 70% μέχρι το reset του παραθύρου, ώστε το 30% να μένει για τη δική σου χρήση. Τα δύο όρια είναι ρυθμίσεις. Οι γύροι που τρέχουν δεν κόβονται. Αν παρ' όλα αυτά η οθόνη ενός CLI δείξει μήνυμα ορίου, κανένα νέο run μέχρι το reset, με ειδοποίηση στον χρήστη. Αν το `agents.config` ορίζει εναλλακτικό είδος agent, το task συνεχίζει εκεί από το status και τα commits.

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
- tmux μόνο για τον `tmux` adapter (ADR 0003). Στα native Windows τρέχει μόνο ο SDK adapter.
- Ο ιδιωτικός tmux server ξεκινά με το allowlisted περιβάλλον και κενό `update-environment` πριν από κάθε session· κάθε session παίρνει τις μεταβλητές του ρητά με `new-session -e`. Αλλιώς το tmux αντιγράφει από τον client μεταβλητές όπως το `SSH_AUTH_SOCK`.

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
| Ειδοποιήσεις | Web Push από τη web εφαρμογή του labhq (ADR 0007) | ntfy, Telegram ή εξωτερική πύλη έγκρισης | Ανοίγει το link στο κινητό, το προσθέτει στην αρχική οθόνη και επιτρέπει τις ειδοποιήσεις |
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

Κατάσταση: τα spikes πέρασαν και το ADR 0001 έγινε δεκτό (2026-10-02): default το υπάρχον login του Claude Code (συνδρομή), API key όταν υπάρχει `ANTHROPIC_API_KEY`.

Στόχος: να μετρηθούν τα ρίσκα πριν γραφτεί η μηχανή.

Βήματα:

1. `git init` και `.gitignore` πριν το πρώτο commit.
2. Agent SDK spike: σε `bypassPermissions` ένα PreToolUse hook μπλοκάρει `git push`· `interrupt()`· resume· και `can_use_tool` σε αναμονή για το strict mode.
3. Έκθεση και auth χωρίς Cloudflare Access: δοκιμαστικός MCP με ακίνδυνο tool και ενσωματωμένο auth (token σε header και secret path), JSON χωρίς SSE. Η φωνή μέσω custom MCP είναι ήδη αποδεδειγμένη (§3.4), οπότε δεν χρειάζεται νέα δοκιμή φωνής.
4. Απόφαση billing: συνδρομή ή API key (βλ. §12). Αποφασίστηκε: συνδρομή ως default (ADR 0001).

Κριτήρια αποδοχής:

- Script spike δείχνει: σε `bypassPermissions` ένα PreToolUse hook μπλοκάρει `git push`· ένα `interrupt()` σταματά run· ένα resume κρατά context· σε strict mode ένα `can_use_tool` μένει σε αναμονή >60 s και συνεχίζει μετά την απάντηση.
- Ο δοκιμαστικός MCP περνά τα tests: 401 χωρίς token ή με λάθος token, `initialize`, `tools/list` και `tools/call` με σωστό token, απαντήσεις JSON χωρίς SSE, secret path.
- ADR για billing στο `docs/adr/`.
- Το repo έχει `.gitignore` πριν το πρώτο commit, και tag `v0.0.1-spike` με τα αποτελέσματα.

### Φάση 1 — Engine

Κατάσταση: ολοκληρώθηκε (2026-10-03), tag `v0.1.0-alpha.1`. Και οι τέσσερις χειροκίνητοι έλεγχοι πέρασαν με πραγματικό login (`docs/checks/`). Το A/B του `rtk` βρήκε δύο bugs που τα tests δεν έπιαναν· διορθώθηκαν πριν το tag.

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
- Ένα `interrupt()` καταγράφει το run ως `interrupted`, όχι ως `failed` (το SDK το επιστρέφει ως `error_during_execution` με `terminal_reason` `aborted_streaming`) (test).
- ruff, τύποι και έλεγχος μεγέθους αρχείων περνούν στο CI. Tag `v0.1.0-alpha.1`.

Εκτέλεση: ένα GitHub issue ανά κομμάτι, ένα cloud session (`claude --cloud`) ανά issue, ένα PR ανά session. Τα κύματα τρέχουν παράλληλα μέσα τους και σειριακά μεταξύ τους. Κάθε issue κατέχει δικούς του φακέλους (`CLAUDE.md`), ώστε τα παράλληλα sessions να μη συγκρούονται.

| Κύμα | Issue | Περιεχόμενο |
|---|---|---|
| 0 | Foundation | Σκελετός πακέτου, ruff, mypy, pytest, CI, settings, clock, `money`, όλα τα μοντέλα και τα migrations, έλεγχος μεγέθους αρχείων |
| 0 | CI guards | gitleaks, απαγορευμένοι όροι από repository secret, guard για αναφορές σε credentials (ADR 0001) |
| 1 | Adapters and runs | Registry, fake adapter, Claude adapter, κύκλος ζωής run, `run_events`, `cost_events`, `interrupted` |
| 1 | Worktrees and push guard | Worktree ανά task, parsed-command hook, απενεργοποιημένο push URL, περιβάλλον χωρίς credentials |
| 1 | Health and rules | Collector για το τοπικό μηχάνημα, registry κανόνων, κανόνας ορίου, incidents |
| 1 | Token economy | Ύφος ανά αποδέκτη, δομημένα handoffs, `rtk` hook |
| 1 | Budgets | Υπολογισμός κόστους ανά agent και project, προειδοποίηση στο 80%, σταμάτημα στο 100% |
| 2 | Scheduler | Wakeups, idempotency, coalescing, concurrency, ατομικό checkout, έλεγχος budget στο enqueue και πριν την εκκίνηση, timeouts, reaper |
| 2 | Approvals | `approvals` με κλάση ρίσκου ως δεδομένα, push μόνο μετά την έγκριση, εκτέλεση από τη μηχανή |
| 3 | CLI and demo | Εντολές CLI, demo από άκρη σε άκρη, χειροκίνητοι έλεγχοι στο `docs/checks/` |

Μετά το CLI and demo: ένα issue για τον `tmux` adapter (ADR 0003), και μετά από αυτό ένα για την ανάληψη agent που ήδη τρέχει (ADR 0005). Δεν είναι κριτήρια της Φάσης 1· τα κριτήρια της Φάσης 1 καλύπτονται από τον SDK adapter.

Τα tests δεν καλούν ποτέ πραγματικό μοντέλο. Το demo με πραγματικό login και το A/B του `rtk` τρέχουν τοπικά, και τα αποτελέσματα μπαίνουν στο `docs/checks/`. Το tag μπαίνει τοπικά, μετά το gate.

### Φάση 2 — Call Center (MCP)

Περιεχόμενο: τα tools, annotations, async tickets, απαντήσεις του προγράμματος από τη βάση, ερωτήσεις των agents προς τον χρήστη με ειδοποίηση (§3.5), δοκιμή με φωνή σε Claude και ChatGPT.

Κριτήρια αποδοχής:

- Ο MCP server περνά έλεγχο με MCP inspector· κάθε tool έχει σωστά `readOnlyHint`/`destructiveHint` (test που τα διαβάζει).
- `ask_ceo` επιστρέφει ticket σε <2 s ανεξάρτητα από τη διάρκεια της δουλειάς· το `get_reply` το εξαργυρώνει.
- Καμία απάντηση tool δεν περιέχει πίνακα markdown ή JSON σε πεδίο φωνής (test).
- Ένα `decide` για heavy ενέργεια επιστρέφει "ζητήθηκε έγκριση" και δημιουργεί `approvals` row· δεν εκτελεί.
- Live δοκιμή με φωνή: τουλάχιστον μία εφαρμογή (Claude ή ChatGPT) ολοκληρώνει το σενάριο brief → ask_ceo → get_reply. Καταγράφεται βίντεο.
- Ο notifier στέλνει μήνυμα (ntfy ή Telegram) όταν δημιουργείται έγκριση.
- Μια ερώτηση agent φτάνει στον χρήστη από τον notifier· η απάντησή του πηγαίνει μόνο στον agent που ρώτησε, μία φορά, ακόμα και με δύο ταυτόχρονες απαντήσεις (test).
- Το `health` απαντά με προφορικό κείμενο για την κατάσταση των μηχανημάτων (test).
- Ο MCP server απαντά με JSON χωρίς SSE και δουλεύει πίσω από Cloudflare quick tunnel (test).
- Ένας custom connector του Claude συνδέεται στον MCP με σταθερό credential ή secret path, χωρίς Cloudflare Access (demo).
- Tag `v0.2.0-alpha.1`.

Εκτέλεση: issues #31–#40 στο milestone «Phase 2: Call Center (MCP)», με την ίδια μορφή και τα ίδια labels με τη Φάση 1. Ο Call Center agent τρέχει με τον SDK adapter μέχρι να έρθει ο tmux adapter (τροποποίηση του ADR 0004).

| Κύμα | Issue | Περιεχόμενο |
|---|---|---|
| 0 | #31 Foundation | Πίνακες του ADR 0004 και outbox ειδοποιήσεων, εξαρτήσεις (`mcp`, `httpx`, `uvicorn`), `labhq.speech`, `labhq.work` |
| 1 | #32 Notifier | ntfy (default) και Telegram, outbox που στέλνει μία φορά, ειδοποίηση για έγκριση και για ερώτηση agent |
| 1 | #33 MCP server | Stateless HTTP με JSON, bearer ή secret path, registry από tools |
| 1 | #34 Program answers | `brief`, `inbox`, `health` από τη βάση, σε προφορικό κείμενο, <2 s |
| 1 | #35 Decide and order | Light εγκρίσεις από φωνή, heavy μόνο ζητούνται· νέο task με ανάθεση |
| 1 | #36 Agent questions | `.labhq/status.md`, ερωτήσεις προς τον χρήστη, απάντηση μία φορά, αυτούσια παράδοση |
| 2 | #37 Exposure | Cloudflare quick tunnel με `--config /dev/null`, URL του connector |
| 2 | #38 Call Center tools | Τα tools στο MCP με annotations, έλεγχος φωνής, MCP inspector στο CI |
| 3 | #39 ask_ceo and get_reply | Agent ανά κλήση, tickets <2 s, resume μέσα στο παράθυρο, `deliver`/`interrupt` με όρια |
| — | #40 Owner tasks | ntfy στο κινητό, connector, δοκιμή φωνής με βίντεο, tag |

### Φάση 3 — Hierarchy & meetings

Περιεχόμενο: CEO → managers → leads → workers, δημιουργία ομάδας με έγκριση, standup/planning/review με πρακτικά → tasks, Discord adapter για τις συσκέψεις, τμήμα IT/Infra (κανόνες από agent, tickets, SSH), `graphify` index ανά project, Call Center agent ανά κλήση με status αρχεία και ανάγνωση οθόνης (§3.5).

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
- Ο Call Center απαντά για ένα project από φρέσκο status χωρίς να στείλει τίποτα στον manager· με μπαγιάτικο status διαβάζει την οθόνη του (test).
- Δύο ταυτόχρονες κλήσεις εξυπηρετούνται από δύο agents· μια ερώτηση μέσα στο παράθυρο της κλήσης κάνει resume το ίδιο session (test).
- Ο Call Center παραδίδει σε agent μόνο αυτούσια λόγια του χρήστη από την τρέχουσα κλήση, σε agent με εκκρεμή ερώτηση ή που ονόμασε ο χρήστης· interrupt μόνο με ρητό αίτημα στην ίδια κλήση· κάθε παράδοση καταγράφεται (test).
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
| 2 | Ρωτάς το Call Center τι έκαναν οι ομάδες το βράδυ | `brief` απαντά με 3-4 σύντομες προτάσεις |
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
| Όροι συνδρομής | Παραβίαση όρων ή περιορισμοί ορίων | Ειδοποίηση στην εγκατάσταση, χαμηλό concurrency και budgets, API key ως εναλλακτική, γραπτή ερώτηση στην Anthropic πριν το 1.0 |
| Έκρηξη κόστους από ιεραρχία και meetings | Απρόβλεπτος λογαριασμός | Budget ανά project, team-size caps, χαμηλό concurrency, 80%/100% όρια |
| Μεγάλα, ώριμα εργαλεία orchestration agents υπάρχουν ήδη | Αδύνατος ανταγωνισμός σε εύρος | Ανταγωνισμός στη γωνία (φωνή, ασφάλεια, meetings), όχι στο εύρος |
| Έλεγχος διεργασιών στα Windows | Ορφανές διεργασίες, ασταθή runs | Interface ανά πλατφόρμα, `taskkill /T`, WSL2/Docker ως επίσημη διαδρομή, CI matrix |
| Οι συζητήσεις περνούν από τρίτο SaaS (Discord, Slack) | Κώδικας και αποφάσεις σε servers τρίτων | Προαιρετικό κανάλι, self-hosted επιλογές (Mattermost, Matrix), η βάση μας μένει η πηγή της αλήθειας |
| Agents του IT με πρόσβαση στα μηχανήματα (τοπικά και μέσω SSH) | Λάθος εντολή ρίχνει υπηρεσία ή μηχάνημα | `strict` mode, μόνο ανάγνωση, χρήστης SSH μόνο για ανάγνωση, διορθώσεις μόνο ως ticket με biometrics |
| Εταιρικά φίλτρα μπλοκάρουν domains υπηρεσιών tunnel | Δεν ανοίγουν login, εγκρίσεις και UI από εταιρικό δίκτυο | Δικό σου domain (Cloudflare Tunnel, Pangolin, Caddy) για καθημερινή χρήση· η φωνή δεν περνά από το εταιρικό δίκτυο |
| Ανάγνωση οθόνης στον `tmux` adapter (τέλος γύρου, usage, όριο) | Μια αλλαγή στη μορφή ενός CLI σπάει την ανίχνευση ή δίνει λάθος νούμερα | Για το Claude Code, usage από το `rate_limits` του statusline JSON χωρίς οθόνη· για τα υπόλοιπα, fixtures οθόνης ανά agent στα tests, extractor με έλεγχο σχήματος και αυτούσιων αριθμών, αποτυχημένη μέτρηση ποτέ ως μηδέν |
| Ένας agent που αναλήφθηκε ενώ έτρεχε δουλεύει στο main checkout, όχι σε worktree | Push με κλειδί SSH από τον δίσκο, αλλαγές στο checkout του χρήστη | Push απενεργοποιημένο μέσω `GIT_CONFIG_COUNT` στο περιβάλλον του και parsed-command hook, που αποθαρρύνουν αλλά δεν εγγυώνται· sandbox ή ξεχωριστός OS user ως συνιστώμενη ρύθμιση, ο μόνος τρόπος που αποκλείει το push (§5, κανόνας 6)· ειδοποίηση για κάθε αλλαγή στο checkout μετά την ανάληψη (ADR 0005) |
| Λακωνικό ύφος ή συμπίεση χαλάει την ποιότητα | Λάθη και κακές αποφάσεις των agents | A/B με έλεγχο ποιότητας, ύφος μόνο στο κείμενο και όχι στη σκέψη, `headroom` προαιρετικό |

### Σημείωση billing
Η τεκμηρίωση της Anthropic λέει ότι τα όρια Pro/Max προϋποθέτουν συνηθισμένη ατομική χρήση, και ότι προϊόντα πάνω στο Agent SDK πρέπει να χρησιμοποιούν API keys. Η προγραμματισμένη χρήση πολλών agents σε προσωπική συνδρομή δεν καλύπτεται ρητά: γκρίζα ζώνη. Απόφαση (ADR 0001): default το υπάρχον login του Claude Code (συνδρομή)· API key όταν υπάρχει `ANTHROPIC_API_KEY`. Το labhq δεν αγγίζει ποτέ credentials.

## 13. Ανοιχτά ερωτήματα

| # | Ερώτημα | Κατάσταση |
|---|---|---|
| 1 | Ποιο project είναι το pilot; | Αναποφάσιστο |
| 2 | Πόση αυτονομία έχουν οι managers: σχηματίζουν ομάδες μόνοι τους; Κάνουν merge ή σταματούν σε branch; | Αναποφάσιστο (σήμερα: team creation και merge είναι heavy) |
| 3 | Συχνότητα συσκέψεων (cadence) | Αναποφάσιστο |
| 4 | Default concurrency και budget caps | Αναποφάσιστο (πρόταση concurrency: 1) |

## 14. Επόμενο βήμα

Ξεκίνα το κύμα 0 της Φάσης 2: το #31 (Foundation). Τα πέντε issues του κύματος 1 (#32–#36) ξεκινούν παράλληλα μόλις γίνει merge. Τα #25 (tmux adapter) και #27 (ανάληψη agent) μπορούν να τρέξουν δίπλα, χωρίς να είναι κριτήρια καμίας φάσης.
