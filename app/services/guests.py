"""Guests on the boat: a QR code that opens a page where they leave their email (to get the report) and
share their photos. The report is emailed to them when the guide sends it, and straight away to anyone
who signs up after that. Emails carry the company's review links (Google, TripAdvisor).

Guest-facing text is in the report's language (en, es, de, fr), like the report itself."""
from __future__ import annotations

import html
import io
import logging
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Guest, Organization, Trip, User
from . import mail

log = logging.getLogger("tripreports.guests")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
MAX_GUESTS = 300
MAX_GUEST_PHOTOS = 200

G = {
    "en": {
        "title": "Get your trip report", "lead": "Leave your email and {org} will send you the report of today's outing: what we saw, the species list and photos.",
        "email": "Your email", "name": "Your name (optional)", "news": "I'd like to hear from {org} about future trips",
        "consent": "Your email is only used by {org} to send you this report{news}.", "news_short": " and, if you tick the box, news from them",
        "send": "Send me the report", "done": "Done! We'll email you the report as soon as it's ready.", "done_sent": "Done! The report is on its way to your inbox.",
        "photos": "Share your photos", "photos_lead": "Got a great shot? Upload it and, once the guide approves it, it will appear in the report with your name.",
        "photos_btn": "Upload photos", "photos_ok": "Thank you! {n} photo(s) received. They'll appear in the report once the guide approves them.",
        "photos_bad": "Those photos couldn't be read. Try JPG or PNG files.", "photos_rights": "By uploading you confirm the photos are yours and let {org} show them in this report.",
        "author": "Name for the photo credit (optional)", "bad_email": "That email doesn't look right. Check it and try again.",
        "closed": "This page is closed", "closed_lead": "The guide has closed sign-ups for this outing.",
        "none": "No outing open right now", "none_lead": "Ask your guide to show you the QR code of today's outing.",
        "slow": "Too many attempts. Wait a few minutes and try again.", "privacy": "Privacy",
        "subject": "Your trip report: {title}", "hello": "Hello{name},", "mail_lead": "Thank you for coming with {org}. Here's the report of your outing, with everything we saw:",
        "open": "Open the report", "review_ask": "Did you enjoy it? A short review helps us a lot:", "google": "Review on Google", "tripadvisor": "Review on TripAdvisor",
        "why": "You're receiving this because you left your email on the QR page of this outing.", "outing": "today's outing",
    },
    "es": {
        "title": "Recibe el informe de tu salida", "lead": "Deja tu email y {org} te enviará el informe de la salida de hoy: lo que vimos, la lista de especies y las fotos.",
        "email": "Tu email", "name": "Tu nombre (opcional)", "news": "Quiero recibir novedades de {org} sobre próximas salidas",
        "consent": "{org} solo usará tu email para enviarte este informe{news}.", "news_short": " y, si marcas la casilla, sus novedades",
        "send": "Enviadme el informe", "done": "¡Listo! Te enviaremos el informe por email en cuanto esté listo.", "done_sent": "¡Listo! El informe va de camino a tu correo.",
        "photos": "Comparte tus fotos", "photos_lead": "¿Tienes una buena foto? Súbela y, cuando el guía la apruebe, aparecerá en el informe con tu nombre.",
        "photos_btn": "Subir fotos", "photos_ok": "¡Gracias! Hemos recibido {n} foto(s). Aparecerán en el informe cuando el guía las apruebe.",
        "photos_bad": "No hemos podido leer esas fotos. Prueba con archivos JPG o PNG.", "photos_rights": "Al subirlas confirmas que las fotos son tuyas y permites que {org} las muestre en este informe.",
        "author": "Nombre para el crédito de la foto (opcional)", "bad_email": "Ese email no parece correcto. Revísalo y vuelve a intentarlo.",
        "closed": "Esta página está cerrada", "closed_lead": "El guía ha cerrado la inscripción para esta salida.",
        "none": "Ahora mismo no hay ninguna salida abierta", "none_lead": "Pide a tu guía que te enseñe el código QR de la salida de hoy.",
        "slow": "Demasiados intentos. Espera unos minutos y vuelve a probar.", "privacy": "Privacidad",
        "subject": "El informe de tu salida: {title}", "hello": "Hola{name}:", "mail_lead": "Gracias por venir con {org}. Aquí tienes el informe de la salida, con todo lo que vimos:",
        "open": "Ver el informe", "review_ask": "¿Te gustó? Una reseña corta nos ayuda muchísimo:", "google": "Reseña en Google", "tripadvisor": "Reseña en TripAdvisor",
        "why": "Recibes este email porque dejaste tu dirección en la página QR de esta salida.", "outing": "la salida de hoy",
    },
    "de": {
        "title": "Holen Sie sich Ihren Tourbericht", "lead": "Hinterlassen Sie Ihre E-Mail und {org} schickt Ihnen den Bericht der heutigen Tour: was wir gesehen haben, die Artenliste und Fotos.",
        "email": "Ihre E-Mail", "name": "Ihr Name (optional)", "news": "Ich möchte von {org} über künftige Touren hören",
        "consent": "{org} nutzt Ihre E-Mail nur, um Ihnen diesen Bericht zu senden{news}.", "news_short": " und, wenn Sie das Kästchen ankreuzen, Neuigkeiten",
        "send": "Bericht zusenden", "done": "Fertig! Wir mailen Ihnen den Bericht, sobald er fertig ist.", "done_sent": "Fertig! Der Bericht ist unterwegs in Ihr Postfach.",
        "photos": "Teilen Sie Ihre Fotos", "photos_lead": "Ein tolles Foto gemacht? Laden Sie es hoch. Sobald der Guide es freigibt, erscheint es mit Ihrem Namen im Bericht.",
        "photos_btn": "Fotos hochladen", "photos_ok": "Danke! {n} Foto(s) erhalten. Sie erscheinen im Bericht, sobald der Guide sie freigibt.",
        "photos_bad": "Diese Fotos konnten nicht gelesen werden. Versuchen Sie JPG- oder PNG-Dateien.", "photos_rights": "Mit dem Hochladen bestätigen Sie, dass die Fotos Ihnen gehören, und erlauben {org}, sie in diesem Bericht zu zeigen.",
        "author": "Name für den Bildnachweis (optional)", "bad_email": "Diese E-Mail sieht nicht richtig aus. Bitte prüfen.",
        "closed": "Diese Seite ist geschlossen", "closed_lead": "Der Guide hat die Anmeldung für diese Tour geschlossen.",
        "none": "Gerade ist keine Tour geöffnet", "none_lead": "Bitten Sie Ihren Guide um den QR-Code der heutigen Tour.",
        "slow": "Zu viele Versuche. Bitte warten Sie ein paar Minuten.", "privacy": "Datenschutz",
        "subject": "Ihr Tourbericht: {title}", "hello": "Hallo{name},", "mail_lead": "Danke, dass Sie mit {org} unterwegs waren. Hier ist der Bericht Ihrer Tour mit allem, was wir gesehen haben:",
        "open": "Bericht öffnen", "review_ask": "Hat es Ihnen gefallen? Eine kurze Bewertung hilft uns sehr:", "google": "Bewertung auf Google", "tripadvisor": "Bewertung auf TripAdvisor",
        "why": "Sie erhalten diese E-Mail, weil Sie Ihre Adresse auf der QR-Seite dieser Tour hinterlassen haben.", "outing": "die heutige Tour",
    },
    "fr": {
        "title": "Recevez le rapport de votre sortie", "lead": "Laissez votre e-mail et {org} vous enverra le rapport de la sortie du jour : ce que nous avons vu, la liste des espèces et les photos.",
        "email": "Votre e-mail", "name": "Votre nom (facultatif)", "news": "Je souhaite recevoir des nouvelles de {org} sur les prochaines sorties",
        "consent": "{org} utilise votre e-mail uniquement pour vous envoyer ce rapport{news}.", "news_short": " et, si vous cochez la case, ses nouvelles",
        "send": "Envoyez-moi le rapport", "done": "C'est fait ! Nous vous enverrons le rapport par e-mail dès qu'il sera prêt.", "done_sent": "C'est fait ! Le rapport arrive dans votre boîte mail.",
        "photos": "Partagez vos photos", "photos_lead": "Une belle photo ? Envoyez-la : une fois validée par le guide, elle apparaîtra dans le rapport avec votre nom.",
        "photos_btn": "Envoyer des photos", "photos_ok": "Merci ! {n} photo(s) reçue(s). Elles apparaîtront dans le rapport une fois validées par le guide.",
        "photos_bad": "Ces photos n'ont pas pu être lues. Essayez des fichiers JPG ou PNG.", "photos_rights": "En les envoyant, vous confirmez que les photos sont les vôtres et autorisez {org} à les montrer dans ce rapport.",
        "author": "Nom pour le crédit photo (facultatif)", "bad_email": "Cet e-mail ne semble pas correct. Vérifiez-le.",
        "closed": "Cette page est fermée", "closed_lead": "Le guide a fermé les inscriptions pour cette sortie.",
        "none": "Aucune sortie ouverte pour le moment", "none_lead": "Demandez à votre guide le code QR de la sortie du jour.",
        "slow": "Trop de tentatives. Attendez quelques minutes.", "privacy": "Confidentialité",
        "subject": "Le rapport de votre sortie : {title}", "hello": "Bonjour{name},", "mail_lead": "Merci d'être venu avec {org}. Voici le rapport de votre sortie, avec tout ce que nous avons vu :",
        "open": "Voir le rapport", "review_ask": "Vous avez aimé ? Un petit avis nous aide beaucoup :", "google": "Avis sur Google", "tripadvisor": "Avis sur TripAdvisor",
        "why": "Vous recevez cet e-mail parce que vous avez laissé votre adresse sur la page QR de cette sortie.", "outing": "la sortie du jour",
    },
}


