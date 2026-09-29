#!/usr/bin/env python3
"""Generate a scholar-facing Twilio SMS setup Word guide."""

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "Twilio_SMS_Setup_Guide.docx"
NAVY = RGBColor(0x1A, 0x37, 0x5E)
MUTED = RGBColor(0x55, 0x55, 0x55)


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = NAVY


def add_bullet(doc: Document, text: str, bold_prefix: str = "") -> None:
    p = doc.add_paragraph(style="List Bullet")
    if bold_prefix:
        run = p.add_run(bold_prefix)
        run.bold = True
        p.add_run(text)
    else:
        p.add_run(text)


def add_link_line(doc: Document, label: str, url: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    p.add_run(f"{label}: ").bold = True
    run = p.add_run(url)
    run.font.color.rgb = RGBColor(0x0B, 0x57, 0xD0)
    run.underline = True


def add_code(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    run.font.size = Pt(10)


def table(doc: Document, headers: list[str], rows: list[list[str]]) -> None:
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, h in enumerate(headers):
        t.rows[0].cells[i].text = h
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = val


def build() -> Document:
    doc = Document()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = title.add_run("Twilio SMS Setup Guide\n")
    r.bold = True
    r.font.size = Pt(22)
    r.font.color.rgb = NAVY
    s = title.add_run("Daycare Violence Detection — Pi Alerts")
    s.font.size = Pt(14)
    s.font.color.rgb = MUTED

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta.add_run(f"For: Project scholar / intern\n").italic = True
    meta.add_run(f"Date: {date.today().strftime('%d %B %Y')}\n").italic = True
    meta.add_run("No Twilio experience required").italic = True

    add_heading(doc, "1. What you are setting up")
    doc.add_paragraph(
        "When the Raspberry Pi detects possible violence, it sends an SMS to staff phones. "
        "The web dashboard does not send SMS. Only the Pi uses Twilio."
    )
    doc.add_paragraph(
        "Target message (or as close as Twilio’s India rules allow):"
    )
    add_code(
        doc,
        "Possible violence / unsafe activity detected at 25 Sep 2026, 04:15 PM. Please check.",
    )

    add_heading(doc, "2. Create a Twilio account")
    add_bullet(doc, "Open the sign-up page and register with email + phone OTP.")
    add_link_line(doc, "Sign up", "https://www.twilio.com/try-twilio")
    add_link_line(doc, "Console (after login)", "https://console.twilio.com")
    doc.add_paragraph(
        "A new account starts as Trial. Trial can send SMS, but recipients must be verified, "
        "and India often requires an approved template (see Step 7)."
    )

    add_heading(doc, "3. Copy the three credentials")
    doc.add_paragraph(
        "On the console home page, find Account Info. You need three values for pi/.env:"
    )
    table(
        doc,
        ["What to copy", "Looks like", "pi/.env name"],
        [
            ["Account SID", "Starts with AC…", "TWILIO_ACCOUNT_SID"],
            ["Auth Token (click Show)", "Long secret string", "TWILIO_AUTH_TOKEN"],
            ["Twilio phone number", "+1737… (E.164)", "TWILIO_SMS_FROM"],
        ],
    )
    add_link_line(doc, "Console home (SID + token)", "https://console.twilio.com")
    add_link_line(
        doc,
        "API keys page (if token is hidden)",
        "https://console.twilio.com/us1/account/keys-credentials/api-keys",
    )
    doc.add_paragraph(
        "Never put the Auth Token in GitHub, Slack, or email screenshots. Only pi/.env on the device."
    )

    add_heading(doc, "4. Get a Twilio phone number (From)")
    add_bullet(doc, "Open incoming numbers. If one exists, copy it as +countrycode…")
    add_link_line(
        doc,
        "Manage numbers",
        "https://console.twilio.com/us1/develop/phone-numbers/manage/incoming",
    )
    add_bullet(doc, "If none: Buy a number → United States → enable SMS → Buy (trial credit is enough).")
    add_link_line(
        doc,
        "Buy a number",
        "https://console.twilio.com/us1/develop/phone-numbers/manage/search",
    )
    add_link_line(doc, "Twilio docs: phone numbers", "https://www.twilio.com/docs/phone-numbers")
    add_code(doc, "TWILIO_SMS_FROM=+17372508034")

    add_heading(doc, "5. Allow SMS to India (geo permissions)")
    doc.add_paragraph(
        "If India is blocked, Twilio returns error 20003 — Policy evaluation failed."
    )
    add_bullet(doc, "Open SMS Geo permissions.")
    add_bullet(doc, "Enable India and save.")
    add_link_line(
        doc,
        "Geo permissions",
        "https://console.twilio.com/us1/develop/sms/settings/geo-permissions",
    )
    add_link_line(
        doc,
        "Docs",
        "https://www.twilio.com/docs/sms/preventing-destination-country-blocked",
    )

    add_heading(doc, "6. Trial only: verify the staff phone (To)")
    doc.add_paragraph(
        "Trial accounts cannot text random numbers. Add each staff mobile and complete OTP."
    )
    add_link_line(
        doc,
        "Verified Caller IDs",
        "https://console.twilio.com/us1/develop/phone-numbers/manage/verified",
    )
    add_code(doc, "SMS_TO=+919354501373")
    doc.add_paragraph(
        "Several people: SMS_TO=+919354501373,+9198XXXXXXXX  (comma-separated, always +91)."
    )
    doc.add_paragraph(
        "After you upgrade to a paid Twilio account, most countries no longer need this list. "
        "India production SMS may still need DLT / templates — see Twilio India guidelines."
    )
    add_link_line(doc, "India SMS guidelines", "https://www.twilio.com/en-us/guidelines/in/sms")

    add_heading(doc, "7. Build the message (choose one path)")

    add_heading(doc, "Path A — Custom template (recommended wording)", level=2)
    doc.add_paragraph(
        "Use this so the SMS says: possible violence / unsafe activity detected at [date time]. Please check."
    )
    add_bullet(doc, "Open Content Template Builder.")
    add_link_line(
        doc,
        "Content Template Builder",
        "https://console.twilio.com/us1/develop/sms/content-template-builder",
    )
    add_link_line(
        doc,
        "Docs: create templates",
        "https://www.twilio.com/docs/content/create-templates-with-the-content-template-builder",
    )
    add_bullet(doc, "Create new → Text / SMS.")
    add_bullet(doc, "Friendly name: violence_alert")
    doc.add_paragraph("Body (use {{1}} for date and time — the Pi fills this automatically):")
    add_code(
        doc,
        "Possible violence / unsafe activity detected at {{1}}. Please check.",
    )
    doc.add_paragraph("Optional extra variables the Pi can send later:")
    table(
        doc,
        ["Variable", "Meaning in this project"],
        [
            ["{{1}}", "Date and time (e.g. 25 Sep 2026, 04:15:02 PM)"],
            ["{{2}}", "Confidence (e.g. 85.0%)"],
            ["{{3}}", "Camera IP"],
            ["{{4}}", "Label (violence)"],
        ],
    )
    add_bullet(doc, "Save the template. Copy the Content SID — it starts with HX…")
    doc.add_paragraph("Put this in pi/.env:")
    add_code(
        doc,
        "SMS_ENABLED=true\n"
        "TWILIO_SMS_MODE=content\n"
        "TWILIO_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
        "TWILIO_SMS_USE_TEMPLATE=false",
    )

    add_heading(doc, "Path B — Free-form text (no template builder)", level=2)
    doc.add_paragraph(
        "The Pi already builds a longer message in code (time, confidence, camera, “please verify”). "
        "This works when Twilio allows a normal SMS body (often paid / non-India-trial)."
    )
    add_code(
        doc,
        "SMS_ENABLED=true\n"
        "TWILIO_SMS_MODE=auto\n"
        "TWILIO_SMS_USE_TEMPLATE=false",
    )
    doc.add_paragraph("Leave TWILIO_CONTENT_SID empty.")

    add_heading(doc, "Path C — India trial name sms_internal_alerts", level=2)
    doc.add_paragraph(
        "Some India trial accounts only accept a pre-approved template name as the body. "
        "The SMS will NOT use your custom “please check” sentence."
    )
    add_code(
        doc,
        "TWILIO_SMS_MODE=template\n"
        "TWILIO_SMS_TEMPLATE=sms_internal_alerts\n"
        "TWILIO_SMS_USE_TEMPLATE=true",
    )

    add_heading(doc, "8. Complete pi/.env checklist")
    add_code(
        doc,
        "SMS_ENABLED=true\n"
        "TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
        "TWILIO_AUTH_TOKEN=your_auth_token\n"
        "TWILIO_SMS_FROM=+1xxxxxxxxxx\n"
        "SMS_TO=+91xxxxxxxxxx\n"
        "\n"
        "# Path A example:\n"
        "TWILIO_SMS_MODE=content\n"
        "TWILIO_CONTENT_SID=HXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    )

    add_heading(doc, "9. Test without a real alert")
    doc.add_paragraph("On the laptop or Pi, from the pi folder:")
    add_code(doc, "cd pi\npython3 violence_monitor.py --test-sms")
    doc.add_paragraph(
        "Success looks like:  [notifier] SMS sent → +91…  sid=SM…"
    )
    doc.add_paragraph("Restart violence_monitor.py after any .env change.")

    add_heading(doc, "10. Common errors")
    table(
        doc,
        ["Error", "Meaning", "What to do"],
        [
            [
                "20003 Policy evaluation failed",
                "Geo, trial, or auth policy",
                "Enable India in geo permissions; verify SMS_TO; re-copy Auth Token",
            ],
            [
                "21608 / unverified",
                "Trial cannot text that number",
                "Add the number under Verified Caller IDs",
            ],
            [
                "21211 Invalid To",
                "Bad phone format",
                "Use +91 then 10 digits, no spaces",
            ],
            [
                "Template / missing parameter",
                "Wrong SMS mode",
                "India trial: Path C. Custom sentence: Path A with HX SID",
            ],
        ],
    )
    add_link_line(doc, "Twilio error dictionary", "https://www.twilio.com/docs/api/errors")

    add_heading(doc, "11. How this fits the project")
    doc.add_paragraph(
        "Pi detects violence → photo to Cloudinary → row on the web dashboard → SMS via Twilio to SMS_TO."
    )
    doc.add_paragraph(
        "Each daycare Pi can share one Twilio account and use a different SMS_TO for that site’s staff. "
        "The web/ folder does not need Twilio keys."
    )

    add_heading(doc, "12. Link list (bookmark these)")
    table(
        doc,
        ["Step", "URL"],
        [
            ["Sign up", "https://www.twilio.com/try-twilio"],
            ["Console / credentials", "https://console.twilio.com"],
            ["Phone numbers", "https://console.twilio.com/us1/develop/phone-numbers/manage/incoming"],
            ["Buy a number", "https://console.twilio.com/us1/develop/phone-numbers/manage/search"],
            ["Geo permissions", "https://console.twilio.com/us1/develop/sms/settings/geo-permissions"],
            ["Verify trial phones", "https://console.twilio.com/us1/develop/phone-numbers/manage/verified"],
            ["Content templates", "https://console.twilio.com/us1/develop/sms/content-template-builder"],
            ["India SMS rules", "https://www.twilio.com/en-us/guidelines/in/sms"],
            ["Error codes", "https://www.twilio.com/docs/api/errors"],
        ],
    )

    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("\n— End of guide —")
    run.italic = True
    run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
    return doc


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    build().save(OUTPUT)
    print(f"Created: {OUTPUT}")


if __name__ == "__main__":
    main()
