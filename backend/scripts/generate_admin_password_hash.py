import getpass

import bcrypt


def main() -> None:
    pw = getpass.getpass("Admin password (input hidden): ")
    if not pw:
        raise SystemExit("Password cannot be empty.")
    pw2 = getpass.getpass("Confirm password: ")
    if pw != pw2:
        raise SystemExit("Passwords do not match.")

    hashed = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    print()
    print("ADMIN_PASSWORD_HASH=" + hashed)


if __name__ == "__main__":
    main()