def labels(lang: str, org_name: str) -> dict:
    t = G.get(lang) or G["en"]
    return {k: v.replace("{org}", org_name or "") for k, v in t.items()}


def clean_email(s: str) -> str | None:
    s = (s or "").strip().lower()
    return s if len(s) <= 254 and EMAIL.match(s) else None


def clean_url(s: str) -> str:
    s = (s or "").strip()
    if re.match(r"^[a-z][a-z0-9+.-]*:(?!//)", s, re.I) and not re.match(r"^https?:", s, re.I):
        return ""  # javascript:, mailto: and the like
    if s and not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    return s[:400] if re.match(r"^https?://[^\s/$.?#][^\s]*$", s) else ""


def ensure_token(db: Session, obj) -> str:
    if not obj.guest_token:
        obj.guest_token = secrets.token_urlsafe(9)  # 12 characters: short QR, still unguessable
        db.commit()
    return obj.guest_token


def trip_url(db: Session, trip: Trip) -> str:
    return f"{settings.app_url}/g/{ensure_token(db, trip)}"


def card_url(db: Session, org: Organization) -> str:
    return f"{settings.app_url}/q/{ensure_token(db, org)}"


def qr_svg(url: str, dark: str = "#1C2420") -> str:
    import segno
    out = io.BytesIO()
    segno.make(url, error="m").save(out, kind="svg", scale=1, border=2, xmldecl=False, svgns=True,
                                   dark=dark, light="#ffffff", omitsize=True)
    return out.getvalue().decode()


