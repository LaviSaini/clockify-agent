from dotenv import load_dotenv

load_dotenv()

from agent.runner import run_analysis
from report.excel_builder import build_excel_report


def main():
    print("=== LogLens Time Audit Agent ===")
    start_date = input("Enter start date (YYYY-MM-DD): ").strip()
    end_date = input("Enter end date   (YYYY-MM-DD): ").strip()

    print(f"\nRunning analysis for {start_date} to {end_date}...")
    report_data = run_analysis(start_date, end_date)

    print(f"Missing log entries found : {len(report_data.get('missing_logs', []))}")
    print(f"Poor descriptions found   : {len(report_data.get('poor_descriptions', []))}")

    build_excel_report(report_data, start_date, end_date)


if __name__ == "__main__":
    main()
