import requests
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import time
import os

# ===== CONFIG =====
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")

REST_URL = "https://rest.runpod.io/v1/pods"
GRAPHQL_URL = "https://api.runpod.io/graphql"

INTERVAL = 3 * 3600  # 3 hours


# ===== REST: GET PODS =====
def get_pods():
    resp = requests.get(REST_URL, headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"})
    resp.raise_for_status()
    return resp.json()


# ===== GRAPHQL: GET BALANCE =====
def get_balance():
    query = """
    {
      myself {
        balance
      }
    }
    """

    resp = requests.post(
        GRAPHQL_URL,
        json={"query": query},
        headers={"Authorization": f"Bearer {RUNPOD_API_KEY}"},
    )
    resp.raise_for_status()
    return float(resp.json()["data"]["myself"]["balance"])


# ===== COST CALC =====
def calculate_hourly_cost(pods):
    total = 0.0
    breakdown = []

    for pod in pods:
        if pod["desiredStatus"] != "RUNNING":
            continue

        cost = pod.get("adjustedCostPerHr") or float(pod["costPerHr"])
        total += cost
        breakdown.append((pod["name"], cost))

    return total, breakdown


def parse_emails():
    return [e.strip() for e in EMAIL_TO.split(",") if e.strip()]


# ===== EMAIL =====
def send_email(subject, body):
    recipients = parse_emails()

    if not recipients:
        print("[WARN] No recipients configured")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, recipients, msg.as_string())


# ===== TIME CALC =====
def hours_until_monday():
    now = datetime.now()
    days_ahead = (7 - now.weekday()) % 7  # Monday=0
    if days_ahead == 0:
        days_ahead = 7

    monday = now + timedelta(days=days_ahead)
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)

    return (monday - now).total_seconds() / 3600


# ===== CORE LOGIC =====
def check_billing():
    pods = get_pods()
    balance = get_balance()

    hourly_cost, breakdown = calculate_hourly_cost(pods)

    if hourly_cost == 0:
        print("No running pods.")
        return

    hours_left = balance / hourly_cost

    print(f"[INFO] Hourly cost: ${hourly_cost:.2f}")
    print(f"[INFO] Balance: ${balance:.2f}")
    print(f"[INFO] Hours left: {hours_left:.2f}")

    alert = False
    message = ""

    # Rule 1: < 24 hours
    if hours_left < 24:
        alert = True
        message += f"⚠️ Less than 24h remaining ({hours_left:.2f}h)\n"

    # Rule 2: Friday weekend check
    if datetime.now().weekday() == 4:  # Friday
        needed = hours_until_monday()
        if hours_left < needed:
            alert = True
            message += (
                f"⚠️ Not enough credit to last until Monday\n"
                f"Needed: {needed:.2f}h\n"
                f"Available: {hours_left:.2f}h\n"
            )

    if alert:
        message += "\nPod breakdown:\n"
        for name, cost in breakdown:
            message += f"- {name}: ${cost:.2f}/hr\n"

        send_email("RunPod Credit Alert", message)
        print("[ALERT] Email sent")
    else:
        print("[OK] No issues")


# ===== BACKGROUND WORKER =====
def run_forever():
    while True:
        start = time.time()

        try:
            check_billing()
        except Exception as e:
            print(f"[ERROR] {e}")

        elapsed = time.time() - start
        sleep_time = max(0, INTERVAL - elapsed)

        print(f"[SLEEP] Sleeping {sleep_time/3600:.2f} hours\n")
        time.sleep(sleep_time)


if __name__ == "__main__":
    run_forever()
