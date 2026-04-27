"""
Iron Pixel – Smart School Hub  |  Poster Generator
Run: python static/_gen_poster.py
Output: static/poster_iron_pixel.png
"""
import math
import os
from PIL import Image, ImageDraw, ImageFont

# ── Canvas ─────────────────────────────────────────────────────────────────
W, H = 1800, 2800
img = Image.new("RGB", (W, H), (10, 14, 30))
draw = ImageDraw.Draw(img)

# ── Colour palette ──────────────────────────────────────────────────────────
DARK       = (10,  14,  30)
NAVY       = (16,  23,  45)
BLUE       = (59, 130, 246)
INDIGO     = (99, 102, 241)
VIOLET     = (139, 92, 246)
CYAN       = (6,  182, 212)
EMERALD    = (16, 185, 129)
AMBER      = (245, 158, 11)
ROSE       = (244,  63,  94)
WHITE      = (255, 255, 255)
LIGHT      = (226, 232, 240)
MID        = (148, 163, 184)
DIM        = (71,  85, 105)
CARD_BG    = (18,  24,  48)
CARD_BDR   = (30,  41,  70)

# ── Helpers ──────────────────────────────────────────────────────────────────
def lerp_color(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def gradient_rect(draw, x0, y0, x1, y1, c0, c1, vertical=True):
    if vertical:
        for y in range(y0, y1):
            t = (y - y0) / max(y1 - y0, 1)
            draw.line([(x0, y), (x1, y)], fill=lerp_color(c0, c1, t))
    else:
        for x in range(x0, x1):
            t = (x - x0) / max(x1 - x0, 1)
            draw.line([(x, y0), (x, y1)], fill=lerp_color(c0, c1, t))

def gradient_pill(draw, x0, y0, x1, y1, c0, c1, radius=10):
    """Horizontal gradient rounded rect."""
    for x in range(x0, x1):
        t = (x - x0) / max(x1 - x0, 1)
        col = lerp_color(c0, c1, t)
        draw.line([(x, y0), (x, y1)], fill=col)
    # re-draw corners transparent by stamping rounded mask
    mask = Image.new("L", (x1 - x0, y1 - y0), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([(0, 0), (x1 - x0 - 1, y1 - y0 - 1)], radius=radius, fill=255)
    base = img.crop((x0, y0, x1, y1))
    base.paste(Image.new("RGB", (x1 - x0, y1 - y0), DARK), mask=ImageChops_invert(mask))
    img.paste(base, (x0, y0))

from PIL import ImageChops
def ImageChops_invert(mask):
    inv = mask.point(lambda p: 255 - p)
    return inv

def rounded_rect(draw_obj, xy, radius, fill, outline=None, outline_width=2):
    draw_obj.rounded_rectangle(xy, radius=radius, fill=fill,
                                outline=outline, width=outline_width)

def glow_circle(xy, r, color, alpha=60):
    """Radial glow via concentric alpha circles."""
    cx, cy = xy
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    steps = 20
    for i in range(steps, 0, -1):
        a = int(alpha * (i / steps) ** 2)
        rr = int(r * i / steps)
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                   fill=(*color, a))
    base_rgba = img.convert("RGBA")
    combined = Image.alpha_composite(base_rgba, glow)
    img.paste(combined.convert("RGB"))

def get_font(size, bold=False):
    font_paths = [
        r"C:\Windows\Fonts\Calibri.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"C:\Windows\Fonts\Arial.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
    ]
    bold_paths = [
        r"C:\Windows\Fonts\Calibrib.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
        r"C:\Windows\Fonts\Arialbd.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
    ]
    paths = bold_paths if bold else font_paths
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def text_center(draw_obj, y, text, font, color):
    bbox = draw_obj.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw_obj.text(((W - tw) // 2, y), text, font=font, fill=color)
    return bbox[3] - bbox[1]

def text_left(draw_obj, x, y, text, font, color):
    draw_obj.text((x, y), text, font=font, fill=color)

# ── Background glows ────────────────────────────────────────────────────────
glow_circle((W - 200, 150), 380, INDIGO, alpha=40)
glow_circle((150, H - 300), 320, CYAN, alpha=30)
glow_circle((W // 2, H // 2), 280, VIOLET, alpha=15)

# ── Grid lines ───────────────────────────────────────────────────────────────
grid_col = (20, 28, 58)
for gx in range(0, W, 72):
    draw.line([(gx, 0), (gx, H)], fill=grid_col)
for gy in range(0, H, 72):
    draw.line([(0, gy), (W, gy)], fill=grid_col)

# ── Top gradient band ────────────────────────────────────────────────────────
gradient_rect(draw, 0, 0, W, 320, (12, 18, 50), DARK)

# ── BRAND BADGE ──────────────────────────────────────────────────────────────
badge_y = 54
rounded_rect(draw, [W//2 - 170, badge_y, W//2 + 170, badge_y + 38],
             radius=19, fill=(26, 30, 72), outline=(70, 75, 180))
# animated dot
draw.ellipse([W//2 - 148, badge_y + 13, W//2 - 132, badge_y + 29],
             fill=INDIGO)
f_badge = get_font(16, bold=True)
bb = draw.textbbox((0,0), "IRON PIXEL TECHNOLOGIES", font=f_badge)
tw = bb[2]-bb[0]
draw.text((W//2 - tw//2 + 10, badge_y + 11), "IRON PIXEL TECHNOLOGIES",
          font=f_badge, fill=(165, 180, 252))

# ── FLAGSHIP PRODUCT label ───────────────────────────────────────────────────
f_eye = get_font(18, bold=True)
text_center(draw, badge_y + 56, "F L A G S H I P   P R O D U C T   ·   2 0 2 6", f_eye, CYAN)

# ── MAIN TITLE ───────────────────────────────────────────────────────────────
f_title = get_font(118, bold=True)
f_title_sm = get_font(56, bold=True)
# Shadow
draw.text((W//2 - 395 + 4, 160 + 4), "Smart", font=f_title, fill=(0, 0, 0))
draw.text((W//2 - 395, 160), "Smart", font=f_title, fill=WHITE)
draw.text((W//2 - 75 + 4, 160 + 4), "School", font=f_title, fill=(0, 0, 0))
draw.text((W//2 - 75, 160), "School", font=f_title, fill=WHITE)
# "Hub" in gradient via band
hub_x = W//2 - 395
draw.text((hub_x + 4, 280 + 4), "Hub", font=f_title, fill=(0, 0, 0))
# Draw Hub in cyan/indigo approximate
draw.text((hub_x, 280), "Hub", font=f_title, fill=CYAN)

# ── Tagline ───────────────────────────────────────────────────────────────────
f_tag = get_font(26)
text_center(draw, 420, "The all-in-one intelligent platform powering every corner of a modern institution.", f_tag, MID)
text_center(draw, 454, "From enrollment to graduation · Classrooms to boardrooms", f_tag, DIM)

# ── Accent line ───────────────────────────────────────────────────────────────
gradient_rect(draw, W//2 - 80, 498, W//2 + 80, 502, INDIGO, CYAN, vertical=False)

# ── STATS STRIP ──────────────────────────────────────────────────────────────
stats = [
    ("7+",    "User Roles"),
    ("7",     "App Steps"),
    ("AI",    "GPT-4o"),
    ("∞",     "Schools"),
    ("100%",  "Cloud Native"),
]
sy = 530
sh = 108
sw_total = W - 140
sw_item = sw_total // len(stats)
rounded_rect(draw, [70, sy, W - 70, sy + sh], radius=18, fill=CARD_BG, outline=CARD_BDR)
f_sn = get_font(38, bold=True)
f_sl = get_font(14, bold=True)
for i, (num, label) in enumerate(stats):
    cx = 70 + i * sw_item + sw_item // 2
    if i > 0:
        draw.line([(70 + i * sw_item, sy + 20), (70 + i * sw_item, sy + sh - 20)], fill=CARD_BDR)
    # Number
    bb = draw.textbbox((0,0), num, font=f_sn)
    tw = bb[2]-bb[0]
    draw.text((cx - tw//2, sy + 14), num, font=f_sn, fill=CYAN)
    # Label
    bb2 = draw.textbbox((0,0), label, font=f_sl)
    tw2 = bb2[2]-bb2[0]
    draw.text((cx - tw2//2, sy + 66), label, font=f_sl, fill=DIM)

# ── SECTION: CORE FEATURES ────────────────────────────────────────────────────
f_sec = get_font(32, bold=True)
f_secsub = get_font(18)
y_sec = 690
text_center(draw, y_sec, "CORE PLATFORM FEATURES", f_sec, LIGHT)
text_center(draw, y_sec + 44, "Everything an institution needs, built in from day one.", f_secsub, DIM)
gradient_rect(draw, W//2 - 36, y_sec + 78, W//2 + 36, y_sec + 81, INDIGO, CYAN, vertical=False)

# ── FEATURE CARDS ─────────────────────────────────────────────────────────────
features = [
    ("🎓", "Multi-Step Online Applications",
     "7-stage guided student application journey from programme\nselection to document upload — fully paperless.",
     [" Programme & qualification selector",
      " Auto-generated application reference",
      " Draft save & resume at any step",
      " Confirmation email on submit"],
     BLUE, INDIGO),

    ("🤖", "AI-Powered Application Screening",
     "Every application scored & ranked instantly by GPT-4o-mini\nwith strengths, concerns & full audit trail.",
     [" Numeric score 0–100 + recommendation",
      " Strengths, concerns & missing items",
      " Rules-only fallback when AI is offline",
      " Full JSONB screening audit trail"],
     VIOLET, ROSE),

    ("🏫", "School & Curriculum Management",
     "Manage the entire institution hierarchy from school profile\ndown to departments, courses & modules.",
     [" Multi-school support (Pre/Primary/High/Tertiary)",
      " Curriculum builder per school",
      " School logo & branding per institution",
      " School-specific public website pages"],
     CYAN, BLUE),

    ("📚", "Virtual Classrooms & LMS",
     "Full-featured Learning Management System with classroom\ntools, materials, assignments & enrollment.",
     [" Upload learning materials & resources",
      " Assignments creation & submission portal",
      " Student enrollment & attendance tracking",
      " Module-level content management"],
     EMERALD, CYAN),

    ("📹", "Live Virtual Meetings & Calls",
     "Integrated real-time video call infrastructure with secure\ntoken-authenticated meeting rooms built in.",
     [" Live / Scheduled / Ended status indicators",
      " Media controls: mute, camera, screen share",
      " Password-protected links via signed tokens",
      " Global meetings management panel"],
     AMBER, ROSE),

    ("📊", "Results Portal & Analytics",
     "Transparent academic performance dashboards with GPA\ntracking, term results & per-subject charts.",
     [" Term-by-term result cards",
      " GPA bar: Good / OK / Poor thresholds",
      " Per-subject performance charts",
      " Downloadable academic reports"],
     ROSE, VIOLET),

    ("🔔", "Announcements & Notifications",
     "Targeted notification system reaching every role across\nthe platform with real-time updates.",
     [" School-wide & class-level announcements",
      " Notification bell with unread count",
      " Admin broadcast panel",
      " Role-filtered news feeds"],
     BLUE, CYAN),

    ("🔐", "Enterprise Security & Auth",
     "Bank-level authentication architecture protecting every\nuser, session and data exchange.",
     [" Google OAuth signup / completion flow",
      " Signed token URLs (itsdangerous)",
      " Forgot / reset password via email link",
      " Role-based access control on every route"],
     VIOLET, INDIGO),

    ("💬", "Contact & Communication Hub",
     "Centralised inbox for inbound enquiries plus broadcast\ncommunication tools for admins.",
     [" Public contact form with SMTP delivery",
      " Admin inbox with message management",
      " Email confirmations on key actions",
      " Message read / unread status tracking"],
     CYAN, EMERALD),
]

cols       = 3
card_w     = 510
card_h     = 295
gap_x      = 40
gap_y      = 28
start_x    = (W - (cols * card_w + (cols - 1) * gap_x)) // 2
start_y    = y_sec + 104

f_fi    = get_font(30)
f_ft    = get_font(22, bold=True)
f_fd    = get_font(15)
f_fb    = get_font(14)

for idx, (icon, title, desc, bullets, c0, c1) in enumerate(features):
    col = idx % cols
    row = idx // cols
    cx = start_x + col * (card_w + gap_x)
    cy = start_y + row * (card_h + gap_y)

    # Card background
    rounded_rect(draw, [cx, cy, cx + card_w, cy + card_h],
                 radius=16, fill=CARD_BG, outline=CARD_BDR)

    # Top accent bar gradient
    for bx in range(cx + 2, cx + card_w - 2):
        t = (bx - cx) / card_w
        col_bar = lerp_color(c0, c1, t)
        draw.point((bx, cy + 2), fill=col_bar)
        draw.point((bx, cy + 3), fill=col_bar)
        draw.point((bx, cy + 4), fill=col_bar)

    # Icon + Title
    draw.text((cx + 16, cy + 16), icon, font=f_fi, fill=WHITE)
    draw.text((cx + 58, cy + 18), title, font=f_ft, fill=LIGHT)

    # Description
    for li, dline in enumerate(desc.split("\n")):
        draw.text((cx + 16, cy + 60 + li * 20), dline, font=f_fd, fill=MID)

    # Divider
    draw.line([(cx + 16, cy + 110), (cx + card_w - 16, cy + 110)], fill=CARD_BDR)

    # Bullets
    for bi, b in enumerate(bullets):
        by = cy + 120 + bi * 40
        # bullet dot
        draw.ellipse([cx + 16, by + 7, cx + 22, by + 13], fill=INDIGO)
        draw.text((cx + 30, by), b, font=f_fb, fill=(203, 213, 225))

# ── AI SPOTLIGHT SECTION ─────────────────────────────────────────────────────
rows_feat = math.ceil(len(features) / cols)
ai_y = start_y + rows_feat * (card_h + gap_y) + 40

# Background panel
rounded_rect(draw, [70, ai_y, W - 70, ai_y + 320],
             radius=24, fill=(14, 20, 50), outline=(60, 70, 160))

# Glow behind it
glow_circle((W // 2, ai_y + 160), 260, INDIGO, alpha=25)

# AI Tag
rounded_rect(draw, [W//2 - 130, ai_y + 18, W//2 + 130, ai_y + 50],
             radius=16, fill=(26, 30, 80), outline=(80, 85, 200))
f_aitag = get_font(15, bold=True)
text_center(draw, ai_y + 24, "✦  AI  INTELLIGENCE  LAYER", f_aitag, (165, 180, 252))

f_aith = get_font(36, bold=True)
text_center(draw, ai_y + 64, "Your Students Get a Personal AI Tutor.", f_aith, WHITE)
text_center(draw, ai_y + 106, "Your Admins Get an AI Application Screener.", f_aith, WHITE)

f_aisub = get_font(19)
text_center(draw, ai_y + 158,
    "Smart School Hub integrates OpenAI GPT-4o-mini deeply — giving learners a 24/7 study", f_aisub, MID)
text_center(draw, ai_y + 182,
    "assistant with image understanding and admins an intelligent scoring engine.", f_aisub, MID)

ai_pills = [
    "📖 Study AI Chat",
    "🖼️ Image-Aware Q&A",
    "📝 Weekly AI Quizzes",
    "🎯 Application Scoring",
    "⚡ Daily Usage Limits",
    "🔌 Offline Fallback",
    "💡 Premium Instructor AI",
    "📊 Recommendation Engine",
]
pill_y = ai_y + 225
f_pill = get_font(15, bold=True)
pill_x = 100
for pi, pill in enumerate(ai_pills):
    bb = draw.textbbox((0,0), pill, font=f_pill)
    pw = bb[2] - bb[0] + 28
    if pill_x + pw > W - 100:
        pill_x = 100
        pill_y += 44
    rounded_rect(draw, [pill_x, pill_y, pill_x + pw, pill_y + 32],
                 radius=16, fill=(22, 28, 62), outline=(45, 52, 110))
    draw.text((pill_x + 14, pill_y + 7), pill, font=f_pill, fill=LIGHT)
    pill_x += pw + 14

# ── ROLES GRID ────────────────────────────────────────────────────────────────
roles_y = ai_y + 370
f_rsec = get_font(32, bold=True)
f_rsecsub = get_font(18)
text_center(draw, roles_y, "BUILT FOR EVERY ROLE", f_rsec, LIGHT)
text_center(draw, roles_y + 44, "Tailored dashboards and workflows for every person in the institution.", f_rsecsub, DIM)
gradient_rect(draw, W//2 - 36, roles_y + 78, W//2 + 36, roles_y + 81, INDIGO, CYAN, vertical=False)

roles = [
    ("👑", "Super Admin",   "Full platform control"),
    ("🏛️",  "School Admin",  "Institution manager"),
    ("🧑‍🏫", "Lecturer",      "Teaching & marking"),
    ("🎒", "Student",       "Learning portal"),
    ("👨‍👩‍👧", "Parent",        "Progress tracking"),
    ("🧑‍💼", "Staff",          "Operations & admin"),
]
ry = roles_y + 100
rcard_w = 240
rcard_h = 110
rgap = 26
rx_start = (W - (len(roles) * rcard_w + (len(roles) - 1) * rgap)) // 2
f_ri = get_font(28)
f_rn = get_font(19, bold=True)
f_rd = get_font(14)

for i, (icon, name, desc) in enumerate(roles):
    rx = rx_start + i * (rcard_w + rgap)
    rounded_rect(draw, [rx, ry, rx + rcard_w, ry + rcard_h],
                 radius=14, fill=CARD_BG, outline=CARD_BDR)
    draw.text((rx + 16, ry + 14), icon, font=f_ri, fill=WHITE)
    draw.text((rx + 56, ry + 18), name, font=f_rn, fill=LIGHT)
    draw.text((rx + 56, ry + 46), desc, font=f_rd, fill=DIM)

# ── TECH STACK ───────────────────────────────────────────────────────────────
tech_y = ry + rcard_h + 56
text_center(draw, tech_y, "POWERED BY MODERN TECHNOLOGY", f_rsec, LIGHT)
text_center(draw, tech_y + 44, "Built on a proven, scalable, cloud-native stack.", f_rsecsub, DIM)
gradient_rect(draw, W//2 - 36, tech_y + 78, W//2 + 36, tech_y + 81, INDIGO, CYAN, vertical=False)

techs = [
    "🐍 Python / Flask",
    "🗄️ Supabase (PostgreSQL)",
    "🤖 OpenAI GPT-4o-mini",
    "☁️ Cloud Native",
    "🔒 Werkzeug Security",
    "📦 SQLAlchemy ORM",
    "🔑 itsdangerous Tokens",
    "🌐 SMTP Email",
    "🎨 Jinja2 Templates",
    "🚦 Flask-Migrate",
]
ty = tech_y + 98
tx = 80
f_tech = get_font(17, bold=True)
for tech in techs:
    bb = draw.textbbox((0,0), tech, font=f_tech)
    tw2 = bb[2]-bb[0] + 32
    if tx + tw2 > W - 80:
        tx = 80
        ty += 50
    rounded_rect(draw, [tx, ty, tx + tw2, ty + 38],
                 radius=10, fill=(16, 22, 46), outline=(30, 40, 80))
    draw.text((tx + 16, ty + 9), tech, font=f_tech, fill=(148, 163, 184))
    tx += tw2 + 16

# ── FOOTER ───────────────────────────────────────────────────────────────────
footer_y = ty + 68
draw.line([(80, footer_y), (W - 80, footer_y)], fill=CARD_BDR)

f_fl = get_font(52, bold=True)
f_ft2 = get_font(16, bold=True)
f_fc  = get_font(14)
text_center(draw, footer_y + 20, "Iron Pixel", f_fl, INDIGO)
text_center(draw, footer_y + 84, "C R A F T I N G   D I G I T A L   E X C E L L E N C E   ·   E S T .  2 0 2 4", f_ft2, DIM)
text_center(draw, footer_y + 114, "© 2026 Iron Pixel Technologies  ·  Smart School Hub  ·  All Rights Reserved", f_fc, (45, 55, 75))

# ── SAVE ─────────────────────────────────────────────────────────────────────
out_path = os.path.join(os.path.dirname(__file__), "poster_iron_pixel.png")
img.save(out_path, "PNG", quality=98)
print(f"Poster saved → {out_path}")
