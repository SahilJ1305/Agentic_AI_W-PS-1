"""
app/core/relay.py — person-to-person messages that pass through the bot.

People talk to each other through Cadence ("tell Priya the API key is missing", "@Rohan can you
share the creds?", "Rohan ko bolo ki PR merge kar de", "unblock Omar"). Before this, every message
was read as a status update on the sender's own tasks, so anything addressed to someone else was
dropped with "I only keep track of project tasks".

parse_directed() recognises the unambiguous shapes with plain rules, so relaying works instantly and
even when the model is down. Everything fuzzier is left to the Coordinator Agent, which now returns
`messages` alongside `updates` and is told who is on the team.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.agents.schemas import Interpretation, RelayOut

_LEAD_WORDS = {"lead", "leader", "teamlead", "team lead", "boss"}
_EVERYONE_WORDS = {"everyone", "everybody", "all", "team", "the team", "all of you", "guys"}

_VERBS = r"(?:tell|ask|ping|inform|notify|message|msg|dm|remind|update|let|warn|cc)"
_THAT = r"(?:\s*(?:that|to|:|,|-|–|—|know(?:\s+that)?))*"
_WHO = r"(?:(?:the|our)\s+)?@?\w[\w.'-]*(?:(?<=team)\s+lead)?"      # "Rohan", "@rohan", "the lead", "team lead"

# "tell Rohan that ...", "ask the lead to ...", "let Priya know ..."
_VERB_FIRST = re.compile(
    rf"^\s*(?:please\s+|pls\s+|plz\s+|can you\s+|could you\s+|just\s+)*{_VERBS}\s+(?P<who>{_WHO}(?:\s*(?:,|and|&)\s*{_WHO})*)"
    rf"{_THAT}\s+(?P<body>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)
# "Rohan ko bolo ki ...", "lead ko batao ...", "@priya ko bata do ..."
_HINGLISH = re.compile(
    r"^\s*(?P<who>@?\w+)\s+ko\s+(?:bol(?:o|\s*do)?|bata(?:o|\s*do)?|keh(?:\s*do)?|kaho|message\s+kar(?:o|\s*do)?)"
    r"\s*(?:ki|ke)?\s*[,:-]?\s*(?P<body>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)
# "@Rohan can you ...", "Rohan, can you ...", "hey Priya: ...", "to lead: ..."
_ADDRESSED = re.compile(
    r"^\s*(?:(?:hey|hi|hello|yo|oye|hello there)\s+|to\s+|for\s+)?(?P<who>@?\w[\w.'-]*)\s*(?:[:,\-–—]\s*|\s+(?=\S))(?P<body>\S.*)$",
    re.IGNORECASE | re.DOTALL,
)
_MENTION = re.compile(r"@(\w+)")

_RESOLVE_WORD = r"(?:unblock(?:ed)?|resolved?|cleared?|fixed|sorted)"
_WHO_OR_KEY = r"(?:T\d+|@?\w[\w.-]*)"
_RESOLVE_FIRST = re.compile(
    rf"^\s*(?:ok(?:ay)?[ ,]+|done[ ,]+|i\s+have\s+|i've\s+|i\s+)?{_RESOLVE_WORD}\s+(?:the\s+)?(?:blocker\s+(?:on|for)\s+)?"
    rf"(?P<who>{_WHO_OR_KEY})(?:'s)?(?:\s+blocker)?(?:\s+(?:task|issue))?[\s,:.\-–—]*(?P<note>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RESOLVE_AFTER = re.compile(
    rf"^\s*(?P<who>{_WHO_OR_KEY})(?:'s)?\s+(?:blocker\s+|issue\s+)?(?:is\s+|has\s+been\s+|got\s+)?{_RESOLVE_WORD}\b"
    r"[\s,:.\-–—]*(?P<note>.*)$",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class Person:
    id: int
    name: str
    role: str
    usernames: frozenset[str]  # Telegram usernames we know for them (the one the lead saved, the one they joined with)


def _people(rows: list[dict]) -> list[Person]:
    return [
        Person(
            r["id"], r["name"], r.get("role") or "member",
            frozenset(u.lstrip("@").lower() for u in (r.get("telegram_username"), r.get("joined_username")) if u),
        )
        for r in rows
    ]


def _match_one(token: str, people: list[Person]) -> Person | list[Person] | None:
    """A name, @username or 'lead' → the person. Several matching first names → None (ambiguous)."""
    word = re.sub(r"^@", "", token.strip()).strip(" .,'").lower()
    word = re.sub(r"^(?:the|our)\s+", "", word)
    if not word:
        return None
    if word in _LEAD_WORDS:
        return next((p for p in people if p.role == "lead"), None)
    exact = [p for p in people if p.name.lower() == word or word in p.usernames]
    if len(exact) == 1:
        return exact[0]
    first = [p for p in people if p.name.lower().split()[0] == word]
    if len(first) == 1:
        return first[0]
    if len(first) > 1:
        return first
    return None


def resolve_target(token: str, people: list[Person], sender_id: int):
    """('everyone', None) | ('people', [Person…]) | ('unknown', None) | ('ambiguous', [Person…])."""
    word = token.strip().lower().lstrip("@").strip(" .,")
    if word in _EVERYONE_WORDS:
        return "everyone", None
    found: list[Person] = []
    for part in re.split(r"\s*(?:,|\band\b|&)\s*", token.strip(), flags=re.IGNORECASE):
        hit = _match_one(part, people)
        if isinstance(hit, list):
            return "ambiguous", hit
        if hit and hit.id != sender_id and hit not in found:
            found.append(hit)
    return ("people", found) if found else ("unknown", None)


def _is_known(token: str, people: list[Person]) -> bool:
    word = token.strip().lower().lstrip("@").strip(" .,")
    return word in _EVERYONE_WORDS or any(
        _match_one(part, people) for part in re.split(r"\s*(?:,|\band\b|&)\s*", token.strip(), flags=re.IGNORECASE)
    )


_NOT_A_NAME = {
    "me", "us", "you", "him", "her", "them", "it", "this", "that", "these", "those", "myself", "someone", "anyone",
    "somebody", "everything", "nothing", "how", "what", "when", "why", "who", "where", "if", "my", "our", "your",
}
_STRICT_VERBS = re.compile(r"^\s*(?:(?:please|pls|plz|can you|could you|just)\s+)*(?:tell|ping|inform|notify|message|msg|dm)\b", re.I)


def _looks_like_a_name(who: str, text: str, pattern) -> bool:
    """
    "tell Zubin the build is broken" where Zubin is nobody on the team: still a message, so the bot can
    say it doesn't know Zubin instead of ignoring it. Only for a capitalised word or an @handle after a
    clear verb (tell/ping/inform/notify/message/dm), never for "tell me", "ask him", "update T3".
    """
    word = who.strip()
    plain = word.lstrip("@")
    if not plain or plain.lower() in _NOT_A_NAME or re.fullmatch(r"T\d+", plain, re.I) or " " in word:
        return False
    if pattern is _HINGLISH:
        return word.startswith("@") or word[:1].isupper()
    if not _STRICT_VERBS.match(text):
        return False
    return word.startswith("@") or word[:1].isupper()


def _clean(body: str) -> str:
    return re.sub(r"\s+", " ", body).strip()


def parse_directed(text: str, participants: list[dict], sender: dict) -> Interpretation | None:
    """
    Recognise a message that is addressed to someone: "@Rohan …", "tell the lead that …",
    "Rohan, …", "Rohan ko bolo …". Returns None when the message is about the sender's own work, so
    "done @Priya please review" and every ordinary status update still go to the Coordinator Agent.
    """
    text = (text or "").strip()
    if not text or text.startswith("/") or len(text) > 1500:
        return None
    people = [p for p in _people(participants) if p.id != sender.get("id")]   # "Meera, done" from Meera is a status

    for pattern in (_VERB_FIRST, _HINGLISH):
        m = pattern.match(text)
        if m and (_is_known(m.group("who"), people) or _looks_like_a_name(m.group("who"), text, pattern)):
            body = _clean(m.group("body"))
            if body:
                return Interpretation(intent="message_relay", messages=[RelayOut(to=_clean(m.group("who")), text=body)],
                                      raw_message=text)

    m = _ADDRESSED.match(text)
    if m:
        who = m.group("who")
        # Plain "name word…" is only an address when it starts with @, or has a comma/colon after the
        # name ("Rohan, can you…"), or is the word "lead". A bare "Meera done" must stay a status.
        raw_start = text.lstrip()
        lowered = raw_start.lower()
        at_mention = bool(re.match(r"(?:(?:hey|hi|hello|yo|oye)\s+)?@", lowered))
        punctuated = bool(re.match(r"(?:(?:hey|hi|hello|yo|oye|to|for)\s+)?@?\w[\w.'-]*\s*[:,]", lowered))
        if _is_known(who, people) and (at_mention or punctuated):
            body = _clean(m.group("body"))
            if body:
                return Interpretation(intent="message_relay", messages=[RelayOut(to=_clean(who), text=body)],
                                      raw_message=text)
    return None


def parse_resolution(text: str, participants: list[dict], sender: dict) -> Interpretation | None:
    """
    The lead clearing someone's blocker from Telegram: "unblock Omar", "T4 is resolved, use the
    new key", "fixed T9". Only the lead can do this; for anyone else it is just a message.
    """
    if sender.get("role") != "lead":
        return None
    text = (text or "").strip()
    if not text or text.startswith("/"):
        return None
    people = _people(participants)
    for pattern in (_RESOLVE_FIRST, _RESOLVE_AFTER):
        m = pattern.match(text)
        if not m:
            continue
        who = m.group("who")
        note = _clean(m.group("note") or "")
        if re.fullmatch(r"T\d+", who, re.IGNORECASE):
            return Interpretation(
                intent="message_relay", raw_message=text,
                messages=[RelayOut(to="", text=note, task_key=who.upper(), resolves_blocker=True)],
            )
        explicit = re.search(r"unblock|blocker|blocked", text, re.IGNORECASE)
        if explicit and _is_known(who, people) and who.lower() not in _EVERYONE_WORDS:
            return Interpretation(
                intent="message_relay", raw_message=text,
                messages=[RelayOut(to=_clean(who), text=note, resolves_blocker=True)],
            )
    return None


def mentioned_people(text: str, participants: list[dict], sender_id: int | None = None) -> list[dict]:
    """People @mentioned in a group message (by Telegram @username, or by a name that has an @ in front)."""
    people = _people(participants)
    by_id = {p["id"]: p for p in participants}
    out: list[dict] = []
    for token in _MENTION.findall(text or ""):
        hit = _match_one(token, people)
        for p in (hit if isinstance(hit, list) else [hit] if hit else []):
            if p.id != sender_id and by_id[p.id] not in out:
                out.append(by_id[p.id])
    return out
