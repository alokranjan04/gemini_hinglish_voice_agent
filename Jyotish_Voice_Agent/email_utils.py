import smtplib
import os
import re
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

RASHI = ['Aries','Taurus','Gemini','Cancer','Leo','Virgo',
         'Libra','Scorpio','Sagittarius','Capricorn','Aquarius','Pisces']

_CITIES = {
    "patna":(25.5941,85.1376),"delhi":(28.6139,77.2090),"new delhi":(28.6139,77.2090),
    "mumbai":(19.0760,72.8777),"bombay":(19.0760,72.8777),
    "kolkata":(22.5726,88.3639),"calcutta":(22.5726,88.3639),
    "chennai":(13.0827,80.2707),"madras":(13.0827,80.2707),
    "bengaluru":(12.9716,77.5946),"bangalore":(12.9716,77.5946),
    "hyderabad":(17.3850,78.4867),"ahmedabad":(23.0225,72.5714),
    "pune":(18.5204,73.8567),"surat":(21.1702,72.8311),
    "jaipur":(26.9124,75.7873),"lucknow":(26.8467,80.9462),
    "kanpur":(26.4499,80.3319),"nagpur":(21.1458,79.0882),
    "indore":(22.7196,75.8577),"bhopal":(23.2599,77.4126),
    "agra":(27.1767,78.0081),"varanasi":(25.3176,82.9739),
    "kashi":(25.3176,82.9739),"banaras":(25.3176,82.9739),
    "meerut":(28.9845,77.7064),"rajkot":(22.3039,70.8022),
    "amritsar":(31.6340,74.8723),"jabalpur":(23.1815,79.9864),
    "prayagraj":(25.4358,81.8463),"allahabad":(25.4358,81.8463),
    "ranchi":(23.3441,85.3096),"guwahati":(26.1445,91.7362),
    "chandigarh":(30.7333,76.7794),"coimbatore":(11.0168,76.9558),
    "vijayawada":(16.5062,80.6480),"jodhpur":(26.2389,73.0243),
    "madurai":(9.9252,78.1198),"raipur":(21.2514,81.6296),
    "kochi":(9.9312,76.2673),"cochin":(9.9312,76.2673),
    "bhubaneswar":(20.2961,85.8245),"dehradun":(30.3165,78.0322),
    "panaji":(15.4989,73.8278),"goa":(15.2993,74.1240),
    "mysore":(12.2958,76.6394),"mysuru":(12.2958,76.6394),
    "thiruvananthapuram":(8.5241,76.9366),"trivandrum":(8.5241,76.9366),
    "jammu":(32.7266,74.8570),"srinagar":(34.0837,74.7973),
    "gorakhpur":(26.7606,83.3732),"bareilly":(28.3670,79.4304),
    "aligarh":(27.8974,78.0880),"mathura":(27.4924,77.6737),
    "haridwar":(29.9457,78.1642),"varanasi":(25.3176,82.9739),
    "muzaffarpur":(26.1209,85.3647),"gaya":(24.7914,84.9994),
    "bhagalpur":(25.2425,86.9842),"darbhanga":(26.1542,85.8918),
    "jamshedpur":(22.8046,86.2029),"dhanbad":(23.7957,86.4304),
    "visakhapatnam":(17.6868,83.2185),"vizag":(17.6868,83.2185),
    "siliguri":(26.7271,88.3952),"guntur":(16.3067,80.4365),
    "salem":(11.6643,78.1460),"trichy":(10.7905,78.7047),
    "puducherry":(11.9416,79.8083),"pondicherry":(11.9416,79.8083),
    "udaipur":(24.5854,73.7125),"ajmer":(26.4499,74.6399),
    "ludhiana":(30.9010,75.8573),"jalandhar":(31.3260,75.5762),
    "gwalior":(26.2183,78.1828),"nashik":(19.9975,73.7898),
    "mangalore":(12.9141,74.8560),"mangaluru":(12.9141,74.8560),
}

