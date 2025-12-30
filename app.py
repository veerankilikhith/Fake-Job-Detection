from datetime import datetime
import os
import hashlib
import requests
from flask import Flask, render_template, request
from openai import OpenAI
from PIL import Image
import io

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB image limit

# ================= OPENAI =================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

client = OpenAI(api_key=OPENAI_API_KEY)

# ================= OCR.SPACE =================
OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_API_KEY")
if not OCR_SPACE_API_KEY:
    raise RuntimeError("OCR_SPACE_API_KEY not set")


def extract_text_from_image(image_bytes):
    try:
        # ---- Resize & compress image (OCR.space limit = 1MB) ----
        image = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB (required for JPEG)
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Resize if too large
        max_width = 1200
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height))

        # Save compressed image to memory
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=70)
        buffer.seek(0)

        # ---- Send to OCR.space ----
        response = requests.post(
            "https://api.ocr.space/parse/image",
            files={"file": ("image.jpg", buffer.getvalue())},
            data={
                "apikey": OCR_SPACE_API_KEY,
                "language": "eng",
                "isOverlayRequired": False
            },
            timeout=30
        )

        result = response.json()

        if result.get("IsErroredOnProcessing"):
            print("OCR Error:", result.get("ErrorMessage"))
            return ""

        parsed_results = result.get("ParsedResults")
        if parsed_results:
            return parsed_results[0].get("ParsedText", "").lower()

        return ""

    except Exception as e:
        print("OCR Exception:", e)
        return ""


# ================= CACHE =================
ai_cache = {}

def cache_key(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode()).hexdigest()


# ================= DATA =================
suspicious_phrases = [
    "registration fee", "application fee", "training fee", "deposit", "pay",
    "apply immediately", "limited seats", "urgent hiring",
    "no interview", "guaranteed placement",
    "work from home", "whatsapp", "telegram"
]

risk_tips = {
    "registration fee": "Genuine companies do not ask for fees.",
    "limited seats": "Fake jobs create urgency.",
    "whatsapp": "Hiring via WhatsApp is suspicious.",
    "telegram": "Telegram recruitment is risky.",
    "no interview": "Skipping interviews is a red flag."
}


# ================= AI EXPLANATION =================
def ai_explanation(text, risk, reasons):
    prompt = f"""
Risk Level: {risk}
Suspicious indicators: {', '.join(reasons) if reasons else 'None'}

Explain simply:
• Why this job is risky
• What students should check
• One safety tip
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=120
    )
    return response.choices[0].message.content.strip()


# ================= ROUTE =================
@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    # Greeting
    hour = datetime.now().hour
    if hour < 12:
        greeting = "🌅 Good Morning"
    elif hour < 17:
        greeting = "🌞 Good Afternoon"
    else:
        greeting = "🌙 Good Evening"

    if request.method == "POST":
        text = ""

        # ---- TEXT INPUT ----
        job_text = request.form.get("job_text", "").strip()
        if job_text:
            text = job_text.lower()

        # ---- IMAGE INPUT (ONLY if text empty) ----
        if not text and "job_image" in request.files:
            img_file = request.files["job_image"]
            if img_file and img_file.filename:
                image_bytes = img_file.read()
                text = extract_text_from_image(image_bytes)

        if not text:
            error = "No text detected"
            return render_template(
                "index.html",
                error=error,
                greeting=greeting
            )

        # ---- RISK ANALYSIS ----
        score = 0
        reasons = []

        for phrase in suspicious_phrases:
            if phrase in text:
                score += 1
                reasons.append(phrase)

        if score == 0:
            risk, meter, trust, cls = "LOW RISK", 20, 85, "low"
        elif score <= 2:
            risk, meter, trust, cls = "MEDIUM RISK", 60, 55, "medium"
        else:
            risk, meter, trust, cls = "HIGH RISK", 90, 20, "high"

        key = cache_key(text[:120])
        if key not in ai_cache:
            ai_cache[key] = ai_explanation(text[:120], risk, reasons)

        result = {
            "risk": risk,
            "trust": trust,
            "meter": meter,
            "class": cls,
            "reasons": reasons,
            "tips": risk_tips,
            "ai": ai_cache[key]
        }

    return render_template(
        "index.html",
        result=result,
        error=error,
        greeting=greeting
    )


# ================= RUN =================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

