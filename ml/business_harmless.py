"""Harmless business emails and lines for training (label 0).

LLMail-Inject's attacks are about finance/project emails, so a model can learn the topic words
("forecast", "send", "body", "confirmation", "forward") instead of the attack. These ordinary
messages use the same words harmlessly. Written fresh for training; ml/probe_business.py is a
separate test and nothing here is copied or paraphrased from it (generate() drops any line that
shares too many words with a probe line).
"""
import random
import re

PEOPLE = ["Priya", "Marcus", "Elena", "Tom", "Aisha", "Daniel", "Mei", "Carlos", "Hannah", "Olu", "Sven", "Rosa"]
TEAMS = ["finance", "procurement", "the regional sales team", "operations", "HR", "the audit committee",
         "legal", "the product group", "customer success", "the EMEA office", "facilities", "IT"]
DOCS = ["the variance analysis", "the vendor scorecard", "the headcount plan", "the capex request",
        "the churn dashboard", "the inventory reconciliation", "the pricing memo", "the board pack",
        "the cash-flow projection", "the renewal tracker", "the margin bridge", "the onboarding checklist"]
PERIODS = ["Q1", "Q2", "Q3", "Q4", "H1", "H2", "FY25", "FY26", "October", "the fiscal year"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "end of day", "next week", "the 20th"]

LINES = [
    "{p}, could you send the signed purchase order to {t} when you get a chance?",
    "I'll send the {per} revenue recap after the numbers are locked on {d}.",
    "Our {per} forecast was revised down slightly because two deals slipped.",
    "Please forward {doc} to {t}; they asked for it yesterday.",
    "The confirmation email from the travel portal should arrive within an hour.",
    "Booking confirmation for the offsite is attached; check-in starts at 3 PM.",
    "The email body has the agenda, and the slides are in the shared drive.",
    "I pasted the policy text into the body of the message so you don't need the attachment.",
    "Can you forward me the thread with the auditors? I wasn't copied on it.",
    "{t} needs {doc} before {d} to close the books.",
    "Reminder that expense reports for {per} are due {d}.",
    "{p} will present the {per} results at the all-hands.",
    "Gross margin held steady in {per} despite higher freight costs.",
    "We beat the {per} bookings target by about four percent.",
    "Send me your availability for a 30-minute review of {doc}.",
    "Please reply-all with any corrections to the minutes.",
    "Forwarding this from {p} in case it's useful for your planning.",
    "Got the confirmation code, thanks. The registration went through.",
    "I've attached {doc}; the summary is in the first tab.",
    "The {per} outlook assumes flat headcount and no new office leases.",
    "Could someone send the final invoice to the customer's accounts payable inbox?",
    "Please email {t} if the shipment is delayed again.",
    "The profit-and-loss statement for {per} is now posted in the finance folder.",
    "{p} asked whether we can send the contract redlines by {d}.",
    "Once legal approves, I'll forward the NDA to the vendor for signature.",
    "The body of the press release still needs a quote from the CEO.",
    "Order confirmation #48213 shows delivery between Tuesday and Thursday.",
    "Please send a calendar invite for the {per} planning kickoff.",
    "Our {per} projections are conservative; upside depends on the enterprise pipeline.",
    "Kindly forward the candidate's references to HR before the offer goes out.",
    "I'm sending the updated org chart to {t} this afternoon.",
    "The quarterly earnings summary is ready for review by {t}.",
    "Can you confirm the room booking for the {per} business review?",
    "Thanks, {p}. I've forwarded your note to {t}.",
    "The revenue forecast tab now pulls actuals automatically through {per}.",
    "Please send your slides to {p} by {d} so they can be merged into one deck.",
    "The email you sent to the client bounced; can you double-check the address?",
    "I'll email the shipping confirmation once the carrier picks up the pallets.",
    "Attached are {per} sales by region; APAC grew fastest.",
    "Please don't forward the draft outside the company until it's final.",
]

EMAIL = [
    ("Re: {doc}", "Hi {p},\n\nThanks for pulling this together. I made two small edits and will send it to {t} on {d}.\n\nBest,\n{p2}"),
    ("{per} close checklist", "Team,\n\nPlease send outstanding accruals to {t} by {d}. The {per} forecast review is the following morning.\n\nThanks,\n{p}"),
    ("Fwd: vendor invoice", "Forwarding the invoice below for approval. Once you confirm, I'll send it to accounts payable.\n\n{p}"),
    ("Booking confirmation", "Hi all,\n\nThe confirmation for the client dinner is attached. Please forward it to anyone joining late.\n\n{p}"),
    ("{per} results summary", "Hello,\n\nHeadline numbers for {per}: revenue up 6%, operating margin flat. Details are in the body of the attached memo.\n\nRegards,\n{p}"),
    ("Quick question on {doc}", "Hi {p},\n\nCould you send me the source data behind {doc}? {t} wants to check the totals.\n\nThanks!\n{p2}"),
    ("Please review: {doc}", "{p},\n\nWhen you have time, please review {doc} and send comments by {d}. No rush beyond that.\n\n{p2}"),
    ("Updated forecast", "Hi team,\n\nThe {per} forecast is updated with last week's actuals. Please forward questions to {p}.\n\nCheers,\n{p2}"),
    ("Re: shipment confirmation", "Thanks {p}. The carrier sent a confirmation this morning; I'll email tracking details to {t}.\n\n{p2}"),
    ("Meeting notes", "Hi everyone,\n\nNotes from today are in the body of this email. Action items: {p} to send {doc} to {t} by {d}.\n\n{p2}"),
]


def _fill(tpl: str, r: random.Random) -> str:
    p, p2 = r.sample(PEOPLE, 2)
    return tpl.format(p=p, p2=p2, t=r.choice(TEAMS), doc=r.choice(DOCS), per=r.choice(PERIODS), d=r.choice(DAYS))


def _words(t: str) -> set:
    return set(re.findall(r"[a-z0-9]+", t.lower()))


def generate(n: int = 300, seed: int = 11) -> list[str]:
    from ml.probe_business import LINES as PROBE
    probe = [_words(t) for t in PROBE]
    r, out, seen = random.Random(seed), [], set()
    tries = 0
    while len(out) < n and tries < n * 50:
        tries += 1
        if r.random() < 0.6:
            t = _fill(r.choice(LINES), r)
        else:
            subj, body = r.choice(EMAIL)
            t = f"{_fill(subj, r)}. {_fill(body, r)}"
        w = _words(t)
        if t in seen or any(len(w & q) / len(w | q) > 0.4 for q in probe):
            continue
        seen.add(t)
        out.append(t)
    return out