def _get_coords(place_str: str) -> tuple:
    key = place_str.lower().strip()
    for city, coords in _CITIES.items():
        if city in key or key.startswith(city):
            return coords
    print(f"[WARN] City not found: '{place_str}' — defaulting to New Delhi")
    return (28.6139, 77.2090)


def calculate_vedic_planets(dob_str: str, tob_str: str, pob_str: str):
    """
    Calculate accurate Vedic planet house positions using Swiss Ephemeris (Lahiri ayanamsha).
    Returns (planets_str, lagna_name) or (None, None) on failure.
    """
    try:
        import swisseph as swe

        # Parse date
        date_obj = None
        for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                date_obj = datetime.strptime(dob_str.strip(), fmt)
                break
            except ValueError:
                continue
        if not date_obj:
            m = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', dob_str)
            if m:
                try:
                    date_obj = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y")
                except ValueError:
                    pass
        if not date_obj:
            print(f"[ERROR] Cannot parse DOB: {dob_str}")
            return None, None

        # Parse time + AM/PM
        tob_upper = tob_str.strip().upper()
        is_pm = any(x in tob_upper for x in ("PM", "RAAT", "SHAM", "EVENING"))
        is_am = any(x in tob_upper for x in ("AM", "SUBAH", "SAVERE", "MORNING"))
        tm = re.search(r'(\d{1,2})[:\.](\d{2})', tob_upper)
        if tm:
            hour, minute = int(tm.group(1)), int(tm.group(2))
        else:
            tm = re.search(r'(\d{1,2})', tob_upper)
            hour, minute = (int(tm.group(1)), 0) if tm else (0, 0)
        if is_pm and hour != 12:
            hour += 12
        elif is_am and hour == 12:
            hour = 0

        # Convert IST → UTC
        dt_ist = date_obj.replace(hour=hour, minute=minute, second=0)
        dt_utc = dt_ist - timedelta(hours=5, minutes=30)

        jd = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                        dt_utc.hour + dt_utc.minute / 60.0)

        swe.set_sid_mode(swe.SIDM_LAHIRI)
        ayanamsha = swe.get_ayanamsa(jd)

        lat, lon = _get_coords(pob_str)
        _, ascmc = swe.houses(jd, lat, lon, b'P')
        asc_sidereal = (ascmc[0] - ayanamsha) % 360
        asc_sign = int(asc_sidereal / 30)

        PLANET_IDS = [
            ('Sun', swe.SUN), ('Moon', swe.MOON), ('Mars', swe.MARS),
            ('Mercury', swe.MERCURY), ('Jupiter', swe.JUPITER),
            ('Venus', swe.VENUS), ('Saturn', swe.SATURN),
        ]
        result = {}
        for pname, pid in PLANET_IDS:
            pos, _ = swe.calc_ut(jd, pid, swe.FLG_SIDEREAL)
            psign = int(pos[0] / 30)
            result[pname] = ((psign - asc_sign) % 12) + 1

        rahu_pos, _ = swe.calc_ut(jd, swe.TRUE_NODE, swe.FLG_SIDEREAL)
        rahu_sign = int(rahu_pos[0] / 30)
        ketu_sign = int(((rahu_pos[0] + 180) % 360) / 30)
        result['Rahu'] = ((rahu_sign - asc_sign) % 12) + 1
        result['Ketu'] = ((ketu_sign - asc_sign) % 12) + 1

        planets_str = ",".join(f"{p}={h}" for p, h in result.items())
        lagna = RASHI[asc_sign]
        print(f"[INFO] Vedic chart computed — Lagna: {lagna} | {planets_str}")
        return planets_str, lagna

    except ImportError:
        print("[WARN] pyswisseph not installed — planet positions will not be calculated")
        return None, None
    except Exception as e:
        print(f"[ERROR] Chart calculation failed: {e}")
        return None, None


