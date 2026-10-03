import warnings

from dotenv import load_dotenv

from askyourdb import AnalystConfig, SQLAnalyst
from askyourdb.observability import configure_langsmith

warnings.filterwarnings("ignore")
QUESTION = "Which five students owe the most in unpaid fees?"


def main():
    """Demo against the bundled school database (see db/README.md and .env.example)."""
    load_dotenv()
    configure_langsmith()
    with SQLAnalyst(AnalystConfig.from_env()) as analyst:
        result = analyst.ask(QUESTION)

    if result["success"]:
        print("\nSQL query executed successfully.")
        print(result["sql_used"])
        print(result["rows"])
        print(result["answer"])
    else:
        print("\nQuery workflow failed.")
        print(result["error"])
        print(result["sql_used"])
        print(result["rows"])


if __name__ == "__main__":
    main()
