import os

from dotenv import load_dotenv

load_dotenv()

import db

INACTIVITY_DAYS = int(os.environ.get("INACTIVITY_DAYS", 5 * 365))

if __name__ == "__main__":
    db.init_db()
    deleted = db.delete_inactive_users(INACTIVITY_DAYS)
    print(f"Usuários removidos por inatividade (> {INACTIVITY_DAYS} dias): {deleted}")
