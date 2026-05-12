import io
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

COL_DATE_X1   = 72
COL_DETAIL_X1 = 326
COL_CREDIT_X1 = 368
COL_DEBIT_X1  = 411

DATE_RE = re.compile(r"^\d{2} [A-Za-z]{3} \d{4}$")

GOTYME_SIGNALS = ('GoTyme', 'GoalSave', 'Credits (+)', 'Running Balance', 'Debits (-)')


def is_gotyme(text):
    return any(s in text for s in GOTYME_SIGNALS)


class GoTymeParser:

    def parse(self, pdf_data, password=None):
        import pdfplumber
        transactions = []
        with pdfplumber.open(io.BytesIO(pdf_data), password=password) as pdf:
            current_account = None
            for page in pdf.pages:
                words = self._clean_words(page)
                rows  = self._group_rows(words)
                meta  = self._extract_meta(rows)
                txns  = self._extract_transactions(rows)
                if "account_number" in meta:
                    current_account = meta["account_number"]
                for t in txns:
                    t["account_number"] = current_account
                    transactions.append(t)

        logger.info(f"GoTyme: {len(transactions)} transactions")
        return self._standardise(transactions)

    # ------------------------------------------------------------------ helpers

    def _is_stamp(self, c):
        return c["matrix"][1] != 0.0

    def _clean_words(self, page):
        chars = sorted(
            [c for c in page.chars if not self._is_stamp(c)],
            key=lambda c: (round(c["top"] / 4) * 4, c["x0"])
        )
        if not chars:
            return []
        words, cur = [], [chars[0]]
        for c in chars[1:]:
            prev = cur[-1]
            if abs(c["top"] - prev["top"]) < 4 and (c["x0"] - prev["x1"]) < 4:
                cur.append(c)
            else:
                text = "".join(ch["text"] for ch in cur).strip()
                if text:
                    words.append({"text": text, "x0": cur[0]["x0"], "x1": cur[-1]["x1"], "top": cur[0]["top"]})
                cur = [c]
        text = "".join(ch["text"] for ch in cur).strip()
        if text:
            words.append({"text": text, "x0": cur[0]["x0"], "x1": cur[-1]["x1"], "top": cur[0]["top"]})
        return words

    def _group_rows(self, words):
        rows = {}
        for w in words:
            rows.setdefault(round(w["top"] / 4) * 4, []).append(w)
        return rows

    def _col(self, word):
        x = word["x0"]
        if x < COL_DATE_X1:    return "date"
        if x < COL_DETAIL_X1:  return "detail"
        if x < COL_CREDIT_X1:  return "credit"
        if x < COL_DEBIT_X1:   return "debit"
        return "balance"

    def _extract_meta(self, rows):
        meta = {}
        for y in sorted(rows):
            line = " ".join(w["text"] for w in sorted(rows[y], key=lambda x: x["x0"]))
            if "Account Number:" in line:
                m = re.search(r"Account Number:\s*(\d+)", line)
                if m:
                    meta["account_number"] = m.group(1)
            if "Period:" in line:
                m = re.search(r"Period:\s*(\d{2} \w+ \d{4} - \d{2} \w+ \d{4})", line)
                if m:
                    meta["period"] = m.group(1)
            if "Opening balance" in line:
                m = re.search(r"Opening balance\s+R([\d.,]+)", line)
                if m:
                    meta["opening_balance"] = float(m.group(1).replace(",", ""))
            if "Closing balance" in line:
                m = re.search(r"Closing balance\s+R([\d.,]+)", line)
                if m:
                    meta["closing_balance"] = float(m.group(1).replace(",", ""))
        return meta

    def _extract_transactions(self, rows):
        transactions = []
        current_date = None
        for y in sorted(rows):
            by_col = {"date": [], "detail": [], "credit": [], "debit": [], "balance": []}
            for w in sorted(rows[y], key=lambda w: w["x0"]):
                by_col[self._col(w)].append(w["text"])

            date_str    = " ".join(by_col["date"]).strip()
            detail_str  = " ".join(by_col["detail"]).strip()
            credit_str  = " ".join(by_col["credit"]).strip()
            debit_str   = " ".join(by_col["debit"]).strip()
            balance_str = " ".join(by_col["balance"]).strip()

            if DATE_RE.match(date_str):
                current_date = date_str
            if detail_str == "Details":
                continue
            if not (current_date and detail_str and balance_str):
                continue

            balance = self._amt(balance_str)
            credit  = self._amt(credit_str)
            debit   = self._amt(debit_str)

            if balance is None:
                continue
            if credit is None and debit is None and credit_str != "-" and debit_str != "-":
                continue

            transactions.append({
                "date":    current_date,
                "details": detail_str,
                "credit":  credit,
                "debit":   debit,
                "balance": balance,
            })
        return transactions

    def _amt(self, s):
        s = s.strip().replace(",", "")
        if not s or s == "-":
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _standardise(self, transactions):
        result = []
        for t in transactions:
            try:
                trans_date = datetime.strptime(t["date"], "%d %b %Y").date()
            except ValueError:
                continue
            if t["credit"]:
                amount, trans_type = t["credit"], "credit"
            elif t["debit"]:
                amount, trans_type = t["debit"], "debit"
            else:
                continue
            result.append({
                "date":        trans_date,
                "description": t["details"],
                "amount":      amount,
                "type":        trans_type,
                "reference":   f"GOTYME-{trans_date.strftime('%Y%m%d')}-{len(result)}",
                "balance":     t["balance"],
            })
        return result
