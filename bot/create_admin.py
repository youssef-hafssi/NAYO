"""Create (or reset the password of) a team member for the admin inbox at /admin.

    .venv\\Scripts\\python create_admin.py --email sara@nayo.ma --name "Sara"

The password is asked without being shown. It is stored as a scrypt hash, never in clear.
With --sql the script only prints an INSERT statement (to paste in Supabase → SQL editor) instead of writing.
Running it again with the same email updates the name and password.
"""

from __future__ import annotations

import argparse
import getpass
import sys
import uuid

from app.admin import hash_password
from app.config import get_settings
from app.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True, help="shown to customers' threads as the agent name, e.g. Sara")
    ap.add_argument("--password", help="avoid on shared machines: it stays in the shell history")
    ap.add_argument("--sql", action="store_true", help="print an INSERT statement instead of writing to the database")
    args = ap.parse_args()

    password = args.password or getpass.getpass("Mot de passe (min. 10 caractères) : ")
    if len(password) < 10:
        print("Mot de passe trop court (10 caractères minimum).")
        return 1
    if not args.password and getpass.getpass("Confirmer : ") != password:
        print("Les mots de passe ne correspondent pas.")
        return 1

    admin_id, email, name, pw_hash = uuid.uuid4().hex, args.email.strip().lower(), args.name.strip(), hash_password(password)
    if args.sql:
        q = lambda s: "'" + s.replace("'", "''") + "'"  # noqa: E731
        print(
            "INSERT INTO admin_users (id, email, password_hash, name) VALUES "
            f"({q(admin_id)}, {q(email)}, {q(pw_hash)}, {q(name)}) "
            "ON CONFLICT (email) DO UPDATE SET password_hash = excluded.password_hash, name = excluded.name;"
        )
        return 0

    s = get_settings()
    store = Store(s.state_backend, database_url=s.database_url, sqlite_path=s.sqlite_path)
    store.upsert_admin(admin_id, email, pw_hash, name)
    print(f"OK : {name} <{email}> peut se connecter sur /admin")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