def build_kundali_table(planets_str: str) -> str:
    """Build a South Indian 4x4 Kundali chart from a planet positions string."""
    planet_colors = {
        'Sun': '#f97316', 'Moon': '#93c5fd', 'Mars': '#ef4444',
        'Mercury': '#22c55e', 'Jupiter': '#fbbf24', 'Venus': '#e879f9',
        'Saturn': '#94a3b8', 'Rahu': '#a78bfa', 'Ketu': '#fb923c',
    }
    planet_names_hi = {
        'Sun': 'सूर्य', 'Moon': 'चंद्र', 'Mars': 'मंगल',
        'Mercury': 'बुध', 'Jupiter': 'गुरु', 'Venus': 'शुक्र',
        'Saturn': 'शनि', 'Rahu': 'राहु', 'Ketu': 'केतु',
    }

    house_contents: dict[int, list[str]] = {}
    for part in planets_str.split(','):
        part = part.strip()
        if '=' not in part:
            continue
        planet, house_str = part.split('=', 1)
        planet = planet.strip()
        try:
            house = int(house_str.strip())
        except ValueError:
            continue
        if 1 <= house <= 12 and planet in planet_colors:
            color = planet_colors[planet]
            name = planet_names_hi.get(planet, planet)
            house_contents.setdefault(house, []).append(
                f'<span style="color:{color};font-weight:bold;font-size:14px;display:block;line-height:1.4;">{name}</span>'
            )

    grid = [
        [12, 1,  2, 3],
        [11,  0,  0, 4],
        [10,  0,  0, 5],
        [ 9,  8,  7, 6],
    ]

    html = (
        '<table border="0" cellpadding="0" cellspacing="3" '
        'style="background:#080a0f;border:2px solid #d97706;margin:0 auto;font-family:Arial,sans-serif;">'
    )
    for r, row in enumerate(grid):
        html += '<tr>'
        for c, house_num in enumerate(row):
            if house_num == 0:
                if r == 1 and c == 1:
                    html += (
                        '<td colspan="2" rowspan="2" style="background:#0c0e14;text-align:center;'
                        'color:#d97706;font-size:13px;font-weight:bold;border:1px solid #d97706;">'
                        '<div style="font-size:22px;margin-bottom:6px;">✦</div>'
                        'जन्म<br>कुंडली</td>'
                    )
                continue
            planets_html = ''.join(house_contents.get(house_num, []))
            html += (
                f'<td style="width:100px;height:100px;background:#111318;border:2px solid #92400e;'
                f'text-align:center;vertical-align:middle;padding:6px;">'
                f'<div style="color:#ffffff;font-size:10px;margin-bottom:4px;opacity:0.5;">{house_num}</div>'
                f'<div style="line-height:1.5;">{planets_html}</div></td>'
            )
        html += '</tr>'
    html += '</table>'
    return html