def current_trip(db: Session, org: Organization) -> Trip | None:
    """For the permanent boat card: today's outing (or yesterday's, for late evening scans)."""
    today = date.today()
    trips = db.scalars(select(Trip).where(Trip.org_id == org.id, Trip.is_demo.is_(False), Trip.guests_closed.is_(False),
                                          Trip.start_date >= today - timedelta(days=1), Trip.start_date <= today)
                       .order_by(Trip.start_date.desc(), Trip.created_at.desc())).all()
    return trips[0] if trips else None


# ---------------------------------------------------------------- the report email
def _owner(db: Session, org: Organization) -> User | None:
    return db.scalar(select(User).where(User.org_id == org.id, User.role == "owner", User.is_active.is_(True)))


def email_for(trip: Trip, org: Organization, guest: Guest) -> tuple[str, str, str]:
    """(subject, text, html) in the guest's language."""
    t = labels(guest.lang or trip.report_lang, org.name or settings.name_for(trip.report_lang))
    url = f"{settings.app_url}/r/{trip.share_token}"
    title = trip.title or t["outing"]
    name = f" {guest.name.split()[0]}" if guest.name.strip() else ""
    reviews = [(t["google"], org.review_google), (t["tripadvisor"], org.review_tripadvisor)]
    reviews = [(lbl, u) for lbl, u in reviews if u]
    text = [t["hello"].replace("{name}", name), "", t["mail_lead"], "", url, ""]
    if reviews:
        text += [t["review_ask"]] + [f"{lbl}: {u}" for lbl, u in reviews] + [""]
    if org.signoff:
        text += [org.signoff, ""]
    text += ["--", t["why"]]
    acc = org.accent if re.match(r"^#[0-9a-fA-F]{6}$", org.accent or "") else "#2E6A5C"
    e = html.escape
    btn = ('<a href="{u}" style="display:inline-block;background:{c};color:#fff;text-decoration:none;font-weight:600;'
           'padding:12px 20px;border-radius:10px;margin:4px 6px 4px 0">{l}</a>')
    rbtn = ('<a href="{u}" style="display:inline-block;border:1px solid {c};color:{c};text-decoration:none;font-weight:600;'
            'padding:9px 16px;border-radius:10px;margin:4px 6px 4px 0">{l}</a>')
    body = [
        f'<div style="font-family:Helvetica,Arial,sans-serif;color:#1C2420;max-width:560px;margin:0 auto;padding:24px 18px;line-height:1.55">',
        f'<div style="height:5px;background:{acc};border-radius:3px;margin-bottom:22px"></div>',
        f'<p style="font-weight:700;color:{acc};margin:0 0 18px">{e(org.name or "")}</p>' if org.name else "",
        f'<h1 style="font-size:22px;margin:0 0 14px">{e(title)}</h1>',
        f'<p>{e(t["hello"].replace("{name}", name))}</p><p>{e(t["mail_lead"])}</p>',
        f'<p style="margin:22px 0">{btn.format(u=e(url), c=acc, l=e(t["open"]))}</p>',
    ]
    if reviews:
        body.append(f'<p style="margin:26px 0 6px">{e(t["review_ask"])}</p><p>' +
                    "".join(rbtn.format(u=e(u), c=acc, l=e(lbl)) for lbl, u in reviews) + "</p>")
    if org.signoff:
        body.append(f'<p style="margin-top:26px;white-space:pre-line">{e(org.signoff)}</p>')
    body.append(f'<p style="margin-top:32px;font-size:12px;color:#737E77">{e(t["why"])}</p></div>')
    subject = t["subject"].replace("{title}", title)
    return subject, "\n".join(text), "".join(body)


def send_to(db: Session, trip: Trip, guests: list[Guest]) -> int:
    """Email the report to these guests (needs the trip's share link). Returns how many went out."""
    org = db.get(Organization, trip.org_id)
    if not trip.share_token or not org:
        return 0
    owner = _owner(db, org)
    sent = 0
    for g in guests:
        if g.sent_at:
            continue
        subject, text, body = email_for(trip, org, g)
        ok = mail.send(g.email, subject, text, html=body, sender_name=org.name or None,
                       reply_to=owner.email if owner else None)
        if ok:
            g.sent_at = datetime.now(timezone.utc)
            sent += 1
        db.commit()
    return sent


def send_pending(trip_id: str) -> None:
    """Background job: send the report to everyone on the list who hasn't had it."""
    from ..db import SessionLocal
    with SessionLocal() as db:
        trip = db.get(Trip, trip_id)
        if trip:
            n = send_to(db, trip, [g for g in trip.guest_list if not g.sent_at])
            log.info("Report %s emailed to %d guest(s)", trip_id, n)
