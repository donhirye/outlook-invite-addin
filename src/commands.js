/*
 * Create Invite - Outlook add-in function
 *
 * Flow when the ribbon button is clicked:
 *   1. Read the open email's body (plain text), subject, and sender.
 *   2. Detect the proposed meeting time from the text (e.g. "Thursday at 11:00 AM").
 *   3. Open a pre-filled meeting invite (sender = required attendee) for the user
 *      to review and Send. Nothing is sent automatically.
 *
 * Time detection is relative to when the email was sent, so "Thursday" resolves
 * to the correct calendar date even when you open the email days later.
 */

const DEFAULT_DURATION_MIN = 30;

if (typeof Office !== "undefined") {
  Office.onReady(function () {
    // Register the function so the manifest's ExecuteFunction can call it.
    if (Office.actions && Office.actions.associate) {
      Office.actions.associate("createInvite", createInvite);
    }
  });
}

function createInvite(event) {
  const item = Office.context.mailbox.item;

  // Reference date = when the email was sent (fallback: now). Used to resolve
  // relative day names like "Thursday" / "tomorrow".
  const referenceDate = item.dateTimeCreated ? new Date(item.dateTimeCreated) : new Date();
  const subject = item.subject || "";
  const sender = getSenderAddress(item);

  item.body.getAsync(Office.CoercionType.Text, function (result) {
    let bodyText = "";
    if (result.status === Office.AsyncResultStatus.Succeeded) {
      bodyText = result.value || "";
    }

    const parsed = detectMeeting(bodyText + "\n" + subject, referenceDate);

    const form = {
      requiredAttendees: sender ? [sender] : [],
      subject: buildSubject(subject),
      body: buildBody(item, parsed),
    };

    if (parsed && parsed.start) {
      form.start = parsed.start;
      form.end = parsed.end;
    } else {
      notify(item, "No time detected - opening a blank invite. Set the time manually.");
    }

    Office.context.mailbox.displayNewAppointmentForm(form);
    event.completed();
  });
}

function getSenderAddress(item) {
  // In read mode, the sender is item.from (fallback to item.sender).
  const src = item.from || item.sender;
  if (src && src.emailAddress) return src.emailAddress;
  return "";
}

function buildSubject(originalSubject) {
  // Strip common prefixes so the invite subject reads cleanly.
  let s = (originalSubject || "").trim();
  s = s.replace(/^\s*(\[ext\]|re:|fw:|fwd:)\s*/gi, "").trim();
  s = s.replace(/^\s*(re:|fw:|fwd:)\s*/gi, "").trim();
  return s ? "Meeting: " + s : "Meeting";
}

function buildBody(item, parsed) {
  const lines = [];
  if (parsed && parsed.start) {
    lines.push("Proposed time detected from the email: " + parsed.start.toLocaleString());
  }
  const src = item.from || item.sender;
  if (src && src.displayName) {
    lines.push("Requested by: " + src.displayName);
  }
  lines.push("");
  lines.push("(Auto-created from the email thread. Please review the time and attendees before sending.)");
  return lines.join("\n");
}

function notify(item, text) {
  try {
    item.notificationMessages.replaceAsync("createInviteInfo", {
      type: Office.MailboxEnums.ItemNotificationMessageType.InformationalMessage,
      message: text,
      icon: "icon16",
      persistent: false,
    });
  } catch (e) {
    /* notifications are best-effort */
  }
}

/* ------------------------------------------------------------------ */
/* Lightweight scheduling-text parser (no external dependencies)      */
/* ------------------------------------------------------------------ */

const WEEKDAYS = {
  sunday: 0, sun: 0,
  monday: 1, mon: 1,
  tuesday: 2, tues: 2, tue: 2,
  wednesday: 3, wed: 3,
  thursday: 4, thurs: 4, thur: 4, thu: 4,
  friday: 5, fri: 5,
  saturday: 6, sat: 6,
};

function detectMeeting(text, referenceDate) {
  if (!text) return null;
  const lower = text.toLowerCase();

  const time = findTime(lower);
  const day = findDay(lower, referenceDate);
  const durationMin = findDuration(lower) || DEFAULT_DURATION_MIN;

  // Need at least a time to build a meaningful start; a day alone is ambiguous.
  if (!time) {
    return { start: null, end: null, durationMin: durationMin };
  }

  const base = day ? day : new Date(referenceDate);
  const start = new Date(base.getFullYear(), base.getMonth(), base.getDate(), time.hour, time.minute, 0, 0);

  // If we only had a time (no day) and it's already past today, push to tomorrow.
  if (!day && start.getTime() < referenceDate.getTime()) {
    start.setDate(start.getDate() + 1);
  }

  const end = new Date(start.getTime() + durationMin * 60 * 1000);
  return { start: start, end: end, durationMin: durationMin };
}

function findTime(lower) {
  // 12-hour with am/pm: "11:00 am", "11 am", "2:30pm", "at 9pm"
  let m = lower.match(/(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)/i);
  if (m) {
    let hour = parseInt(m[1], 10);
    const minute = m[2] ? parseInt(m[2], 10) : 0;
    const mer = m[3].replace(/\./g, "").toLowerCase();
    if (mer === "pm" && hour < 12) hour += 12;
    if (mer === "am" && hour === 12) hour = 0;
    if (hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59) {
      return { hour: hour, minute: minute };
    }
  }

  // 24-hour after the word "at": "at 14:00", "at 9:30"
  m = lower.match(/\bat\s+(\d{1,2}):(\d{2})\b/);
  if (m) {
    const hour = parseInt(m[1], 10);
    const minute = parseInt(m[2], 10);
    if (hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59) {
      return { hour: hour, minute: minute };
    }
  }
  return null;
}

function findDay(lower, referenceDate) {
  if (/\btomorrow\b/.test(lower)) {
    const d = new Date(referenceDate);
    d.setDate(d.getDate() + 1);
    return d;
  }
  if (/\btoday\b/.test(lower)) {
    return new Date(referenceDate);
  }

  // Weekday name -> the next occurrence on or after the reference date.
  const dayMatch = lower.match(/\b(sunday|monday|tuesday|wednesday|thursday|friday|saturday|sun|mon|tues|tue|wed|thurs|thur|thu|fri|sat)\b/);
  if (dayMatch) {
    const target = WEEKDAYS[dayMatch[1]];
    const d = new Date(referenceDate);
    const current = d.getDay();
    let delta = (target - current + 7) % 7;
    // "next Thursday" or a same-day reference: 0 means today; keep today unless
    // the phrase explicitly says "next", then push a week.
    if (delta === 0 && /\bnext\b/.test(lower)) delta = 7;
    d.setDate(d.getDate() + delta);
    return d;
  }
  return null;
}

function findDuration(lower) {
  // "30 minutes", "45 min", "for 15 minutes"
  let m = lower.match(/(\d{1,3})\s*(minutes|minute|mins|min)\b/);
  if (m) return parseInt(m[1], 10);

  // "1 hour", "2 hours", "1.5 hours"
  m = lower.match(/(\d+(?:\.\d+)?)\s*(hours|hour|hrs|hr)\b/);
  if (m) return Math.round(parseFloat(m[1]) * 60);

  // "an hour" / "half hour"
  if (/\bhalf\s+hour\b/.test(lower)) return 30;
  if (/\ban?\s+hour\b/.test(lower)) return 60;

  return null;
}

// Allow Node-based testing of the pure parser without a browser/Office runtime.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { detectMeeting, findTime, findDay, findDuration };
}
