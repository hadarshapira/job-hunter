"""Decide what a job email says: application received, rejection, interview invitation, or nothing.

Rules only, in English and Hebrew. Rejection is checked first (rejections often begin with
"thank you for applying"), then interview, then confirmation. Sentences that only say an
interview *might* happen ("if your profile fits, we'll contact you to schedule an interview")
don't count as an invitation.
"""

import re

CONFIRMATION, REJECTION, INTERVIEW = "confirmation", "rejection", "interview"
LABELS = {CONFIRMATION: "Application received", REJECTION: "Rejection", INTERVIEW: "Interview invitation"}


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), re.I)


# Mail that is about jobs in general but never about one of your applications
_IGNORE_SENDER = _rx(r"jobalerts?", r"job-?alerts?", r"jobs-listings", r"newsletter", r"digest", r"notifications-noreply@linkedin",
                     r"messages-noreply@linkedin", r"invitations@linkedin", r"jobs-noreply@glassdoor")
_IGNORE_TEXT = _rx(r"jobs? (you may|you might|that may|we think you)", r"recommended jobs", r"new jobs? (for you|match)",
                   r"job alert", r"your application was viewed", r"application (was )?viewed by", r"משרות (חדשות|מומלצות)",
                   r"התראת משרות")

# The email must be about an application, a position or a candidacy
_JOB_CONTEXT = _rx(r"\bappl(y|ied|ying|ication)", r"\bposition\b", r"\brole\b", r"\bcandida(te|cy)", r"\bopening\b",
                   r"\bvacanc", r"\binterview", r"\brecruit", r"\bhiring\b", r"\bjob\b", r"מועמד", r"משרה", r"משרת", r"תפקיד",
                   r"קורות (ה)?חיים", r"ראיון", r"גיוס")

_REJECTION = _rx(
    r"\bunfortunately\b", r"regret to (inform|let you know|tell you)", r"\bnot (be )?(moving|move) forward",
    r"decided (not to|to (move|proceed|go|continue) (forward )?with (other|another|a different|the other|candidates?|applicants?|profiles?))",
    # "move forward with candidates whose experience is more closely aligned..." (no "other")
    r"(mov|proceed|go|continu|progress)(e|es|ed|ing)? (forward )?with (other |another |different )?(candidates?|applicants?|profiles?) (whose|who|that|with)",
    r"(more|most|better) (closely )?(aligned|suited|match(ing|es)?) (with|to|for) (the|our|this|current)",
    r"(won't|will not|wouldn't|would not|can't|cannot|are unable to) (be )?(mov|proceed|progress|continu)(e|ing) (forward )?with (your|you\b)",
    r"(go|going) (in|with) a different direction",
    r"(will|would) not be (proceeding|moving|continuing|progressing)", r"not (been )?selected", r"other candidates? whose",
    r"(position|role|job) (has|have) (been|now been) filled", r"no longer (considering|being considered|available)",
    r"pursue other candidates", r"(isn't|is not|wasn't|was not) the right (fit|match)", r"decided to pursue",
    r"we (will|won't|will not) (not )?be (taking|progressing) your application",
    r"לצערנו", r"לא נוכל להתקדם", r"לא נמשיך", r"החלטנו (שלא|להתקדם עם מועמד|לא להתקדם)", r"הוחלט (שלא|לא)",
    r"לא נבחרת", r"מועמדים אחרים", r"המשרה (אוישה|כבר אוישה)", r"לא (נתקדם|נמשיך) (בתהליך|איתך)",
)

_INVITE = _rx(
    r"invite you (to|for) (an?|the|a short|our)? ?(interview|call|chat|conversation|meeting|technical|phone|video|first|next|home)",
    r"(like|love|happy|glad|pleased|excited) to (invite|schedule|set up|arrange|book|have) (you|a|an|the)?\s?(interview|call|chat|meeting|time|conversation|phone|video|zoom|first)",
    r"(like|love) to (move forward|proceed|continue) (with you|to the next)", r"schedule (an?|the|your) (interview|call|phone screen|chat)",
    r"\bphone screen", r"(please|kindly) (choose|pick|select|book|let us know) (a )?(time|slot|your availability)",
    r"your availability (for|this|next)", r"(next|first) (stage|step) (of|in) (the|our) (interview|hiring|recruitment) process",
    r"calendly\.com", r"goodtime\.io", r"app\.greenhouse\.io/.*schedul", r"\binterview invitation\b", r"invitation to (an )?interview",
    r"נשמח (לזמן|להזמין|לקבוע|לתאם)", r"לזמן אותך", r"לתאם (איתך )?(ראיון|שיחה|פגישה)", r"לקבוע (איתך )?(ראיון|שיחה|פגישה)",
    r"הזמנה ל(ראיון|שיחה)", r"שיחת (היכרות|טלפון|סינון)", r"מתי (נוח|תהיה זמין|תהיי זמינה)", r"זימון ל(ראיון|שיחה)",
)
# "If your experience fits, we'll contact you to schedule an interview" is not an invitation
_CONDITIONAL = _rx(r"\bif\b", r"\bshould\b", r"\bin case\b", r"\bonce\b", r"\bwill (be in touch|contact|reach)", r"\bmay (contact|reach)",
                   r"\bwould be in touch", r"\bאם\b", r"\bבמידה\b", r"ניצור (איתך )?קשר", r"נחזור אליך")

_CONFIRMATION = _rx(
    r"thanks? (you )?(so much )?for (applying|your application|submitting|your interest in (joining|the|our|working))",
    r"(we('ve| have)?|have) (successfully )?received your (application|resume|cv|candidacy)",
    r"your (application|resume|cv|candidacy) (has been|was|is) (successfully )?(received|submitted|sent)",
    r"application (received|submitted|confirmation)", r"your application (was|has been) sent to", r"successfully applied",
    r"we (got|have got) your application", r"thank you for (considering|choosing) .{0,40} (career|job|position|role)",
    r"קיבלנו את (קורות|מועמדות|פנייתך|בקשתך)", r"תודה (רבה )?על (הגשת|פנייתך|התעניינותך|מועמדותך|שליחת|ההתעניינות|שהגשת)",
    r"מועמדותך (התקבלה|הוגשה|נקלטה)", r"קורות החיים (שלך )?(התקבלו|נקלטו|הגיעו)", r"פנייתך התקבלה",
)

# "If you are not selected..." and "unfortunately we can't answer every applicant" are not rejections
_MAYBE = _rx(r"if", r"should", r"in case", r"אם", r"במידה")
_VOLUME = _rx(r"high (volume|number)", r"(every|each|all) (applicants?|applications?|candidates?)", r"individually",
              r"respond to (all|every|each)", r"לכל (הפניות|המועמדים)")

_SENTENCES = re.compile(r"(?<=[.!?\n])\s+")


def classify(subject: str, text: str, sender: str = "") -> str | None:
    if _IGNORE_SENDER.search(sender or ""):
        return None
    head = f"{subject}\n{text[:6000]}"
    if _IGNORE_TEXT.search(head) and not _CONFIRMATION.search(subject):
        return None
    if not _JOB_CONTEXT.search(head):
        return None
    sentences = _SENTENCES.split(head)
    for sentence in sentences:
        if _REJECTION.search(sentence) and not _MAYBE.search(sentence) and not _VOLUME.search(sentence):
            return REJECTION
    for sentence in sentences:
        if _INVITE.search(sentence) and not _CONDITIONAL.search(sentence):
            return INTERVIEW
    if _CONFIRMATION.search(head):
        return CONFIRMATION
    return None
