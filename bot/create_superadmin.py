"""Create the superadmin account (or reset its password), from your own computer.

    cd bot
    .venv\\Scripts\\python create_superadmin.py --email youssef@admin.com --name "Youssef"

- The password is typed in the terminal with hidden input (twice). It is never echoed, never accepted as an argument
  (it would stay in the shell history), never written to a file or a log: only its scrypt hash reaches the database.
- If the terminal cannot hide the input, the script stops instead of showing the password.
- Uses the database of bot/.env (DATABASE_URL). This is the only way to create the first superadmin; after that, only
  a superadmin can create, promote or demote another superadmin in "Équipe".
- Running it again with the same email sets the new password, makes the account an active superadmin and ends its
  open sessions.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import warnings

MIN_LENGTH = 12


def ask_password() -> str | None:
    if not sys.stdin.isatty():
        print("Lancez ce script dans un vrai terminal (saisie masquée impossible ici).")
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)  # never fall back to a visible prompt
        try:
            first = getpass.getpass(f"Mot de passe du super-administrateur (min. {MIN_LENGTH} caractères) : ")
            if len(first) < MIN_LENGTH:
                print(f"Trop court ({MIN_LENGTH} caractères minimum).")
                return None
            if getpass.getpass("Confirmer : ") != first:
                print("Les mots de passe ne correspondent pas.")
                return None
        except getpass.GetPassWarning:
            print("Ce terminal ne peut pas masquer la saisie : arrêt (rien n'a été écrit).")
            return None
    return first


def main() -> int:
    ap = argparse.ArgumentParser(description="Create or reset the NAYO superadmin (password typed, hidden).")
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    args = ap.parse_args()
    email, name = args.email.strip().lower(), " ".join(args.name.split())
    if "@" not in email or len(name) < 2:
        print("Email ou nom invalide.")
        return 1

    password = ask_password()
    if password is None:
        return 1

    from app.admin import hash_password
    from app.config import get_settings
    from app.store import Store

    pw_hash = hash_password(password)
    del password
    s = get_settings()
    store = Store(s.state_backend, database_url=s.database_url, sqlite_path=s.sqlite_path)
    what = store.set_superadmin(email, name, pw_hash)
    store.audit("create_superadmin.py", "team.superadmin", "admin_user", email, "compte créé" if what == "created" else "mot de passe réinitialisé")
    print(f"OK : {name} <{email}> est super-administrateur ({'créé' if what == 'created' else 'mis à jour'}).")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
