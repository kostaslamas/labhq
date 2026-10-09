# ruff: noqa: RUF001
"""User-facing wording (Greek, as the owner reads it) for login messages.

Nothing here quotes a screen, a code or a credential: only the tool's name and its link.
"""

TITLE = "Το {tool} θέλει login"
WITH_LINK = "Το {tool} θέλει login: {link}"
WITH_CODE = (
    " Αν μετά ζητήσει κωδικό, επικόλλησέ τον μόνος σου στο τερματικό "
    "(tmux -L {socket} attach -t {pane}). Το labhq δεν μεταφέρει κωδικούς."
)
NO_LINK = (
    "Το {tool} θέλει login αλλά δεν βρήκα σύνδεσμο. Τρέξε `{command}` στο τερματικό σου "
    "και ολοκλήρωσε το login εκεί."
)
NO_LOGIN_COMMAND = (
    "Το {tool} θέλει login αλλά δεν έχει δικό του login. Όρισε το κλειδί του πάροχου "
    "στο περιβάλλον του."
)
CONFIRMED = (
    "Το {tool} είναι πλέον συνδεδεμένο. Ο CEO επιβεβαιώνει: οι agents του μπορούν να δουλέψουν."
)
EXPIRED = "Το login του {tool} έληξε χωρίς να ολοκληρωθεί. Ζήτα καινούργιο όταν θες."
