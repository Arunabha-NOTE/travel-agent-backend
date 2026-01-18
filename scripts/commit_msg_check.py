import re
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        print("❌ Commit message file path not provided")
        sys.exit(1)

    msg_file = Path(sys.argv[1])
    msg = msg_file.read_text(encoding="utf-8").strip()

    pattern = r"^(feat|fix|chore|docs|refactor|test|ci)(\(.+\))?: .+"

    if not re.match(pattern, msg):
        print("❌ Invalid commit message.\n")
        print("Expected format:")
        print("  feat: short description")
        print("  fix(auth): short description\n")
        print("Allowed types: feat, fix, chore, docs, refactor, test, ci")
        sys.exit(1)


if __name__ == "__main__":
    main()