def generate_detailed_analysis(name: str, dob: str, tob: str, pob: str,
                               planets_str: str = "", lagna: str = "") -> str:
    """Call Gemini REST API to generate a detailed 1500-word Kundali report in Hindi HTML."""
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[WARN] GEMINI_API_KEY not set — skipping Gemini report generation.")
        return ""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

    h2_style = "color:#fbbf24;font-size:17px;margin:28px 0 10px;padding:9px 0 9px 16px;border-left:4px solid #d97706;background:rgba(217,119,6,0.08);font-family:Arial,sans-serif;"
    p_style = "color:#ffffff;line-height:2.0;margin:8px 0;font-size:15px;font-family:'Noto Sans Devanagari',Arial,sans-serif;"

    chart_context = ""
    if planets_str and lagna:
        chart_context = f"""

CALCULATED CHART (Swiss Ephemeris, Lahiri ayanamsha — use these exact positions, do NOT recalculate):
Lagna (Ascendant): {lagna}
Planet house positions: {planets_str}
"""

    prompt = f"""You are an expert Vedic astrologer. Generate a comprehensive, academic Kundali report.

Birth details:
Name: {name}
Date of Birth: {dob}
Time of Birth: {tob}
Place of Birth: {pob}{chart_context}
Write a detailed 1500+ word Kundali report entirely in Hindi (Devanagari script) formatted as HTML.
Use EXACTLY this structure — each section must be thorough and specific to the birth data:

<h2 style="{h2_style}">१. व्यक्तित्व एवं स्वभाव</h2>
<p style="{p_style}">[200+ words: Lagna, Rashi, Nakshatra, Ascendant Lord's placement — deep personality analysis]</p>

<h2 style="{h2_style}">२. करियर एवं आर्थिक स्थिति</h2>
<p style="{p_style}">[250+ words: 10th house, 2nd house, 11th house, specific Raj Yogas — career prediction with timing]</p>

<h2 style="{h2_style}">३. पारिवारिक जीवन एवं विवाह</h2>
<p style="{p_style}">[200+ words: 7th house, 4th house, Venus and Jupiter placement — marriage timing and family analysis]</p>

<h2 style="{h2_style}">४. स्वास्थ्य एवं शारीरिक स्थिति</h2>
<p style="{p_style}">[150+ words: 6th house, 8th house, Moon sign health indicators and precautions]</p>

<h2 style="{h2_style}">५. विशेष राजयोग एवं दोष</h2>
<p style="{p_style}">[200+ words: All significant Yogas — Gajakesari, Bhadra, Neech Bhang etc. and Doshas — Mangal, Shani Sade Sati etc.]</p>

<h2 style="{h2_style}">६. दशा एवं भविष्यफल</h2>
<p style="{p_style}">[200+ words: Current Mahadasha and Antardasha lord, specific predictions for 1 year ahead, 3 years ahead, and 5 years ahead with approximate timing]</p>

<h2 style="{h2_style}">७. ज्योतिषीय उपाय</h2>
<p style="{p_style}">[150+ words: 6-7 specific remedies — include exact mantra text, gemstone with wearing instructions, day/time for rituals, and charitable acts]</p>

IMPORTANT: Be specific to this person's birth data. Do not give generic answers. Make each section academically detailed."""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096}
    }

    try:
        response = requests.post(url, json=payload, timeout=90)
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        print(f"[INFO] Gemini generated {len(text)} chars of Kundali analysis.")
        return text
    except Exception as e:
        print(f"[ERROR] Gemini report generation failed: {e}")
        return ""


def format_transcript_html(transcript: str) -> str:
    """Format raw transcript string into styled HTML with alternating bubbles."""
    if not transcript:
        return ""
    lines = transcript.split("<br>") if "<br>" in transcript else transcript.split("\n")
    html = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("User:"):
            text = line[5:].strip()
            html += (
                f'<div style="margin:6px 0;padding:8px 12px;background:#1a2235;'
                f'border-left:3px solid #fbbf24;border-radius:3px;">'
                f'<span style="color:#fbbf24;font-size:10px;font-weight:bold;letter-spacing:1px;">आप</span>'
                f'<br><span style="color:#e2e8f0;font-size:12px;line-height:1.6;">{text}</span></div>'
            )
        elif line.startswith("Jyotish Mitra:"):
            text = line[14:].strip()
            html += (
                f'<div style="margin:6px 0;padding:8px 12px;background:#111318;'
                f'border-left:3px solid #d97706;border-radius:3px;">'
                f'<span style="color:#d97706;font-size:10px;font-weight:bold;letter-spacing:1px;">ज्योतिष मित्र</span>'
                f'<br><span style="color:#d1d5db;font-size:12px;line-height:1.6;">{text}</span></div>'
            )
        else:
            html += f'<div style="margin:3px 0;color:#888;font-size:11px;">{line}</div>'
    return html


