"""Tests für den Mailversand: keine Doppelversendung, keine Mail ohne neue Einträge."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from hr_monitor import mailer
from hr_monitor.config import load_config
from hr_monitor.store import Store


def ev(i, region, datum=None):
    return {"id": f"e{i}", "typ": "neugruendung", "datum": datum or date.today().isoformat(),
            "firma": f"Elektro {i} GmbH", "ort": "Hannover", "gericht": "Hannover",
            "register": f"HRB {i}", "branchen": ["Elektro"], "regionen": [region],
            "entfernung_km": 1.0, "quelle": "Test", "titel": "", "text": "", "link": "#"}


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.cfg = load_config()

    def tearDown(self):
        self.tmp.cleanup()

    def send(self):
        smtp = mock.MagicMock()
        env = {"RESEND_API_KEY": "", "MAIL_TO": "", "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
               "EMPFAENGER_HANNOVER": "a@example.com, b@example.com"}
        with mock.patch.dict(os.environ, env), mock.patch("smtplib.SMTP", return_value=smtp):
            n = mailer.send(self.cfg, self.store)
        return n, smtp

    def test_no_mail_without_events(self):
        n, smtp = self.send()
        self.assertEqual(n, 0)
        smtp.send_message.assert_not_called()

    def test_sent_events_are_not_repeated(self):
        self.store.add_event(ev(1, "hannover"))
        n, smtp = self.send()
        self.assertEqual(n, 1)
        _, kwargs = smtp.send_message.call_args
        self.assertEqual(kwargs["to_addrs"], ["a@example.com", "b@example.com"])
        # zweiter Lauf ohne neue Einträge: keine Mail
        n, _ = self.send()
        self.assertEqual(n, 0)
        # neuer Eintrag: Mail nur mit dem neuen Eintrag
        self.store.add_event(ev(2, "hannover"))
        self.assertEqual([e["id"] for e in mailer.pending_events(
            self.cfg, self.store, self.cfg.regionen[0])], ["e2"])

    def test_regions_without_recipients_are_not_marked_sent(self):
        self.store.add_event(ev(3, "wolfsburg"))
        self.send()  # keine EMPFAENGER_WOLFSBURG gesetzt
        wolfsburg = next(r for r in self.cfg.regionen if r.slug == "wolfsburg")
        self.assertEqual(len(mailer.pending_events(self.cfg, self.store, wolfsburg)), 1)

    def test_old_events_are_skipped(self):
        self.store.add_event(ev(4, "hannover", datum="2020-01-01"))
        self.assertEqual(mailer.pending_events(self.cfg, self.store, self.cfg.regionen[0]), [])



class ResendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.cfg = load_config()
        self.store.add_event(ev(1, "hannover"))

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, env, status=200):
        resp = mock.MagicMock(status_code=status, text="fehler")
        resp.json.return_value = {"id": "abc"}
        base = {k: "" for k in ("RESEND_API_KEY", "MAIL_FROM", "MAIL_TO", "SMTP_HOST",
                                "EMPFAENGER_HANNOVER")}
        base.update(env)
        with mock.patch.dict(os.environ, base), \
                mock.patch("hr_monitor.mailer.requests.post", return_value=resp) as post:
            n = mailer.send(self.cfg, self.store, outdir=Path(self.tmp.name) / "out")
        return n, post

    def hannover_pending(self):
        return len(mailer.pending_events(self.cfg, self.store, self.cfg.regionen[0]))

    def test_without_key_mail_is_skipped(self):
        n, post = self.send({"MAIL_TO": "ich@example.com"})
        self.assertEqual(n, 0)
        post.assert_not_called()
        self.assertEqual(self.hannover_pending(), 1)
        self.assertTrue((Path(self.tmp.name) / "out" / "mail-hannover.html").exists())

    def test_test_sender_only_mails_mail_to(self):
        n, post = self.send({"RESEND_API_KEY": "re_x", "MAIL_TO": "ich@example.com",
                             "EMPFAENGER_HANNOVER": "kunde@example.com"})
        self.assertEqual(n, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["from"], "onboarding@resend.dev")
        self.assertEqual(payload["to"], ["ich@example.com"])
        self.assertNotIn("bcc", payload)
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer re_x")
        self.assertEqual(self.hannover_pending(), 0)

    def test_own_domain_uses_region_recipients_in_bcc(self):
        n, post = self.send({"RESEND_API_KEY": "re_x", "MAIL_FROM": "Monitor <hr@firma.de>",
                             "MAIL_TO": "ich@example.com",
                             "EMPFAENGER_HANNOVER": "a@example.com, b@example.com"})
        self.assertEqual(n, 1)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["from"], "Monitor <hr@firma.de>")
        self.assertEqual(payload["to"], ["ich@example.com"])
        self.assertEqual(payload["bcc"], ["a@example.com", "b@example.com"])

    def test_api_error_keeps_events_open(self):
        n, _ = self.send({"RESEND_API_KEY": "re_x", "MAIL_TO": "ich@example.com"}, status=403)
        self.assertEqual(n, 0)
        self.assertEqual(self.hannover_pending(), 1)

    def test_missing_mail_to_with_test_sender(self):
        n, post = self.send({"RESEND_API_KEY": "re_x"})
        self.assertEqual(n, 0)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