def send_astrology_report(to_email, name, dob, tob, pob, analysis_html, planets="", transcript=""):  # noqa: transcript kept for call-site compatibility
    """Send the full premium Kundali report — detailed analysis + chart + transcript."""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        print("[ERROR] Email credentials not found.")
        return False

    # Calculate accurate Vedic chart using Swiss Ephemeris
    print(f"[INFO] Calculating Vedic chart for {name} ({dob}, {tob}, {pob})...")
    calc_planets, lagna = calculate_vedic_planets(dob, tob, pob)
    if calc_planets:
        planets = calc_planets
    else:
        lagna = ""
        print("[WARN] Chart calculation failed — using Gemini-provided planet positions as fallback.")

    # Generate detailed Kundali via Gemini text API with accurate chart data
    print(f"[INFO] Generating Kundali analysis...")
    detailed_analysis = generate_detailed_analysis(name, dob, tob, pob, planets, lagna)
    if not detailed_analysis:
        print("[WARN] Gemini generation failed — using live session analysis_html as fallback.")
        detailed_analysis = analysis_html

    # Build Kundali chart
    kundali_chart_html = build_kundali_table(planets) if planets else (
        '<p style="color:#d97706;font-size:12px;text-align:center;">Chart data unavailable</p>'
    )

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600;700&family=Cinzel:wght@400;600;700&display=swap" rel="stylesheet">
</head>
<body style="background:#0a0c12;margin:0;padding:20px;font-family:Georgia,serif;">
  <div style="max-width:680px;margin:0 auto;">

    <!-- Header -->
    <div style="margin-bottom:30px;border:1px solid #92400e;border-radius:6px;overflow:hidden;background:#111318;">
      <div style="background:#1a1c24;padding:35px 20px;text-align:center;border-bottom:2px solid #d97706;">
        <div style="font-family:'Cinzel',Georgia,serif;font-size:26px;color:#fbbf24;letter-spacing:4px;font-weight:bold;margin-bottom:6px;">✦ ज्योतिष मित्र ✦</div>
        <div style="color:#fbbf24;opacity:0.6;font-size:11px;letter-spacing:3px;text-transform:uppercase;font-family:Arial,sans-serif;">वैदिक ज्योतिष — विस्तृत कुंडली रिपोर्ट</div>
      </div>

      <!-- Birth Details -->
      <div style="padding:25px;border-bottom:1px solid #2d303a;background:#12141c;">
        <h2 style="color:#fbbf24;font-size:13px;letter-spacing:1px;padding-left:12px;border-left:4px solid #d97706;margin:0 0 15px;font-family:Arial,sans-serif;">📋 जन्म विवरण</h2>
        <table style="width:100%;border-collapse:collapse;color:#e2e8f0;font-size:13px;font-family:Arial,sans-serif;">
          <tr style="border-bottom:1px solid #ffffff08;"><td style="color:#d97706;font-weight:bold;padding:8px 0;width:140px;">नाम</td><td style="padding:8px 0;">{name}</td></tr>
          <tr style="border-bottom:1px solid #ffffff08;"><td style="color:#d97706;font-weight:bold;padding:8px 0;">जन्म तिथि</td><td style="padding:8px 0;">{dob}</td></tr>
          <tr style="border-bottom:1px solid #ffffff08;"><td style="color:#d97706;font-weight:bold;padding:8px 0;">जन्म समय</td><td style="padding:8px 0;">{tob}</td></tr>
          <tr><td style="color:#d97706;font-weight:bold;padding:8px 0;">जन्म स्थान</td><td style="padding:8px 0;">{pob}</td></tr>
        </table>
      </div>

      <!-- Kundali Chart -->
      <div style="padding:20px 25px;border-bottom:1px solid #ffffff10;text-align:center;background:#0c0e14;">
        <h2 style="color:#fbbf24;font-size:13px;letter-spacing:2px;padding-left:10px;border-left:3px solid #d97706;margin:0 0 14px;text-align:left;font-family:Arial,sans-serif;">🌐 जन्म कुंडली चक्र</h2>
        <div style="display:inline-block;background:#080a0f;border:1px solid #d97706;padding:10px;border-radius:4px;">
          {kundali_chart_html}
        </div>
      </div>

      <!-- Detailed Analysis -->
      <div style="padding:25px;">
        <h2 style="color:#fbbf24;font-size:14px;letter-spacing:1px;padding-left:12px;border-left:4px solid #d97706;margin:0 0 18px;font-family:Arial,sans-serif;">🔮 विस्तृत कुंडली विश्लेषण</h2>
        <div style="font-family:'Noto Sans Devanagari',Arial,sans-serif;color:#ffffff;font-size:15px;line-height:2.0;">
          {detailed_analysis}
        </div>
      </div>
    </div>

    <div style="text-align:center;color:#ffffff20;font-size:10px;padding:16px;">
      Jyotish Mitra — Vedic Intelligence System v2.5
    </div>

  </div>
</body>
</html>"""

    msg = MIMEMultipart()
    msg['From'] = f"ज्योतिष मित्र 🔮 <{gmail_user}>"
    msg['To'] = to_email
    msg['Subject'] = f"✦ {name} Ji — Aapki Vistar Kundali Report | ज्योतिष मित्र"
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        print(f"[SUCCESS] Full Kundali report sent to {to_email}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send email: {e}")
        return False


def send_transcript_email(to_email: str, name: str, transcript_lines: list) -> bool:
    """Send the full conversation transcript as a separate email after the call ends."""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_password:
        print("[ERROR] Email credentials not found for transcript email.")
        return False

    if transcript_lines:
        formatted = format_transcript_html("<br>".join(transcript_lines))
    else:
        formatted = '<p style="color:#888;font-size:13px;font-style:italic;">Is session ki baatcheet capture nahi ho saki. Kundali report alag email mein bhej di gayi hai.</p>'

    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;600&family=Cinzel:wght@400;600&display=swap" rel="stylesheet">
</head>
<body style="background:#0a0c12;margin:0;padding:20px;font-family:Georgia,serif;">
  <div style="max-width:680px;margin:0 auto;">

    <div style="border:1px solid #92400e;border-radius:6px;overflow:hidden;background:#111318;">
      <div style="background:#1a1c24;padding:28px 20px;text-align:center;border-bottom:2px solid #d97706;">
        <div style="font-family:'Cinzel',Georgia,serif;font-size:22px;color:#fbbf24;letter-spacing:4px;font-weight:bold;margin-bottom:6px;">✦ ज्योतिष मित्र ✦</div>
        <div style="color:#fbbf24;opacity:0.6;font-size:11px;letter-spacing:3px;text-transform:uppercase;font-family:Arial,sans-serif;">वार्तालाप इतिहास — {name} Ji</div>
      </div>

      <div style="padding:24px;">
        <h2 style="color:#fbbf24;font-size:14px;letter-spacing:1px;padding-left:12px;border-left:4px solid #d97706;margin:0 0 20px;font-family:Arial,sans-serif;">💬 पूरी बातचीत</h2>
        {formatted}
      </div>
    </div>

    <div style="text-align:center;color:#ffffff20;font-size:10px;padding:16px;">
      Jyotish Mitra — Vedic Intelligence System v2.5
    </div>
  </div>
</body>
</html>"""

    msg = MIMEMultipart()
    msg['From'] = f"ज्योतिष मित्र 🔮 <{gmail_user}>"
    msg['To'] = to_email
    msg['Subject'] = f"💬 {name} Ji — Aapki Poori Baatcheet | ज्योतिष मित्र"
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        print(f"[SUCCESS] Transcript email sent to {to_email}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send transcript email: {e}")
        return False
